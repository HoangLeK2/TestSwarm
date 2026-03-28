from __future__ import annotations

"""
tests/test_account_import.py — Unit tests for account import logic in db/crud/account.py.

Run: pytest tests/test_account_import.py -v

Tests cover:
- _prepare_account_row: pure validation/normalisation function
- bulk_create_accounts: batch insertion with mocked DB layer
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from db.crud.account import (
    _BULK_BATCH_SIZE,
    _prepare_account_row,
    bulk_create_accounts,
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


# ── bulk_create_accounts ───────────────────────────────────────────────────────


def _make_db_session() -> AsyncMock:
    """Return a minimal async DB session mock."""
    return AsyncMock()


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
async def test_bulk_password_encryption_called(monkeypatch):
    """Row with password='plain123' → encrypt_password called."""
    rows = [{"platform": "facebook", "username": "user1", "password": "plain123"}]
    db = _make_db_session()

    encrypted_calls: list[str] = []

    def _mock_encrypt(plain: str) -> str:
        encrypted_calls.append(plain)
        return f"ENCRYPTED:{plain}"

    with patch("db.crud.account._insert_batch", new_callable=AsyncMock) as mock_insert, \
         patch("common.crypto.encrypt_password", side_effect=_mock_encrypt), \
         patch("db.crud.account.encrypt_password", side_effect=_mock_encrypt):
        mock_insert.side_effect = lambda db_, batch: len(batch)
        await bulk_create_accounts(db, rows, user_id="u1")

    # encrypt_password should have been invoked with the plaintext
    assert "plain123" in encrypted_calls


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
         patch("common.crypto.encrypt_password", side_effect=_mock_encrypt), \
         patch("db.crud.account.encrypt_password", side_effect=_mock_encrypt):
        await bulk_create_accounts(db, rows, user_id="u1")

    # encrypt_password should NOT have been called at all
    assert encrypt_calls == []
    # The pre-encrypted token is passed through as-is
    assert inserted_batches[0][0]["password_encrypted"] == "already_encrypted_token"
