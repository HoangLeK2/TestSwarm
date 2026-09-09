from __future__ import annotations

"""
tests/test_account_import.py — Unit tests for account import logic in db/crud/account.py.

Run: pytest tests/test_account_import.py -v

Tests cover:
- _prepare_account_row: pure validation/normalisation function
- bulk_create_accounts: batch insertion with mocked DB layer
"""

from importlib import import_module
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.crud.account import (
    _BULK_BATCH_SIZE,
    _insert_batch,
    _prepare_account_row,
    bulk_create_accounts,
)
from db.models.account_import_format import AccountImportFormat
from services.account_import_formats import (
    AccountImportFormatError,
    parse_txt_accounts,
    validate_account_import_fields,
)


# ── _prepare_account_row ───────────────────────────────────────────────────────


def test_prepare_valid_row():
    """Valid row → dict with platform lowercased, username stripped."""
    row = {"platform": "Facebook", "username": "  alice  ", "password_encrypted": "tok"}
    result = _prepare_account_row(row, user_id="user-1")
    assert result is not None
    assert result["platform"] == "facebook"
    assert result["username"] == "alice"


def test_prepare_missing_platform_returns_none():
    row = {"username": "alice"}
    assert _prepare_account_row(row, user_id="user-1") is None


def test_prepare_empty_platform_returns_none():
    row = {"platform": "   ", "username": "alice"}
    assert _prepare_account_row(row, user_id="user-1") is None


def test_prepare_missing_username_returns_none():
    row = {"platform": "facebook"}
    assert _prepare_account_row(row, user_id="user-1") is None


def test_prepare_whitespace_only_username_returns_none():
    row = {"platform": "facebook", "username": "   "}
    assert _prepare_account_row(row, user_id="user-1") is None


def test_prepare_password_encrypted_passed_through():
    """password_encrypted field is passed through as-is."""
    row = {"platform": "tiktok", "username": "bob", "password_encrypted": "encrypted_token_xyz"}
    result = _prepare_account_row(row, user_id="u1")
    assert result is not None
    assert result["password_encrypted"] == "encrypted_token_xyz"


def test_prepare_password_encrypted_none_by_default():
    """When password_encrypted is not in the row, it defaults to None."""
    row = {"platform": "instagram", "username": "carol"}
    result = _prepare_account_row(row, user_id="u1")
    assert result is not None
    assert result["password_encrypted"] is None


def test_prepare_optional_fields_default_to_empty_string():
    """display_name, notes, tags default to '' when absent."""
    row = {"platform": "facebook", "username": "dave"}
    result = _prepare_account_row(row, user_id="u1")
    assert result is not None
    assert result["display_name"] == ""
    assert result["notes"] == ""
    assert result["tags"] == ""


def test_prepare_optional_fields_are_stripped():
    row = {
        "platform": "facebook",
        "username": "eve",
        "display_name": "  Eve Smith  ",
        "notes": " some notes ",
        "tags": " tag1 ",
    }
    result = _prepare_account_row(row, user_id="u1")
    assert result is not None
    assert result["display_name"] == "Eve Smith"
    assert result["notes"] == "some notes"
    assert result["tags"] == "tag1"


def test_prepare_user_id_injected():
    row = {"platform": "facebook", "username": "frank"}
    result = _prepare_account_row(row, user_id="owner-42")
    assert result is not None
    assert result["user_id"] == "owner-42"


def test_prepare_org_id_injected():
    row = {"platform": "facebook", "username": "frank"}
    result = _prepare_account_row(row, user_id="owner-42", org_id="org-1")
    assert result is not None
    assert result["org_id"] == "org-1"


def test_prepare_user_id_none():
    row = {"platform": "facebook", "username": "grace"}
    result = _prepare_account_row(row, user_id=None)
    assert result is not None
    assert result["user_id"] is None


