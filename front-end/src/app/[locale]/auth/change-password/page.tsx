'use client';

import { useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AlertCircle, ShieldCheck } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage
} from '@/components/ui/form';
import { PasswordInput } from '@/components/ui/password-input';
import { ROUTES } from '@/config/routes';
import { useAuthContext } from '@/features/auth/providers/auth-provider';
import { authApi } from '@/features/auth/services/api';
import { useRouter } from '@/i18n/navigation';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { tokenStorage } from '@/lib/token-storage';

type ChangePasswordForm = {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
};

function errorMessage(
  err: unknown,
  messages: {
    fallback: string;
    invalidCurrent: string;
    reused: string;
    weak: string;
  }
): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;
  const code =
    detail && typeof detail === 'object' && !Array.isArray(detail)
      ? (detail as { code?: string }).code
      : null;
  if (code === 'INVALID_CREDENTIALS') return messages.invalidCurrent;
  if (code === 'PASSWORD_REUSED') return messages.reused;
  if (code === 'WEAK_PASSWORD') return messages.weak;
  return formatFarmApiError(err, messages.fallback);
}

function safeReturnTo(value: string | null): string | null {
  const trimmed = value?.trim();
  if (!trimmed || !trimmed.startsWith('/') || trimmed.startsWith('//')) {
    return null;
  }
  return trimmed;
}

export default function ChangePasswordPage() {
  const tAuth = useTranslations('auth');
  const tPage = useTranslations('auth.changePasswordPage');
  const tCommon = useTranslations('common');
  const router = useRouter();
  const searchParams = useSearchParams();
  const { pending, user, setUser } = useAuthContext();
  const returnTo = safeReturnTo(searchParams.get('returnTo'));

  const schema = z
    .object({
      currentPassword: z.string().min(1, tPage('errors.currentRequired')),
      newPassword: z
        .string()
        .min(8, tAuth('errors.passwordMinLength8'))
        .regex(/[A-Z]/, tPage('errors.uppercase'))
        .regex(/[a-z]/, tPage('errors.lowercase'))
        .regex(/\d/, tPage('errors.digit'))
        .regex(/[^A-Za-z0-9]/, tPage('errors.special')),
      confirmPassword: z.string().min(1, tPage('errors.confirmRequired'))
    })
    .refine((data) => data.newPassword === data.confirmPassword, {
      path: ['confirmPassword'],
      message: tAuth('errors.passwordsNoMatch')
    });

  const form = useForm<ChangePasswordForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      currentPassword: '',
      newPassword: '',
      confirmPassword: ''
    }
  });

  const mutation = useMutation({
    mutationFn: (values: ChangePasswordForm) =>
      authApi.changePassword({
        current_password: values.currentPassword,
        new_password: values.newPassword
      }),
    onSuccess: async () => {
      const me = await authApi.me();
      const nextUser = {
        id: me.id,
        email: me.email,
        givenName: me.name,
        role: me.role,
        orgRole: me.orgRole ?? null,
        defaultOrgId: me.defaultOrgId ?? null,
        mustChangePassword: Boolean(me.mustChangePassword)
      };
      tokenStorage.setUser(nextUser);
      setUser(nextUser);
      router.replace(returnTo || ROUTES.DASHBOARD.ROOT);
    }
  });

  useEffect(() => {
    if (pending) return;
    if (!tokenStorage.isAuthenticated()) {
      router.replace(ROUTES.AUTH.SIGN_IN);
      return;
    }
    if (user && !user.mustChangePassword) {
      router.replace(returnTo || ROUTES.DASHBOARD.ROOT);
    }
  }, [pending, returnTo, router, user]);

  return (
    <div className='relative w-full overflow-hidden rounded-3xl border border-white/40 bg-white/70 p-7 shadow-[0_20px_60px_-20px_rgba(15,23,42,0.25)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_20px_60px_-20px_rgba(0,0,0,0.6)] sm:p-9'>
      <div className='flex flex-col gap-7'>
        <div className='flex flex-col items-center gap-3 text-center'>
          <div className='flex size-12 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/20'>
            <ShieldCheck className='size-6 text-primary' aria-hidden='true' />
          </div>
          <div className='space-y-1.5'>
            <h1 className='text-2xl font-semibold tracking-tight sm:text-3xl'>
              {tPage('title')}
            </h1>
            <p className='text-sm text-muted-foreground'>{tPage('subtitle')}</p>
          </div>
        </div>

        {mutation.error && (
          <Alert variant='destructive'>
            <AlertCircle aria-hidden='true' />
            <AlertDescription>
              {errorMessage(mutation.error, {
                fallback: tPage('errors.failed'),
                invalidCurrent: tPage('errors.invalidCurrent'),
                reused: tPage('errors.reused'),
                weak: tPage('errors.weak')
              })}
            </AlertDescription>
          </Alert>
        )}

        <Form {...form}>
          <form
            noValidate
            className='space-y-4'
            onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
          >
            <FormField
              control={form.control}
              name='currentPassword'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{tPage('currentPassword')}</FormLabel>
                  <FormControl>
                    <PasswordInput
                      autoComplete='current-password'
                      disabled={mutation.isPending}
                      className='h-11 pr-10'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='newPassword'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{tAuth('newPassword')}</FormLabel>
                  <FormControl>
                    <PasswordInput
                      autoComplete='new-password'
                      disabled={mutation.isPending}
                      className='h-11 pr-10'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='confirmPassword'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{tAuth('confirmNewPassword')}</FormLabel>
                  <FormControl>
                    <PasswordInput
                      autoComplete='new-password'
                      disabled={mutation.isPending}
                      className='h-11 pr-10'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <p className='text-xs leading-relaxed text-muted-foreground'>
              {tPage('passwordRules')}
            </p>

            <Button
              type='submit'
              size='lg'
              className='h-11 w-full text-sm font-semibold'
              loading={mutation.isPending}
              disabled={mutation.isPending || pending}
            >
              {mutation.isPending ? tCommon('processing') : tPage('submit')}
            </Button>
          </form>
        </Form>
      </div>
    </div>
  );
}
