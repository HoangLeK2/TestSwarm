# Secrets Rotation Checklist

- Rotate `OPENAI_API_KEY` in provider dashboard and update deployment secrets.
- Rotate `SECRET_KEY` (JWT signing key) and restart all API workers.
- Rotate `RELAY_API_KEY` on server + all relay agents.
- Revoke any previously leaked keys from local `.env` history and CI logs.
- Verify `device_farm/.env` only contains placeholders for tracked values.
- Keep real secrets only in untracked local env files or secret manager.
