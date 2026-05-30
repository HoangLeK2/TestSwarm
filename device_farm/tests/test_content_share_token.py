from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.auth.content_share import create_content_share_token, verify_content_share_token


def test_share_token_roundtrip():
    token = create_content_share_token(user_id="user-1", content_id="item-1")
    verify_content_share_token(token, content_id="item-1")


def test_share_token_wrong_content_rejected():
    token = create_content_share_token(user_id="user-1", content_id="item-1")
    with pytest.raises(HTTPException) as exc:
        verify_content_share_token(token, content_id="other")
    assert exc.value.status_code == 403
