"""`/api/devices/live` labels each device with the run it is executing.

The grid filters by scenario off this field, so a wrong label sends an operator
to interrupt the wrong phone.
"""
from __future__ import annotations

import asyncio

from api.routes.public import _attach_live_active_runs


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self._results.pop(0) if self._results else [])


def _info(device_id: str | None) -> dict:
    return {"id": device_id or "", "active_run": None}


def _run(devices_by_serial, results, org_id="org-1"):
    session = _FakeSession(results)
    asyncio.run(_attach_live_active_runs(session, devices_by_serial, org_id))
    return session


def test_attaches_campaign_and_scenario_names():
    devices = {"PHONE1": _info("dev-1"), "PHONE2": _info("dev-2")}
    _run(
        devices,
        [
            [("dev-1", "exec-1", "camp-1", None, "Kết bạn", None)],
            [("camp-1", "Chiến dịch A")],
        ],
    )

    assert devices["PHONE1"]["active_run"] == {
        "execution_id": "exec-1",
        "campaign_id": "camp-1",
        "campaign_name": "Chiến dịch A",
        "scenario_id": None,
        "scenario_name": "Kết bạn",
    }
    # Stays None rather than absent: the dashboard merges snapshots, so the
    # route has to be able to clear a run that finished.
    assert devices["PHONE2"]["active_run"] is None


def test_newest_execution_wins_for_a_device():
    devices = {"PHONE1": _info("dev-1")}
    _run(
        devices,
        [
            [
                ("dev-1", "exec-new", None, "scen-2", None, "Mới"),
                ("dev-1", "exec-old", None, "scen-1", None, "Cũ"),
            ],
            [],
        ],
    )

    assert devices["PHONE1"]["active_run"]["execution_id"] == "exec-new"
    assert devices["PHONE1"]["active_run"]["scenario_name"] == "Mới"


def test_rows_for_devices_outside_the_page_are_ignored():
    devices = {"PHONE1": _info("dev-1")}
    _run(devices, [[("dev-other", "exec-1", None, None, None, None)], []])

    assert devices["PHONE1"]["active_run"] is None


def test_no_query_without_registered_device_ids():
    devices = {"PHONE1": _info(None)}
    session = _run(devices, [[("dev-1", "exec-1", None, None, None, None)]])

    assert session.statements == []
    assert devices["PHONE1"]["active_run"] is None


def test_no_query_without_an_org():
    devices = {"PHONE1": _info("dev-1")}
    session = _run(devices, [[("dev-1", "exec-1", None, None, None, None)]], org_id=None)

    assert session.statements == []


def test_one_query_pair_regardless_of_fleet_size():
    """The device list must not turn into an IN list or a per-device query."""
    devices = {f"PHONE{i}": _info(f"dev-{i}") for i in range(200)}
    session = _run(
        devices,
        [
            [(f"dev-{i}", f"exec-{i}", "camp-1", None, None, None) for i in range(200)],
            [("camp-1", "Chiến dịch A")],
        ],
    )

    assert len(session.statements) == 2
    assert devices["PHONE199"]["active_run"]["campaign_name"] == "Chiến dịch A"
    # Compiles the statement: catches a renamed column, and pins the org+status
    # filter that lets idx_executions_org_status_created carry this query
    # instead of a device-id IN list that grows with the fleet.
    sql = str(session.statements[0])
    assert "executions.org_id = " in sql
    assert "executions.status IN " in sql
    assert "device_id IN" not in sql
    # Named keys only: selecting executions.meta pulls a JSON document per
    # phone on a poll that repeats every few seconds.
    assert "executions.meta," not in sql and "executions.meta " not in sql
