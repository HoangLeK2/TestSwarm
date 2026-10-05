"""Platform admin CLI (DF-T-01-006)."""
from __future__ import annotations

import argparse
import secrets
import sys
import time


def _cmd_rotate_jwt_secret(args: argparse.Namespace) -> int:
    new_secret = secrets.token_urlsafe(48)
    current_kid = (args.current_kid or "v1").strip()
    next_kid = (args.next_kid or f"v{int(current_kid.lstrip('v') or '1') + 1}").strip()
    rotated_at = int(time.time())
    print("# JWT rotation — apply these env vars, then rolling restart pods")
    print(f"JWT_SECRET_PREVIOUS_KID={current_kid}")
    print(f"JWT_SECRET_PREVIOUS={args.current_secret or '<copy current SECRET_KEY>'}")
    print(f"JWT_SECRET_PREVIOUS_ROTATED_AT={rotated_at}")
    print(f"JWT_ACTIVE_KID={next_kid}")
    print(f"SECRET_KEY={new_secret}")
    print(f"# overlap window: {args.overlap_hours}h (JWT_SECRET_OVERLAP_HOURS)")
    if args.emit_audit:
        print("# remember to emit audit event secret.rotated after deploy")
    return 0


def _cmd_secret_age_check(args: argparse.Namespace) -> int:
    from auth.secret_versioning import reload_jwt_secrets, secret_age_days

    reload_jwt_secrets()
    ages = secret_age_days()
    threshold = args.max_age_days
    exit_code = 0
    for kid, age in ages.items():
        if age >= threshold:
            print(f"ALERT: JWT signing key {kid} age {age:.1f} days > {threshold}")
            exit_code = 1
        else:
            print(f"OK: JWT signing key {kid} age {age:.1f} days")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="df-admin")
    sub = parser.add_subparsers(dest="command", required=True)

    rotate = sub.add_parser("rotate-jwt-secret", help="Print env vars for zero-downtime JWT rotation")
    rotate.add_argument("--current-kid", default="v1")
    rotate.add_argument("--next-kid", default="")
    rotate.add_argument("--current-secret", default="")
    rotate.add_argument("--overlap-hours", type=int, default=24)
    rotate.add_argument("--emit-audit", action="store_true")
    rotate.set_defaults(func=_cmd_rotate_jwt_secret)

    age = sub.add_parser("secret-age-check", help="Warn when JWT signing key exceeds max age")
    age.add_argument("--max-age-days", type=int, default=90)
    age.set_defaults(func=_cmd_secret_age_check)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
