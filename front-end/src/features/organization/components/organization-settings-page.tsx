'use client';

import Image from 'next/image';
import type { ReactNode } from 'react';
import { Building2, Copy } from 'lucide-react';
import { useFormatter, useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import { formatOrgDisplayName } from '@/features/organization/utils/org-name';
import { cn } from '@/lib/utils';

function OrganizationPageHeader({
  title,
  description
}: {
  title: string;
  description: string;
}) {
  return (
    <div className='flex items-start gap-3'>
      <Building2
        className='mt-0.5 size-5 shrink-0 text-muted-foreground'
        aria-hidden
      />
      <div className='min-w-0'>
        <h1 className='text-xl font-semibold tracking-tight'>{title}</h1>
        <p className='text-sm text-muted-foreground'>{description}</p>
      </div>
    </div>
  );
}

function DetailField({
  label,
  children,
  className
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className='text-xs text-muted-foreground'>{label}</dt>
      <dd className='mt-1.5 text-sm'>{children}</dd>
    </div>
  );
}

function OrganizationLogo({
  src,
  alt
}: {
  src: string;
  alt: string;
}) {
  return (
    <div className='relative size-[72px] shrink-0 overflow-hidden rounded-full border border-border bg-muted'>
      <Image
        src={src}
        alt={alt}
        width={72}
        height={72}
        className='size-full object-contain p-1'
      />
    </div>
  );
}

function OrganizationSettingsSkeleton() {
  return (
    <section className='rounded-xl border border-border bg-card p-6'>
      <div className='flex flex-col gap-6 sm:flex-row sm:items-start'>
        <Skeleton className='size-[72px] rounded-full' />
        <div className='grid min-w-0 flex-1 gap-5 sm:grid-cols-2'>
          <div className='space-y-2'>
            <Skeleton className='h-3 w-24' />
            <Skeleton className='h-4 w-48' />
          </div>
          <div className='space-y-2'>
            <Skeleton className='h-3 w-16' />
            <Skeleton className='h-4 w-40' />
          </div>
          <div className='space-y-2 sm:col-span-2'>
            <Skeleton className='h-3 w-8' />
            <Skeleton className='h-4 w-full max-w-md' />
          </div>
          <div className='space-y-2'>
            <Skeleton className='h-3 w-20' />
            <Skeleton className='h-4 w-36' />
          </div>
        </div>
      </div>
    </section>
  );
}

export function OrganizationSettingsPage() {
  const t = useTranslations('organization');
  const tCommon = useTranslations('common');
  const format = useFormatter();
  const { currentOrg, isLoading, isError, refetch } = useOrganization();

  const copyId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
      toast.success(t('messages.copySuccess'));
    } catch {
      toast.error(t('messages.updateError'));
    }
  };

  return (
    <div className='space-y-6'>
      <OrganizationPageHeader
        title={t('title')}
        description={t('description')}
      />

      {isLoading ? (
        <>
          <p className='sr-only'>{tCommon('loadingOrganization')}</p>
          <OrganizationSettingsSkeleton />
        </>
      ) : isError ? (
        <div className='rounded-xl border border-destructive/30 bg-card p-8 text-center'>
          <p className='text-sm text-muted-foreground'>{t('messages.loadError')}</p>
          <Button
            type='button'
            variant='outline'
            size='sm'
            className='mt-4'
            onClick={() => refetch()}
          >
            {tCommon('retry')}
          </Button>
        </div>
      ) : !currentOrg ? (
        <div className='rounded-xl border border-dashed border-border bg-card p-12 text-center'>
          <Building2 className='mx-auto mb-3 size-10 text-muted-foreground' />
          <p className='text-sm text-muted-foreground'>{t('noOrganization')}</p>
        </div>
      ) : (
        <section className='rounded-xl border border-border bg-card p-6'>
          <div className='flex flex-col gap-6 sm:flex-row sm:items-start'>
            <OrganizationLogo
              src={currentOrg.businessLogo || '/logo.png'}
              alt={formatOrgDisplayName(currentOrg.businessName, t('noName'))}
            />

            <dl className='grid min-w-0 flex-1 gap-5 sm:grid-cols-2'>
              <DetailField label={t('fields.businessName')}>
                <span className='font-semibold text-foreground'>
                  {formatOrgDisplayName(currentOrg.businessName, t('noName'))}
                </span>
              </DetailField>

              <DetailField label={t('fields.businessEmail')}>
                {currentOrg.businessEmail || '—'}
              </DetailField>

              <DetailField
                label={t('fields.organizationId')}
                className='sm:col-span-2'
              >
                <div className='flex flex-wrap items-center gap-2'>
                  <code className='break-all font-mono text-xs text-muted-foreground'>
                    {currentOrg.id}
                  </code>
                  <Button
                    type='button'
                    variant='ghost'
                    size='icon'
                    className='size-7 shrink-0 text-muted-foreground'
                    onClick={() => void copyId(currentOrg.id)}
                    aria-label={t('copyId')}
                  >
                    <Copy className='size-3.5' />
                  </Button>
                </div>
              </DetailField>

              {currentOrg.created_at ? (
                <DetailField label={t('fields.createdAt')}>
                  {format.dateTime(new Date(currentOrg.created_at), {
                    dateStyle: 'medium',
                    timeStyle: 'short'
                  })}
                </DetailField>
              ) : null}
            </dl>
          </div>
        </section>
      )}
    </div>
  );
}
