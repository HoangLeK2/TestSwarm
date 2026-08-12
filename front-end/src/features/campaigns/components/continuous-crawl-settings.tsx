'use client';

import { useId } from 'react';
import { useTranslations } from 'next-intl';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  readContinuousCrawlSettings,
  updateContinuousCrawlSettings
} from '../lib/continuous-crawl-monitor';

export function ContinuousCrawlSettings({
  variables,
  onChange,
  disabled = false
}: {
  variables: Record<string, unknown>;
  onChange: (variables: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const t = useTranslations('campaignsFeature.continuousCrawlSettings');
  const id = useId();
  const settings = readContinuousCrawlSettings(variables);
  const update = (next: Partial<typeof settings>) =>
    onChange(
      updateContinuousCrawlSettings(variables, { ...settings, ...next })
    );

  return (
    <div className='space-y-3'>
      <div className='flex items-center justify-between gap-4'>
        <div className='min-w-0'>
          <Label htmlFor={`${id}-enabled`}>{t('enabledLabel')}</Label>
          <p className='mt-1 text-[11px] text-muted-foreground'>
            {t('enabledHint')}
          </p>
        </div>
        <Switch
          id={`${id}-enabled`}
          checked={settings.enabled}
          onCheckedChange={(enabled) => update({ enabled })}
          disabled={disabled}
        />
      </div>
    </div>
  );
}
