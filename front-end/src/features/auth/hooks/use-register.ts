'use client';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from '@/i18n/navigation';
import { authApi } from '../services/api';
import { ROUTES } from '@/config/routes';

export function useRegister() {
  const router = useRouter();

  return useMutation({
    mutationFn: authApi.register,
    onSuccess: () => {
      router.push(ROUTES.AUTH.SIGN_IN);
    }
  });
}
