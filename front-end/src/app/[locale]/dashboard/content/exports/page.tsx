'use client';

import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Heading } from '@/components/ui/heading';
import { ROUTES } from '@/config/routes';
import { ContentExportHistoryPanel } from '@/features/content/components/content-export-panel';

export default function ContentExportsPage() {
  const t = useTranslations('contentFeature.export');

  return (
    <div className='space-y-6 p-4 sm:p-6'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <Heading title={t('pageTitle')} description={t('pageSubtitle')} />
        <Button asChild variant='outline' size='sm' className='gap-1'>
          <Link href={ROUTES.CONTENT.ROOT}>
            <ArrowLeft size={14} />
            {t('backToContent')}
          </Link>
        </Button>
      </div>
      <ContentExportHistoryPanel />
    </div>
  );
}
