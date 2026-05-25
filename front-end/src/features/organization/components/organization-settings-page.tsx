'use client';

import Image from 'next/image';
import { Building2, Copy } from 'lucide-react';
import { useFormatter, useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import { formatOrgDisplayName } from '@/features/organization/utils/org-name';

export function OrganizationSettingsPage() {
  const t = useTranslations('organization');
  const format = useFormatter();
  const { currentOrg } = useOrganization();

  if (!currentOrg) {
    return (
      <div className='rounded-lg border border-dashed border-border p-12 text-center'>
        <Building2 className='mx-auto mb-3 size-10 text-muted-foreground' />
        <p className='text-sm text-muted-foreground'>{t('noOrganization')}</p>
      </div>
    );
  }

  const displayName = formatOrgDisplayName(
    currentOrg.businessName,
    t('noName')
  );

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(currentOrg.id);
      toast.success(t('messages.copySuccess'));
    } catch {
      toast.error(t('messages.updateError'));
    }
  };

  return (
    <div className='space-y-6'>
      <div className='flex items-center gap-3'>
        <Building2 className='size-5 text-muted-foreground' />
        <div>
          <h1 className='text-xl font-semibold'>{t('title')}</h1>
          <p className='text-sm text-muted-foreground'>{t('description')}</p>
        </div>
      </div>

      <div className='rounded-lg border border-border bg-card p-6'>
        <div className='flex flex-col gap-6 sm:flex-row sm:items-start'>
          <Image
            src={currentOrg.businessLogo || '/logo.png'}
            alt={displayName}
            width={64}
            height={64}
            className='size-16 rounded-full object-contain'
          />
          <dl className='grid flex-1 gap-4 sm:grid-cols-2'>
            <div>
              <dt className='text-xs text-muted-foreground'>
                {t('fields.businessName')}
              </dt>
              <dd className='mt-1 text-sm font-medium'>{displayName}</dd>
            </div>
            <div>
              <dt className='text-xs text-muted-foreground'>
                {t('fields.businessEmail')}
              </dt>
              <dd className='mt-1 text-sm'>
                {currentOrg.businessEmail || '—'}
              </dd>
            </div>
            <div className='sm:col-span-2'>
              <dt className='text-xs text-muted-foreground'>ID</dt>
              <dd className='mt-1 flex items-center gap-2'>
                <code className='text-xs text-muted-foreground'>
                  {currentOrg.id}
                </code>
                <Button
                  type='button'
                  variant='ghost'
                  size='icon'
                  className='size-7'
                  onClick={() => void copyId()}
                  aria-label={t('copyId')}
                >
                  <Copy className='size-3.5' />
                </Button>
              </dd>
            </div>
            {currentOrg.created_at && (
              <div>
                <dt className='text-xs text-muted-foreground'>
                  {t('fields.createdAt')}
                </dt>
                <dd className='mt-1 text-sm'>
                  {format.dateTime(new Date(currentOrg.created_at), {
                    dateStyle: 'medium',
                    timeStyle: 'short'
                  })}
                </dd>
              </div>
            )}
          </dl>
        </div>
      </div>
    </div>
  );
}
