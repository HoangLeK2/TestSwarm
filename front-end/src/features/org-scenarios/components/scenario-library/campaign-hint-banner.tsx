'use client';

import { ArrowRight, Rocket } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Link } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';

export function CampaignHintBanner() {
  const t = useTranslations('orgScenariosFeature.list');

  return (
    <div className='flex flex-col gap-2 rounded-lg bg-muted/50 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between'>
      <p className='flex items-start gap-2 text-xs leading-relaxed text-muted-foreground sm:items-center'>
        <Rocket
          size={14}
          className='mt-0.5 shrink-0 text-foreground/70 sm:mt-0'
          aria-hidden
        />
        <span>{t('campaignHintShort')}</span>
      </p>
      <Button variant='secondary' size='sm' className='h-8 shrink-0 gap-1.5' asChild>
        <Link href={ROUTES.CAMPAIGNS.ROOT}>
          {t('campaignHintLink')}
          <ArrowRight size={14} />
        </Link>
      </Button>
    </div>
  );
}
