'use client';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useTranslations } from 'next-intl';
import {
  AlertCircle,
  Eye,
  EyeOff,
  Lock,
  Mail,
  ShieldCheck
} from 'lucide-react';

import { useLogin } from '@/features/auth/hooks/use-login';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Link } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { AuthInviteEmailBanner } from '@/features/auth/components/auth-invite-email-banner';
import { useAuthEmailFromQuery } from '@/features/auth/lib/auth-query-defaults';
import { formatPublicAuthError } from '@/features/auth/lib/public-auth-error';
import { cn } from '@/lib/utils';

type FormData = {
  email: string;
  password: string;
};

export default function SignInPage() {
  const tAuth = useTranslations('auth');
  const tPage = useTranslations('auth.signInPage');
  const tCommon = useTranslations('common');
  const [showPassword, setShowPassword] = useState(false);
  const emailFromQuery = useAuthEmailFromQuery();

  const schema = z.object({
    email: z.string().email(tAuth('errors.invalidEmail')),
    password: z.string().min(6, tAuth('errors.passwordMinLength'))
  });

  const { mutate, isPending, error } = useLogin();
  const {
    register,
    handleSubmit,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { email: emailFromQuery, password: '' }
  });

  return (
    <div className='relative w-full overflow-hidden rounded-3xl border border-white/40 bg-white/70 p-7 shadow-[0_20px_60px_-20px_rgba(15,23,42,0.25)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_20px_60px_-20px_rgba(0,0,0,0.6)] sm:p-9'>
      <div
        aria-hidden='true'
        className='pointer-events-none absolute inset-x-0 -top-px mx-auto h-px w-3/4 bg-gradient-to-r from-transparent via-primary/60 to-transparent'
      />

      <div className='flex flex-col gap-7'>
        <div className='flex flex-col items-center gap-3 text-center'>
          <div className='flex size-12 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/20'>
            <ShieldCheck className='size-6 text-primary' aria-hidden='true' />
          </div>
          <div className='space-y-1.5'>
            <h1 className='text-2xl font-semibold tracking-tight sm:text-3xl'>
              {tPage('welcomeTitle')}
            </h1>
            <p className='text-sm text-muted-foreground'>
              {tPage('welcomeSubtitle')}
            </p>
          </div>
        </div>

        <AuthInviteEmailBanner />

        <form
          onSubmit={handleSubmit((d) => mutate(d))}
          noValidate
          className='space-y-4'
        >
          <div className='space-y-1.5'>
            <Label htmlFor='email' className='text-sm font-medium'>
              {tAuth('email')}
            </Label>
            <div className='relative'>
              <Mail
                className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground'
                aria-hidden='true'
              />
              <Input
                id='email'
                type='email'
                autoComplete='email'
                autoFocus
                placeholder={tAuth('placeholders.enterEmail')}
                aria-invalid={!!errors.email}
                aria-describedby={errors.email ? 'email-error' : undefined}
                className={cn(
                  'h-11 pl-9',
                  errors.email && 'border-destructive'
                )}
                {...register('email')}
              />
            </div>
            {errors.email && (
              <p
                id='email-error'
                role='alert'
                className='text-xs text-destructive'
              >
                {errors.email.message}
              </p>
            )}
          </div>

          <div className='space-y-1.5'>
            <div className='flex items-center justify-between'>
              <Label htmlFor='password' className='text-sm font-medium'>
                {tAuth('password')}
              </Label>
              <Link
                href={ROUTES.AUTH.FORGOT_PASSWORD}
                className='text-xs font-medium text-primary transition-colors hover:text-primary/80 hover:underline'
              >
                {tAuth('forgotPassword')}
              </Link>
            </div>
            <div className='relative'>
              <Lock
                className='pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground'
                aria-hidden='true'
              />
              <Input
                id='password'
                type={showPassword ? 'text' : 'password'}
                autoComplete='current-password'
                placeholder={tAuth('placeholders.enterPassword')}
                aria-invalid={!!errors.password}
                aria-describedby={
                  errors.password ? 'password-error' : undefined
                }
                className={cn(
                  'h-11 pl-9 pr-10',
                  errors.password && 'border-destructive'
                )}
                {...register('password')}
              />
              <button
                type='button'
                onClick={() => setShowPassword((v) => !v)}
                aria-label={
                  showPassword
                    ? tCommon('hidePassword')
                    : tCommon('showPassword')
                }
                aria-pressed={showPassword}
                className='absolute right-2 top-1/2 inline-flex size-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                tabIndex={-1}
              >
                {showPassword ? (
                  <EyeOff className='size-4' aria-hidden='true' />
                ) : (
                  <Eye className='size-4' aria-hidden='true' />
                )}
              </button>
            </div>
            {errors.password && (
              <p
                id='password-error'
                role='alert'
                className='text-xs text-destructive'
              >
                {errors.password.message}
              </p>
            )}
          </div>

          {error && (
            <div
              role='alert'
              className='flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive'
            >
              <AlertCircle
                className='mt-0.5 size-4 shrink-0'
                aria-hidden='true'
              />
              <span className='leading-relaxed'>
                {formatPublicAuthError(
                  error,
                  tAuth('errors.signInFailed'),
                  tAuth('errors.serverUnavailable')
                )}
              </span>
            </div>
          )}

          <Button
            type='submit'
            size='lg'
            className='mt-2 h-11 w-full text-sm font-semibold shadow-md transition-all hover:shadow-lg'
            loading={isPending}
            disabled={isPending}
          >
            {isPending ? tCommon('processing') : tAuth('signIn')}
          </Button>
        </form>

        <div className='relative flex items-center justify-center'>
          <div className='absolute inset-x-0 top-1/2 h-px bg-border' />
          <span className='relative bg-card px-3 text-[11px] uppercase tracking-wider text-muted-foreground dark:bg-transparent'>
            {tAuth('orContinueWith')}
          </span>
        </div>

        <p className='text-center text-sm text-muted-foreground'>
          {tAuth('dontHaveAccount')}{' '}
          <Link
            href={ROUTES.AUTH.SIGN_UP}
            className='font-medium text-primary transition-colors hover:text-primary/80 hover:underline'
          >
            {tAuth('signUp')}
          </Link>
        </p>
      </div>
    </div>
  );
}
