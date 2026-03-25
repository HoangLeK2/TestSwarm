'use client';

import * as Sentry from '@sentry/nextjs';
import Image from 'next/image';
import { useEffect, useMemo, useState } from 'react';
import { getCapturedLogs } from '@/lib/client-log-buffer';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import { ChevronDown, RefreshCcw } from 'lucide-react';
import { useTranslations } from 'next-intl';

export default function Error({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations('errors.client');
  const [_, setEventId] = useState<string | undefined>(undefined);

  useEffect(() => {
    const id = Sentry.captureException(error) as unknown as string | undefined;
    setEventId(id);
  }, [error]);

  const logs = useMemo(() => getCapturedLogs(), []);

  return (
    <div className='flex min-h-[60vh] w-full flex-col items-center justify-center px-6 py-12'>
      <Image
        src='/logo.png'
        width={48}
        height={48}
        alt='Logo'
        className='mb-6'
      />
      <h1 className='text-2xl font-semibold tracking-tight'>{t('heading')}</h1>
      <p className='mt-2 text-muted-foreground'>{t('description')}</p>
      <div className='mt-5 flex items-center gap-2'>
        <Button onClick={() => reset()} className=''>
          <RefreshCcw className='h-4 w-4' />
          {t('retry')}
        </Button>
        {/* <Button
          variant='outline'
          onClick={() => {
            try {
              // Sentry's dialog types may not be exported in @sentry/nextjs
              // eslint-disable-next-line @typescript-eslint/ban-ts-comment
              // @ts-ignore
              const showReportDialog =
                (Sentry as any).showReportDialog || Sentry.showReportDialog;
              if (typeof showReportDialog === 'function') {
                if (eventId) showReportDialog({ eventId });
                else showReportDialog();
              } else {
                throw new globalThis.Error('Report dialog not available');
              }
            } catch (_err) {
              window.alert(t('reportDialogFail'));
            }
          }}
        >
          {t('report')}
        </Button> */}
      </div>

      <div className='mt-6 w-full max-w-3xl'>
        <Collapsible defaultOpen>
          <CollapsibleTrigger className='w-full'>
            <div className='flex items-center justify-between rounded-md border bg-card px-4 py-2 text-left'>
              <span className='font-medium'>{t('details')}</span>
              <ChevronDown className='h-4 w-4 transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180' />
            </div>
          </CollapsibleTrigger>
          <CollapsibleContent className='mt-2'>
            <pre className='overflow-auto whitespace-pre-wrap rounded-md bg-zinc-950 p-4 text-xs text-zinc-200'>
              {`${error.name}: ${error.message}\n${error.stack ?? ''}\n${error.digest ? `digest: ${error.digest}` : ''}`}
            </pre>
          </CollapsibleContent>
        </Collapsible>

        <Collapsible className='mt-4'>
          <CollapsibleTrigger className='w-full'>
            <div className='flex items-center justify-between rounded-md border bg-card px-4 py-2 text-left'>
              <span className='font-medium'>{t('clientLogs')}</span>
              <ChevronDown className='h-4 w-4 transition-transform duration-200 group-data-[state=open]/collapsible:rotate-180' />
            </div>
          </CollapsibleTrigger>
          <CollapsibleContent className='mt-2'>
            <div className='max-h-96 overflow-auto rounded-md border'>
              <table className='w-full text-xs'>
                <thead className='bg-muted/50'>
                  <tr>
                    <th className='p-2 text-left'>Time</th>
                    <th className='p-2 text-left'>Level</th>
                    <th className='p-2 text-left'>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {logs
                    .slice()
                    .reverse()
                    .map((l, i) => (
                      <tr key={i} className='border-t'>
                        <td className='whitespace-nowrap p-2'>
                          {new Date(l.timestamp).toLocaleTimeString()}
                        </td>
                        <td className='p-2 font-semibold uppercase'>
                          <span
                            className={
                              l.level === 'error'
                                ? 'text-red-600'
                                : l.level === 'warn'
                                  ? 'text-amber-600'
                                  : l.level === 'info'
                                    ? 'text-sky-600'
                                    : 'text-zinc-700'
                            }
                          >
                            {l.level}
                          </span>
                        </td>
                        <td className='p-2'>
                          <pre className='m-0 whitespace-pre-wrap'>
                            {l.message}
                          </pre>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  );
}