def test_prepare_metadata_key_is_empty_dict():
    """The result should have a 'metadata' key equal to {} (not 'account_metadata')."""
    row = {"platform": "facebook", "username": "hank"}
    result = _prepare_account_row(row, user_id="u1")
    assert result is not None
    assert "metadata" in result
    assert result["metadata"] == {}


def test_prepare_metadata_from_login_fields():
    row = {
        "platform": "facebook",
        "username": "ida",
        "email": " ida@example.com ",
        "totp_secret": " JBSW Y3DPE HPK3PXP ",
        "cookies": "c_user=1;xs=2",
        "token": "EAAB",
    }
    result = _prepare_account_row(row, user_id="u1")
    assert result is not None
    assert result["metadata"] == {
        "email": "ida@example.com",
        "totp_secret": "JBSWY3DPEHPK3PXP",
        "cookies": "c_user=1;xs=2",
        "token": "EAAB",
    }


def test_prepare_metadata_aliases_are_normalised():
    row = {
        "platform": "facebook",
        "username": "jane",
        "account_metadata": {"email": "old@example.com", "label": "vip"},
        "login_email": "jane@example.com",
        "authenticator_secret": "abcd",
    }
    result = _prepare_account_row(row, user_id="u1")
    assert result is not None
    assert result["metadata"] == {
        "email": "jane@example.com",
        "label": "vip",
        "totp_secret": "abcd",
    }


def test_txt_format_one_parses_cookies_token_and_email_metadata():
    fmt = AccountImportFormat(
        slug="facebook_uid_password_tfa_cookies_token_email",
        name="Format 1",
        delimiter="|",
        platform="facebook",
        fields=[
            "username",
            "password",
            "totp_secret",
            "cookies",
            "token",
            "email",
            "metadata.email_password",
            "ignore",
        ],
    )
    parsed = parse_txt_accounts(
        (
            "61586957575493|pass123|N57C FFSN E7OE|c_user=1;xs=2|EAAB|"
            "a@example.com|mailpass|\n"
        ),
        fmt,
    )
    assert parsed.total == 1
    assert parsed.invalid == 0
    assert parsed.rows == [
        {
            "platform": "facebook",
            "username": "61586957575493",
            "password": "pass123",
            "totp_secret": "N57C FFSN E7OE",
            "cookies": "c_user=1;xs=2",
            "token": "EAAB",
            "email": "a@example.com",
            "account_metadata": {"email_password": "mailpass"},
        }
    ]


def test_txt_format_two_parses_recovery_email_and_external_id():
    fmt = AccountImportFormat(
        slug="facebook_uid_password_tfa_email_token",
        name="Format 2",
        delimiter="|",
        platform="facebook",
        fields=[
            "username",
            "password",
            "totp_secret",
            "email",
            "metadata.email_password",
            "metadata.recovery_email",
            "token",
            "metadata.external_id",
        ],
    )
    parsed = parse_txt_accounts(
        (
            "61566178707038|pass456|3BMW MSZ6 T4YW|login@example.com|"
            "mailpass|recovery@example.com|M.C544_TOKEN|uuid-1"
        ),
        fmt,
    )
    assert parsed.total == 1
    assert parsed.invalid == 0
    assert parsed.rows[0]["username"] == "61566178707038"
    assert parsed.rows[0]["account_metadata"] == {
        "email_password": "mailpass",
        "recovery_email": "recovery@example.com",
        "external_id": "uuid-1",
    }


def test_txt_format_rejects_unknown_fields():
    with pytest.raises(AccountImportFormatError) as exc:
        validate_account_import_fields(["username", "secret"])
    assert exc.value.code == "IMPORT_FORMAT_FIELD_UNSUPPORTED"


