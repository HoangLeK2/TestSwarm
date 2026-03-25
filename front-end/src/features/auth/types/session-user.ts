/**
 * Shape stored in localStorage for UI (avatar, header). Not the same as API `UserOut`.
 */
export type SessionUser = {
  email?: string | null;
  givenName?: string | null;
  picture?: string | null;
};
