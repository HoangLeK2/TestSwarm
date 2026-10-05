from __future__ import annotations

from inspect import Parameter, signature

from db.models.device_platform_session import DevicePlatformSession
from services.device_platform_session import (
    get_or_create_platform_session,
    get_platform_session,
    mark_active,
    mark_login_required,
    mark_readiness_observed,
)


def test_platform_session_mutations_require_an_explicit_platform():
    for operation in (
        get_platform_session,
        get_or_create_platform_session,
        mark_login_required,
        mark_active,
        mark_readiness_observed,
    ):
        platform = signature(operation).parameters["platform"]
        assert platform.default is Parameter.empty, operation.__name__


def test_platform_session_model_has_no_vendor_package_default():
    default = DevicePlatformSession.__table__.c.app_package.default
    assert default is not None
    assert default.arg == ""
