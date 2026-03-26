'use client';

import { CrawlJobsPanel } from '@/features/crawl-jobs/components/crawl-jobs-panel';
import { useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';

export default function CrawlJobsPage() {
  const t = useTranslations('crawlJobs');
  const searchParams = useSearchParams();
  const campaignId = searchParams.get('campaign_id') || undefined;

  return (
    <div className='container max-w-6xl py-8'>
      <header className='mb-6'>
        <h1 className='text-2xl font-bold tracking-tight'>{t('title')}</h1>
        <p className='text-sm text-muted-foreground'>{t('description')}</p>
      </header>
      <CrawlJobsPanel campaignId={campaignId} />
    </div>
  );
}
