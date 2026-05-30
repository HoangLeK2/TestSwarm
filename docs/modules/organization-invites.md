# Organization member invitations

Status: active

## Flow

1. Owner calls `POST /api/organizations/members` with `{ "email": "..." }`.
2. Backend creates/refreshes a row in `organization_invitations` and sends email (Jinja template under `device_farm/templates/email/`).
3. Recipient opens `/auth/accept-invite?token=...` on the dashboard.
4. **Existing user:** sign in → `POST /api/organizations/invitations/accept`.
5. **New user:** sign up (optional `inviteToken` on register) → sign in → accept.

## Configuration

| Variable | Purpose |
|----------|---------|
| `DEVICE_FARM_FRONTEND_URL` | Base URL in invite links |
| `ORG_INVITE_EXPIRE_DAYS` | Token TTL (default 7) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Outbound mail via aiosmtplib |

When `SMTP_HOST` is unset, invitations are still created but `emailSent` is `false` and the accept URL is logged server-side.

## API

| Method | Path | Auth |
|--------|------|------|
| POST | `/organizations/members` | manage |
| GET | `/organizations/invitations/{token}` | public preview |
| POST | `/organizations/invitations/accept` | bearer |
