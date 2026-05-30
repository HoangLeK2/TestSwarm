'use client';

import React from 'react';
import type { SessionUser } from '../types/session-user';
import { tokenStorage } from '@/lib/token-storage';
import { authApi } from '../services/api';

type AuthContextValue = {
  pending: boolean;
  user: SessionUser | null;
  setUser: (user: SessionUser | null) => void;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

function meToSessionUser(me: Awaited<ReturnType<typeof authApi.me>>): SessionUser {
  return {
    id: me.id,
    email: me.email,
    givenName: me.name,
    role: me.role,
    orgRole: me.orgRole ?? null
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = React.useState(true);
  const [user, setUser] = React.useState<SessionUser | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const stored = tokenStorage.getUser();
        setUser(stored);

        if (!tokenStorage.isAuthenticated()) return;

        const me = await authApi.me();
        if (cancelled) return;
        const next = meToSessionUser(me);
        tokenStorage.setUser(next);
        setUser(next);
      } catch {
      } finally {
        if (!cancelled) setPending(false);
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
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
