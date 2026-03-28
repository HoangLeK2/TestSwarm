from __future__ import annotations

"""
tests/test_crypto.py — Unit tests for common/crypto.py.

Run: pytest tests/test_crypto.py -v

Tests cover:
- Dev mode (no key): pass-through behaviour
- Fernet round-trip: encrypt → decrypt → original
- Edge cases: empty string, None, corrupted token
- Key validity and error propagation
"""

import pytest
from cryptography.fernet import Fernet

import common.crypto as crypto_mod
from common.crypto import decrypt_password, encrypt_password, is_encryption_enabled


# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid_key() -> str:
    return Fernet.generate_key().decode()


# ── Dev mode (no key) ─────────────────────────────────────────────────────────


def test_dev_mode_encrypt_returns_plain(monkeypatch):
    """When _KEY_RAW is None, encrypt_password returns the plaintext unchanged."""
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", None)
    assert encrypt_password("secret123") == "secret123"


def test_dev_mode_decrypt_returns_input(monkeypatch):
    """When _KEY_RAW is None, decrypt_password returns the input unchanged."""
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", None)
    assert decrypt_password("some_token") == "some_token"


def test_dev_mode_is_encryption_enabled_false(monkeypatch):
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", None)
    assert is_encryption_enabled() is False


# ── Round-trip with real Fernet key ──────────────────────────────────────────


def test_round_trip_encrypt_decrypt(monkeypatch):
    """encrypt then decrypt → original plaintext."""
    key = _valid_key()
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", key)
    plain = "my_super_secret_password"
    token = encrypt_password(plain)
    assert token != plain  # should be encrypted
    assert decrypt_password(token) == plain


def test_round_trip_unicode(monkeypatch):
    """Round-trip works for non-ASCII passwords."""
    key = _valid_key()
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", key)
    plain = "mật_khẩu_123"
    assert decrypt_password(encrypt_password(plain)) == plain


# ── Encrypt empty string ──────────────────────────────────────────────────────


def test_encrypt_empty_string_dev_mode(monkeypatch):
    """Empty string → returned as-is in dev mode."""
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", None)
    assert encrypt_password("") == ""


def test_encrypt_empty_string_with_key(monkeypatch):
    """Empty string → returned as-is even when a key is configured (early return)."""
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", _valid_key())
    assert encrypt_password("") == ""


# ── Decrypt None ──────────────────────────────────────────────────────────────


def test_decrypt_none_returns_empty_string(monkeypatch):
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", None)
    assert decrypt_password(None) == ""


def test_decrypt_none_with_key_returns_empty_string(monkeypatch):
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", _valid_key())
    assert decrypt_password(None) == ""


# ── Decrypt corrupted token ───────────────────────────────────────────────────


def test_decrypt_corrupted_token_returns_empty(monkeypatch):
    """Garbage ciphertext → decrypt_password returns '' without raising."""
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", _valid_key())
    result = decrypt_password("this_is_not_a_valid_fernet_token_at_all!!!")
    assert result == ""


def test_decrypt_short_garbage_returns_empty(monkeypatch):
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", _valid_key())
    result = decrypt_password("abc")
    assert result == ""


# ── is_encryption_enabled() True ─────────────────────────────────────────────


def test_is_encryption_enabled_true_when_key_set(monkeypatch):
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", _valid_key())
    assert is_encryption_enabled() is True


# ── Fernet non-determinism ────────────────────────────────────────────────────


def test_encrypt_non_deterministic(monkeypatch):
    """Fernet uses random IV — two encryptions of the same plaintext differ."""
    key = _valid_key()
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", key)
    plain = "password"
    token_a = encrypt_password(plain)
    token_b = encrypt_password(plain)
    # Ciphertexts must differ (random IV)
    assert token_a != token_b
    # But both must decrypt to the same plaintext
    assert decrypt_password(token_a) == plain
    assert decrypt_password(token_b) == plain


# ── Invalid key raises RuntimeError ──────────────────────────────────────────


def test_invalid_key_raises_runtime_error(monkeypatch):
    """A non-Fernet key string → RuntimeError on encrypt (not a silent failure)."""
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", "bad_key_not_base64_fernet")
    with pytest.raises(RuntimeError):
        encrypt_password("test")


def test_invalid_key_raises_runtime_error_on_decrypt(monkeypatch):
    """Same bad-key check for decrypt path."""
    monkeypatch.setattr(crypto_mod, "_KEY_RAW", "another_bad_key")
    with pytest.raises(RuntimeError):
        decrypt_password("some_token")
