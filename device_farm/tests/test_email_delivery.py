"""SMTP email delivery."""

from unittest.mock import patch

import pytest

from services import email_delivery


@pytest.mark.asyncio
async def test_send_email_returns_false_when_smtp_not_configured():
    with patch.object(email_delivery, "smtp_configured", return_value=False):
        ok = await email_delivery.send_email(
            to="a@example.com",
            subject="Test",
            html_body="<p>Hi</p>",
            text_body="Hi",
        )
    assert ok is False