@pytest.mark.asyncio
async def test_account_import_formats_migration_seeds_timestamp_columns():
    migration = import_module("db.migrations.125_account_import_formats")

    class _Dialect:
        name = "postgresql"

    class _Conn:
        dialect = _Dialect()

        def __init__(self):
            self.calls = []

        async def execute(self, statement, params=None):
            self.calls.append((str(statement), params))

    conn = _Conn()

    await migration.upgrade(conn)

    sql_calls = [sql for sql, _params in conn.calls]
    created_default_idx = next(
        index
        for index, sql in enumerate(sql_calls)
        if "ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP" in sql
    )
    updated_default_idx = next(
        index
        for index, sql in enumerate(sql_calls)
        if "ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP" in sql
    )
    seed_idx = next(
        index
        for index, sql in enumerate(sql_calls)
        if "INSERT INTO account_import_formats" in sql
    )

    assert created_default_idx < seed_idx
    assert updated_default_idx < seed_idx
    assert "created_at, updated_at" in sql_calls[seed_idx]
    assert "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP" in sql_calls[seed_idx]


# ── bulk_create_accounts ───────────────────────────────────────────────────────


def _make_db_session() -> AsyncMock:
    """Return a minimal async DB session mock."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_insert_batch_accepts_metadata_column_key():
    db = _make_db_session()
    execute_result = MagicMock()
    execute_result.rowcount = 1
    db.execute.return_value = execute_result

    created = await _insert_batch(
        db,
        [
            {
                "org_id": "org-1",
                "platform": "facebook",
                "username": "user1",
                "password_encrypted": None,
                "display_name": "",
                "notes": "",
                "tags": "",
                "user_id": "u1",
                "metadata": {"email": "user@example.com"},
                "status": "active",
                "state": "active",
                "total_usage_minutes": 0.0,
                "usage_today_minutes": 0.0,
            }
        ],
    )

    assert created == 1


@pytest.mark.asyncio
async def test_bulk_empty_rows_returns_zero():
    db = _make_db_session()
    created, skipped = await bulk_create_accounts(db, [], user_id="u1")
    assert created == 0
    assert skipped == 0


@pytest.mark.asyncio
async def test_bulk_all_valid_no_conflicts():
    """All valid rows, _insert_batch returns len(batch) → (N, 0)."""
    rows = [
        {"platform": "facebook", "username": f"user{i}"}
        for i in range(5)
    ]
    db = _make_db_session()
    with patch("db.crud.account._insert_batch", new_callable=AsyncMock) as mock_insert:
        mock_insert.side_effect = lambda db_, batch: len(batch)
        created, skipped = await bulk_create_accounts(db, rows, user_id="u1")

    assert created == 5
    assert skipped == 0


@pytest.mark.asyncio
async def test_bulk_all_conflicts():
    """_insert_batch returns 0 for all → (0, N) where N = total valid rows."""
    rows = [
        {"platform": "facebook", "username": f"user{i}"}
        for i in range(3)
    ]
    db = _make_db_session()
    with patch("db.crud.account._insert_batch", new_callable=AsyncMock) as mock_insert:
        mock_insert.return_value = 0
        created, skipped = await bulk_create_accounts(db, rows, user_id="u1")

    assert created == 0
    assert skipped == 3


@pytest.mark.asyncio
async def test_bulk_invalid_rows_counted_as_skipped():
    """Rows missing platform → counted in skipped."""
    rows = [
        {"platform": "facebook", "username": "valid_user"},
        {"username": "no_platform"},     # invalid
        {"platform": "", "username": "empty_platform"},  # invalid
    ]
    db = _make_db_session()
    with patch("db.crud.account._insert_batch", new_callable=AsyncMock) as mock_insert:
        mock_insert.side_effect = lambda db_, batch: len(batch)
        created, skipped = await bulk_create_accounts(db, rows, user_id="u1")

    assert created == 1
    assert skipped == 2


@pytest.mark.asyncio
async def test_bulk_batch_size_boundary():
    """With _BULK_BATCH_SIZE=3, 7 valid rows → _insert_batch called 3 times."""
    rows = [
        {"platform": "facebook", "username": f"user{i}"}
        for i in range(7)
    ]
    db = _make_db_session()
    with patch("db.crud.account._BULK_BATCH_SIZE", 3), \
         patch("db.crud.account._insert_batch", new_callable=AsyncMock) as mock_insert:
        mock_insert.side_effect = lambda db_, batch: len(batch)
        created, skipped = await bulk_create_accounts(db, rows, user_id="u1")

    assert mock_insert.call_count == 3  # batches: [3, 3, 1]
    assert created == 7
    assert skipped == 0


@pytest.mark.asyncio
async def test_bulk_batch_sizes_are_correct():
    """Verify actual batch sizes passed to _insert_batch with batch size = 3 and 7 rows."""
    rows = [
        {"platform": "facebook", "username": f"user{i}"}
        for i in range(7)
    ]
    db = _make_db_session()
    call_lengths: list[int] = []

    async def _capture_insert(db_, batch):
        call_lengths.append(len(batch))
        return len(batch)

    with patch("db.crud.account._BULK_BATCH_SIZE", 3), \
         patch("db.crud.account._insert_batch", side_effect=_capture_insert):
        await bulk_create_accounts(db, rows, user_id="u1")

    assert call_lengths == [3, 3, 1]


@pytest.mark.asyncio
async def test_bulk_password_encryption_called():
    """Row with password='plain123' → encrypt_password called."""
    rows = [{"platform": "facebook", "username": "user1", "password": "plain123"}]
    db = _make_db_session()

    encrypted_calls: list[str] = []

    def _mock_encrypt(plain: str) -> str:
        encrypted_calls.append(plain)
        return f"ENCRYPTED:{plain}"

    inserted_batches: list[list[dict]] = []

    async def _capture_insert(db_, batch):
        inserted_batches.append(list(batch))
        return len(batch)

    with patch("db.crud.account._insert_batch", side_effect=_capture_insert), \
         patch("common.crypto.encrypt_password", side_effect=_mock_encrypt):
        await bulk_create_accounts(db, rows, user_id="u1")

    # encrypt_password should have been invoked with the plaintext
    assert "plain123" in encrypted_calls
    assert inserted_batches[0][0]["password_encrypted"] == "ENCRYPTED:plain123"


@pytest.mark.asyncio
async def test_bulk_org_id_passed_to_insert_batch():
    rows = [{"platform": "facebook", "username": "user1"}]
    db = _make_db_session()
    inserted_batches: list[list[dict]] = []

    async def _capture_insert(db_, batch):
        inserted_batches.append(list(batch))
        return len(batch)

    with patch("db.crud.account._insert_batch", side_effect=_capture_insert):
        await bulk_create_accounts(db, rows, user_id="u1", org_id="org-1")

    assert inserted_batches[0][0]["org_id"] == "org-1"


@pytest.mark.asyncio
async def test_bulk_password_encrypted_not_reencrypted():
    """Row with password_encrypted already set → passed through without re-encrypting."""
    rows = [
        {
            "platform": "facebook",
            "username": "user1",
            "password_encrypted": "already_encrypted_token",
        }
    ]
    db = _make_db_session()
    encrypt_calls: list[str] = []

    def _mock_encrypt(plain: str) -> str:
        encrypt_calls.append(plain)
        return f"RE-ENCRYPTED:{plain}"

    inserted_batches: list[list] = []

    async def _capture_insert(db_, batch):
        inserted_batches.append(list(batch))
        return len(batch)

    with patch("db.crud.account._insert_batch", side_effect=_capture_insert), \
         patch("common.crypto.encrypt_password", side_effect=_mock_encrypt):
        await bulk_create_accounts(db, rows, user_id="u1")

    # encrypt_password should NOT have been called at all
    assert encrypt_calls == []
    # The pre-encrypted token is passed through as-is
    assert inserted_batches[0][0]["password_encrypted"] == "already_encrypted_token"
