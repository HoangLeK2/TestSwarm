/**
 * Shape stored in localStorage for UI (avatar, header). Not the same as API `UserOut`.
 */
export type SessionUser = {
  id?: string | null;
  email?: string | null;
  givenName?: string | null;
  picture?: string | null;
  /** From GET /auth/me — `superadmin` | `admin` | `operator`. */
  role?: string | null;
  /** Org membership role from GET /auth/me — `owner` | `member` | `supervisor`. */
  orgRole?: string | null;
};
