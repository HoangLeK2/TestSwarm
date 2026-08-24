'use client';

import { useEffect, useState } from 'react';
import { Loader2, Search, UserPlus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import {
  useAccounts,
  useAssignAccountsToDevice,
  useDeviceAccounts,
  useSetPrimaryDeviceAccount
} from '@/features/accounts/hooks/use-accounts';
import { cn } from '@/lib/utils';

/**
 * Rows the picker shows. The list is a shortcut, not an account browser — an
 * org runs thousands of accounts, so the search goes to the server and only
 * this many rows are ever fetched or rendered.
 */
const MAX_SUGGESTIONS = 5;
const SEARCH_DEBOUNCE_MS = 300;

type Props = {
  /** Phone the step editor previews against; null when none is selected. */
  deviceId: string | null;
  /** Step platform — the gate only ever checks one, so filter to it. */
  platform?: string | null;
};

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className='border-t bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground'>
      {children}
    </div>
  );
}

/**
 * Bind a primary account to the previewed phone, from inside the step editor.
 *
 * The session gate fails at run time with `facebook_ready_without_matching_provenance`
 * when the phone carries no account the farm knows about. Reading "Phone chưa có
 * tài khoản chính" and being left with no control meant leaving the scenario
 * half-edited to go find the device page.
 */
export function SessionGateAccountBinder({ deviceId, platform }: Props) {
  const t = useTranslations('campaignsFeature.stepEditor.sessionGate');
  const perms = useResourcePermissions('accounts');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [pendingId, setPendingId] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSearch(search.trim()),
      SEARCH_DEBOUNCE_MS
    );
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data: links = [] } = useDeviceAccounts(deviceId ?? '');
  // Fetch one row past what is shown — that extra row is how we know to tell
  // the operator there are more matches, without fetching a page to count.
  const { data: accounts = [], isLoading } = useAccounts({
    limit: MAX_SUGGESTIONS + 1,
    ...(platform ? { platform } : {}),
    ...(debouncedSearch ? { search: debouncedSearch } : {})
  });
  const assign = useAssignAccountsToDevice();
  const setPrimary = useSetPrimaryDeviceAccount();

  if (!deviceId) return <Notice>{t('bindNoPhone')}</Notice>;
  if (!perms.canUpdate) return <Notice>{t('bindNoPermission')}</Notice>;

  const linkedIds = new Set(links.map((link) => link.account_id));
  const suggestions = accounts.slice(0, MAX_SUGGESTIONS);
  const hasMore = accounts.length > suggestions.length;
  const busy = pendingId !== null;

  async function bind(accountId: string) {
    if (!deviceId || busy) return;
    setPendingId(accountId);
    try {
      // A phone can carry several accounts; the gate reads the primary one, so
      // link first (when new) and then promote — one click, both steps.
      if (!linkedIds.has(accountId)) {
        await assign.mutateAsync({ deviceId, accountIds: [accountId] });
      }
      await setPrimary.mutateAsync({ deviceId, accountId });
      toast.success(t('bindSuccess'));
      setSearch('');
    } catch {
      toast.error(t('bindError'));
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className='space-y-2 border-t bg-muted/20 px-3 py-2.5'>
      <div className='flex items-start gap-2'>
        <UserPlus className='mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-500' />
        <p className='text-[11px] leading-snug text-muted-foreground'>
          {t('bindHint')}
        </p>
      </div>

      <div className='relative'>
        <Search className='pointer-events-none absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted-foreground' />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t('bindSearchPlaceholder')}
          className='h-7 bg-background pl-7 text-xs'
        />
      </div>

      {isLoading ? (
        <p className='py-1 text-[11px] text-muted-foreground'>{t('loading')}</p>
      ) : suggestions.length === 0 ? (
        <p className='py-1 text-[11px] text-muted-foreground'>
          {t('bindNoAccounts')}
        </p>
      ) : (
        <ul className='space-y-1'>
          {suggestions.map((account) => {
            const name = account.display_name || account.username;
            const pending = pendingId === account.id;
            return (
              <li key={account.id}>
                <button
                  type='button'
                  disabled={busy}
                  onClick={() => bind(account.id)}
                  className={cn(
                    'group flex w-full items-center gap-2 rounded-md border bg-background px-2 py-1.5 text-left transition-colors',
                    'hover:border-primary/40 hover:bg-primary/5',
                    'disabled:pointer-events-none disabled:opacity-60'
                  )}
                >
                  <span className='flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-semibold uppercase text-muted-foreground'>
                    {name.slice(0, 1)}
                  </span>
                  <span className='min-w-0 flex-1'>
                    <span className='block truncate text-xs font-medium'>
                      {name}
                    </span>
                    {account.display_name ? (
                      <span className='block truncate text-[10px] text-muted-foreground'>
                        {account.username}
                      </span>
                    ) : null}
                  </span>
                  {pending ? (
                    <Loader2 className='size-3.5 shrink-0 animate-spin text-primary' />
                  ) : (
                    <span className='shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors group-hover:bg-primary group-hover:text-primary-foreground'>
                      {t('bindCta')}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {hasMore ? (
        <p className='text-[10px] text-muted-foreground'>
          {t('bindMoreResults', { count: MAX_SUGGESTIONS })}
        </p>
      ) : null}
    </div>
  );
}
