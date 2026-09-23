'use client';

import { useState } from 'react';
import { format } from 'date-fns';
import type { Locale } from 'date-fns';
import { ChevronDown, Wrench } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';
import type { ScheduleRunOut } from '../services/api';

export function ScheduleRunTechnicalDetails({
  run,
  dateLocale
}: {
  run: ScheduleRunOut;
  dateLocale: Locale;
}) {
  const t = useTranslations('schedulesFeature.list');
  const [open, setOpen] = useState(false);
  const technicalIds = [
    ...(run.execution_id ? [run.execution_id] : []),
    ...run.task_ids,
    ...run.workflow_ids
  ];

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className='rounded-lg border bg-muted/20'>
        <CollapsibleTrigger asChild>
          <Button
            variant='ghost'
            className='h-auto w-full justify-between rounded-lg px-4 py-3 text-left'
          >
            <span className='flex min-w-0 items-center gap-3'>
              <Wrench
                className='size-4 shrink-0 text-muted-foreground'
                aria-hidden
              />
              <span>
                <span className='block text-sm font-semibold'>
                  {t('technicalDetails')}
                </span>
                <span className='mt-0.5 block text-xs font-normal text-muted-foreground'>
                  {t('technicalDetailsDescription')}
                </span>
              </span>
            </span>
            <ChevronDown
              className={cn(
                'size-4 shrink-0 text-muted-foreground transition-transform',
                open && 'rotate-180'
              )}
              aria-hidden
            />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className='border-t px-4 py-4'>
            <dl className='grid gap-3 text-xs sm:grid-cols-2'>
              <div>
                <dt className='text-muted-foreground'>{t('runId')}</dt>
                <dd className='mt-1 break-all font-mono'>{run.id}</dd>
              </div>
              <div>
                <dt className='text-muted-foreground'>{t('catchUpRun')}</dt>
                <dd className='mt-1'>
                  {run.was_catch_up ? t('yes') : t('no')}
                </dd>
              </div>
              {run.finished_at ? (
                <div>
                  <dt className='text-muted-foreground'>
                    {t('runColFinished')}
                  </dt>
                  <dd className='mt-1'>
                    {format(new Date(run.finished_at), 'PPp', {
                      locale: dateLocale
                    })}
                  </dd>
                </div>
              ) : null}
              {run.deferred_until ? (
                <div>
                  <dt className='text-muted-foreground'>
                    {t('deferredUntil')}
                  </dt>
                  <dd className='mt-1'>
                    {format(new Date(run.deferred_until), 'PPp', {
                      locale: dateLocale
                    })}
                  </dd>
                </div>
              ) : null}
            </dl>
            {technicalIds.length ? (
              <div className='mt-4 border-t pt-3'>
                <p className='text-xs text-muted-foreground'>
                  {t('relatedIds')}
                </p>
                <ul className='mt-2 space-y-1'>
                  {technicalIds.map((id) => (
                    <li key={id} className='break-all font-mono text-xs'>
                      {id}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {run.error_code || run.error_message ? (
              <div className='mt-4 border-t pt-3'>
                <p className='text-xs text-muted-foreground'>
                  {t('originalError')}
                </p>
                {run.error_code ? (
                  <p className='mt-2 break-all font-mono text-xs'>
                    {run.error_code}
                  </p>
                ) : null}
                {run.error_message ? (
                  <p className='mt-1 whitespace-pre-wrap break-words font-mono text-xs'>
                    {run.error_message}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
