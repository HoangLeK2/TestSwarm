'use client';

import React from 'react';
import type { SessionUser } from '../types/session-user';
import { tokenStorage } from '@/lib/token-storage';

type AuthContextValue = {
  pending: boolean;
  user: SessionUser | null;
  setUser: (user: SessionUser | null) => void;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = React.useState(true);
  const [user, setUser] = React.useState<SessionUser | null>(null);

  React.useEffect(() => {
    try {
      setUser(tokenStorage.getUser());
    } finally {
      setPending(false);
    }
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      pending,
      user,
      setUser
    }),
    [pending, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthContext() {
  const ctx = React.useContext(AuthContext);
  if (!ctx) {
    return {
      pending: false,
      user: null,
      setUser: () => {}
    } satisfies AuthContextValue;
  }
  return ctx;
}
