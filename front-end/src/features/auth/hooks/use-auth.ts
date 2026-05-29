'use client';

import { useAuthContext } from '../providers/auth-provider';

export function useUser() {
  const { pending, user } = useAuthContext();

  return {
    user,
    isLoading: pending,
    isSignedIn: !!user
  };
}
