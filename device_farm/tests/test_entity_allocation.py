from types import SimpleNamespace

import pytest

from services.campaign.entity_allocation import (
    EntityAllocationError,
    plan_one_per_device,
)


def _entity(entity_id: str, *, status: str = "candidate"):
    return SimpleNamespace(id=entity_id, status=status)


def test_plan_one_per_device_pairs_in_device_and_pool_order():
    plan = plan_one_per_device(
        device_ids=["device-2", "device-1"],
        entities=[_entity("entity-new"), _entity("entity-old"), _entity("unused")],
    )

    assert [
        (assignment.device_id, assignment.entity.id)
        for assignment in plan.assignments
    ] == [
        ("device-2", "entity-new"),
        ("device-1", "entity-old"),
    ]
    assert plan.available_count == 3


def test_plan_one_per_device_rejects_an_exhausted_pool():
    with pytest.raises(EntityAllocationError) as exc_info:
        plan_one_per_device(
            device_ids=["device-1", "device-2"],
            entities=[_entity("entity-1")],
        )

    assert exc_info.value.code == "ENTITY_POOL_EXHAUSTED"
    assert exc_info.value.details == {
        "device_count": 2,
        "available_entity_count": 1,
        "missing_count": 1,
    }


def test_plan_one_per_device_rejects_unavailable_entities():
    with pytest.raises(EntityAllocationError) as exc_info:
        plan_one_per_device(
            device_ids=["device-1"],
            entities=[_entity("entity-1", status="archived")],
        )

    assert exc_info.value.code == "EXTERNAL_ENTITY_UNAVAILABLE"
    assert exc_info.value.details == {"entity_ids": ["entity-1"]}


def test_plan_one_per_device_scales_to_120_devices_without_extra_sources():
    device_ids = [f"device-{index:03d}" for index in range(120)]
    entities = [_entity(f"entity-{index:03d}") for index in range(200)]

    plan = plan_one_per_device(device_ids=device_ids, entities=entities)

    assert len(plan.assignments) == 120
    assert plan.assignments[-1].device_id == "device-119"
    assert plan.assignments[-1].entity.id == "entity-119"
