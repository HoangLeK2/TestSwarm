'use client';

import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { Mail } from 'lucide-react';
import { Link, useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { Button } from '@/components/ui/button';
import { authApi } from '@/features/auth/services/api';
import { useAuthContext } from '@/features/auth/providers/auth-provider';
import {
  acceptOrganizationInvitation,
  previewOrganizationInvitation,
  type OrganizationInvitationPreview
} from '@/features/organization/services/farm-org-api';
import { saveOrgInviteToken } from '@/features/organization/lib/invite-token';
import { formatOrgInviteAcceptError } from '@/features/organization/lib/format-org-invite-error';
import { tokenStorage } from '@/lib/token-storage';

function normalizeEmail(value: string | null | undefined): string {
  return (value || '').trim().toLowerCase();
}

export function AcceptInviteClient() {
  const t = useTranslations('organization.inviteAccept');
  const { setUser } = useAuthContext();
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = (searchParams.get('token') || '').trim();

  const [preview, setPreview] = useState<OrganizationInvitationPreview | null>(
    null
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sessionEmail, setSessionEmail] = useState<string | null>(null);
  const [sessionChecked, setSessionChecked] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [accepted, setAccepted] = useState(false);

  useEffect(() => {
    if (!token) {
      setLoadError(t('missingToken'));
      return;
    }
    setLoadError(null);
    saveOrgInviteToken(token);
    let cancelled = false;
    previewOrganizationInvitation(token)
      .then((data) => {
        if (!cancelled) setPreview(data);
      })
      .catch(() => {
        if (!cancelled) setLoadError(t('invalidToken'));
      });
    return () => {
      cancelled = true;
    };
  }, [token, t]);

  useEffect(() => {
    if (!preview || !tokenStorage.isAuthenticated()) {
      setSessionEmail(null);
      setSessionChecked(true);
      return;
    }

    let cancelled = false;
    setSessionChecked(false);
    authApi
      .me()
      .then((user) => {
        if (!cancelled) setSessionEmail(normalizeEmail(user.email));
      })
      .catch(() => {
        if (!cancelled) setSessionEmail(null);
      })
      .finally(() => {
        if (!cancelled) setSessionChecked(true);
      });

    return () => {
      cancelled = true;
    };
  }, [preview?.email, preview?.status]);

  const tryAcceptWhileLoggedIn = useCallback(async () => {
    if (!token || !tokenStorage.isAuthenticated()) return;
    setAccepting(true);
    setLoadError(null);
    try {
      await acceptOrganizationInvitation(token);
      setAccepted(true);
      router.push(ROUTES.DEVICES.ROOT);
    } catch (err) {
      setLoadError(formatOrgInviteAcceptError(err, t, t('acceptFailed')));
    } finally {
      setAccepting(false);
    }
  }, [router, t, token]);

  useEffect(() => {
    if (!preview || preview.expired || preview.status !== 'pending') return;
    if (!sessionChecked || !tokenStorage.isAuthenticated()) return;

    const invitedEmail = normalizeEmail(preview.email);
    const currentEmail = normalizeEmail(sessionEmail);
    if (!currentEmail || currentEmail !== invitedEmail) {
      return;
    }

    void tryAcceptWhileLoggedIn();
  }, [preview, sessionChecked, sessionEmail, tryAcceptWhileLoggedIn]);

  const handleSwitchAccount = () => {
    tokenStorage.clearTokens();
    setUser(null);
    setSessionEmail(null);
    setLoadError(null);
    setSessionChecked(true);
  };

  if (!token) {
    return (
      <InviteShell>
        <p className='text-center text-sm text-destructive'>
          {t('missingToken')}
        </p>
        <Button asChild className='w-full'>
          <Link href={ROUTES.AUTH.SIGN_IN}>{t('goSignIn')}</Link>
        </Button>
      </InviteShell>
    );
  }

  if (!preview) {
    return (
      <InviteShell>
        <p className='text-center text-sm text-muted-foreground'>
          {t('loading')}
        </p>
      </InviteShell>
    );
  }

  if (preview.expired || preview.status !== 'pending') {
    return (
      <InviteShell>
        <p className='text-center text-sm text-destructive'>{t('expired')}</p>
        <Button asChild className='w-full'>
          <Link href={ROUTES.AUTH.SIGN_IN}>{t('goSignIn')}</Link>
        </Button>
      </InviteShell>
    );
  }

  if (accepted) {
    return (
      <InviteShell>
        <p className='text-center text-sm text-muted-foreground'>
          {t('accepted')}
        </p>
      </InviteShell>
    );
  }

  const invitedEmail = normalizeEmail(preview.email);
  const currentEmail = normalizeEmail(sessionEmail);
  const isWrongAccount =
    sessionChecked &&
    tokenStorage.isAuthenticated() &&
    Boolean(currentEmail) &&
    currentEmail !== invitedEmail;

  const signInHref = `${ROUTES.AUTH.SIGN_IN}?email=${encodeURIComponent(preview.email)}`;

  if (isWrongAccount) {
    return (
      <InviteShell>
        <div className='space-y-1.5 text-center'>
          <h1 className='text-2xl font-semibold tracking-tight'>
            {t('title')}
          </h1>
          <p className='text-sm text-muted-foreground'>
            {t('subtitle', { org: preview.organizationName })}
          </p>
        </div>
        <p className='text-center text-sm text-amber-700 dark:text-amber-400'>
          {t('wrongAccountLoggedIn', {
            currentEmail: sessionEmail ?? '',
            invitedEmail: preview.email
          })}
        </p>
        <p className='text-center text-xs text-muted-foreground'>
          {t('useAnotherAccount')}
        </p>
        <Button
          type='button'
          variant='outline'
          className='w-full'
          onClick={handleSwitchAccount}
        >
          {t('switchAccount')}
        </Button>
        <InviteActions preview={preview} signInHref={signInHref} t={t} />
      </InviteShell>
    );
  }

  if (loadError) {
    return (
      <InviteShell>
        <p className='text-center text-sm text-destructive'>{loadError}</p>
        <InviteActions preview={preview} signInHref={signInHref} t={t} />
      </InviteShell>
    );
  }

  return (
    <InviteShell>
      <div className='space-y-1.5 text-center'>
        <h1 className='text-2xl font-semibold tracking-tight'>{t('title')}</h1>
        <p className='text-sm text-muted-foreground'>
          {t('subtitle', { org: preview.organizationName })}
        </p>
      </div>
      <p className='flex items-center justify-center gap-2 text-sm'>
        <Mail className='size-4 text-muted-foreground' aria-hidden />
        <span>{preview.email}</span>
      </p>
      <p className='text-center text-sm text-muted-foreground'>
        {preview.existingUser ? t('existingUserHint') : t('newUserHint')}
      </p>
      <InviteActions preview={preview} signInHref={signInHref} t={t} />
      {accepting ? (
        <p className='text-center text-xs text-muted-foreground'>
          {t('accepting')}
        </p>
      ) : null}
    </InviteShell>
  );
}

function InviteActions({
  preview,
  signInHref,
  t
}: {
  preview: OrganizationInvitationPreview;
  signInHref: string;
  t: (key: string) => string;
}) {
  if (!preview.existingUser) {
    return (
      <div className='flex flex-col gap-2'>
        <Button asChild variant='outline' size='lg' className='w-full'>
          <Link href={signInHref}>{t('signIn')}</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className='flex flex-col gap-2'>
      <Button asChild size='lg' className='w-full'>
        <Link href={signInHref}>{t('signIn')}</Link>
      </Button>
    </div>
  );
}

function InviteShell({ children }: { children: React.ReactNode }) {
  return (
    <div className='relative w-full overflow-hidden rounded-3xl border border-white/40 bg-white/70 p-7 shadow-[0_20px_60px_-20px_rgba(15,23,42,0.25)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 sm:p-9'>
      <div className='flex flex-col gap-6'>{children}</div>
    </div>
  );
}
