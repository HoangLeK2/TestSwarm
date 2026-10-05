from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from services.account_verification import resolve_platform_identity


def test_resolve_platform_identity_matches_unique_username():
    xml = """<hierarchy><node resource-id="active_account" text="" content-desc="Profile, @Jane.Doe" /></hierarchy>"""

    result = resolve_platform_identity(
        xml,
        expected_username="jane.doe",
        expected_provider_id=None,
        trusted_resource_id="active_account",
    )

    assert result.status == "verified"
    assert result.identifier_type == "username"
    assert result.observed_identifier == "jane.doe"


def test_resolve_platform_identity_prefers_provider_id():
    xml = """<hierarchy><node resource-id="profile_id" text="1000123456789" /></hierarchy>"""

    result = resolve_platform_identity(
        xml,
        expected_username="jane.doe",
        expected_provider_id="1000123456789",
        trusted_resource_id="profile_id",
    )

    assert result.status == "verified"
    assert result.identifier_type == "provider_id"


def test_resolve_platform_identity_does_not_match_display_name_or_substring():
    xml = """<hierarchy><node text="Jane Doe" content-desc="Open jane.doe2 profile" /></hierarchy>"""

    result = resolve_platform_identity(
        xml,
        expected_username="jane.doe",
        expected_provider_id=None,
        trusted_resource_id="active_account",
    )

    assert result.status == "inconclusive"


def test_resolve_platform_identity_rejects_ambiguous_identifier():
    xml = """<hierarchy>
      <node resource-id="active_account" text="@jane.doe" />
      <node resource-id="active_account" content-desc="Switch profile @jane.doe" />
    </hierarchy>"""

    result = resolve_platform_identity(
        xml,
        expected_username="jane.doe",
        expected_provider_id=None,
        trusted_resource_id="active_account",
    )

    assert result.status == "inconclusive"
    assert result.reason == "ambiguous_identifier"


def test_resolve_platform_identity_requires_trusted_resource_id():
    xml = """<hierarchy><node text="Post by @jane.doe" /></hierarchy>"""

    result = resolve_platform_identity(
        xml,
        expected_username="jane.doe",
        expected_provider_id=None,
        trusted_resource_id=None,
    )

    assert result.status == "inconclusive"
    assert result.reason == "trusted_selector_missing"
