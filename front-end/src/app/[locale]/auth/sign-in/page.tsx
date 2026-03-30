'use client';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useTranslations } from 'next-intl';

import { useLogin } from '@/features/auth/hooks/use-login';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Link } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

type FormData = {
  email: string;
  password: string;
};

export default function SignInPage() {
  const tAuth = useTranslations('auth');
  const tPage = useTranslations('auth.signInPage');
  const tCommon = useTranslations('common');

  const schema = z.object({
    email: z.string().email(tAuth('errors.invalidEmail')),
    password: z
      .string()
      .min(6, tAuth('errors.passwordMinLength'))
  });

  const { mutate, isPending, error } = useLogin();
  const {
    register,
    handleSubmit,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema)
  });

  return (
    <div className='w-full rounded-2xl border border-border/60 bg-card/95 p-8 backdrop-blur-sm sm:p-10'>
      <div className='flex flex-col items-center gap-6'>
        <div className='space-y-1 text-center'>
          <h1 className='text-2xl font-semibold tracking-tight sm:text-3xl'>
            {tPage('welcomeTitle')}
          </h1>
          <p className='text-sm text-muted-foreground'>
            {tPage('welcomeSubtitle')}
          </p>
        </div>

        <form
          onSubmit={handleSubmit((d) => mutate(d))}
          className='mt-2 w-full space-y-5'
        >
          <div className='space-y-1.5'>
            <Label htmlFor='email'>{tAuth('email')}</Label>
            <Input
              id='email'
              type='email'
              autoComplete='email'
              placeholder={tAuth('placeholders.enterEmail')}
              className='h-10'
              {...register('email')}
            />
            {errors.email && (
              <p className='text-xs text-destructive'>{errors.email.message}</p>
            )}
          </div>

          <div className='space-y-1.5'>
            <div className='flex items-center justify-between'>
              <Label htmlFor='password'>{tAuth('password')}</Label>
              <Link
                href={ROUTES.AUTH.FORGOT_PASSWORD}
                className='text-xs font-medium text-primary hover:underline'
              >
                {tAuth('forgotPassword')}
              </Link>
            </div>
            <Input
              id='password'
              type='password'
              autoComplete='current-password'
              placeholder={tAuth('placeholders.enterPassword')}
              className='h-10'
              {...register('password')}
            />
            {errors.password && (
              <p className='text-xs text-destructive'>
                {errors.password.message}
              </p>
            )}
          </div>

          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, tAuth('errors.signInFailed'))}
            </p>
          )}

          <Button
            type='submit'
            className='w-full'
            loading={isPending}
            disabled={isPending}
          >
            {isPending ? tCommon('processing') : tAuth('signIn')}
          </Button>
        </form>

        <p className='mt-6 text-center text-xs text-muted-foreground'>
          {tAuth('dontHaveAccount')}{' '}
          <Link
            href={ROUTES.AUTH.SIGN_UP}
            className='font-medium text-primary hover:underline'
          >
            {tAuth('signUp')}
          </Link>
        </p>
      </div>
    </div>
  );
}
