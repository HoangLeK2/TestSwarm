'use client';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from '@/i18n/navigation';
import { authApi } from '../services/api';
import { ROUTES } from '@/config/routes';
import {
  consumeOrgInviteToken,
  peekOrgInviteToken
} from '@/features/organization/lib/invite-token';

export function useRegister() {
  const router = useRouter();

  return useMutation({
    mutationFn: (data: Parameters<typeof authApi.register>[0]) => {
      const inviteToken = peekOrgInviteToken();
      return authApi.register({
        ...data,
        ...(inviteToken ? { inviteToken } : {})
      });
    },
    onSuccess: (_data, variables) => {
      const email = encodeURIComponent(variables.email.trim());
      consumeOrgInviteToken();
      router.push(`${ROUTES.AUTH.SIGN_IN}?email=${email}`);
    }
  });
}
