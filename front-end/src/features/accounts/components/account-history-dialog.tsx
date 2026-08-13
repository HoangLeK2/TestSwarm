'use client';

import { History } from 'lucide-react';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { ROUTES } from '@/config/routes';
import type { AccountOut } from '../services/api';

export function AccountHistoryDialog({ account }: { account: AccountOut }) {
  const t = useTranslations('accountsFeature.history');
  const href = `${ROUTES.DASHBOARD.ACTIVITY_HISTORY.ROOT}?account_id=${encodeURIComponent(
    account.id
  )}`;

  return (
    <Button asChild variant='ghost' size='sm' className='h-8 gap-1'>
      <Link href={href}>
        <History className='size-3.5' />
        {t('unifiedTrigger')}
      </Link>
    </Button>
  );
}
