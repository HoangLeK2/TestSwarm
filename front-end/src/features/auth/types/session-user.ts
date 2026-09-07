/**
 * Shape stored in localStorage for UI (avatar, header). Not the same as API `UserOut`.
 */
export type SessionUser = {
  id?: string | null;
  email?: string | null;
  givenName?: string | null;
  picture?: string | null;
  /** From GET /auth/me — platform role such as `superadmin`, `support`, `system`. */
  role?: string | null;
  /** Org membership role from GET /auth/me — `owner` | `admin` | `member` | `supervisor`. */
  orgRole?: string | null;
  /** Persisted workspace from GET /auth/me (`users.default_org_id`). */
  defaultOrgId?: string | null;
  /** Backend-enforced temporary password state. */
  mustChangePassword?: boolean;
};
