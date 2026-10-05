from __future__ import annotations

from types import SimpleNamespace

from api.org_scope import data_owner_user_id


def test_data_owner_user_id_none_when_org_context():
    user = SimpleNamespace(id="user-1", org_id="org-1", role="operator")
    assert data_owner_user_id(user) is None


def test_data_owner_user_id_self_without_org():
    user = SimpleNamespace(id="user-1", org_id=None, role="operator")
    assert data_owner_user_id(user) == "user-1"


def test_data_owner_user_id_none_for_superadmin():
    user = SimpleNamespace(id="admin-1", org_id="org-1", role="superadmin")
    assert data_owner_user_id(user) is None
