"""Email HTML templates."""

from services.email_templates import render_organization_invite_email


def test_organization_invite_template_vietnamese_content():
    text, html = render_organization_invite_email(
        inviter="Nguyễn Văn A",
        org_name="Acme Farm",
        accept_url="https://app.example/auth/accept-invite?token=abc",
        existing_user=False,
        recipient_email="guest@example.com",
        expire_days=7,
    )
    assert "Lời mời tham gia" in html
    assert "Chấp nhận lời mời" in html
    assert "guest@example.com" in html
    assert "Acme Farm" in html
    assert "Đăng ký" in html or "đăng ký" in html
    assert "Device Farm" in text
    assert "guest@example.com" in text


def test_organization_invite_template_existing_user_steps():
    _, html = render_organization_invite_email(
        inviter="Owner",
        org_name="Team",
        accept_url="https://app.example/invite",
        existing_user=True,
        recipient_email="member@example.com",
        expire_days=3,
    )
    assert "đăng nhập" in html.lower()
    assert "3 ngày" in html or "3" in html
