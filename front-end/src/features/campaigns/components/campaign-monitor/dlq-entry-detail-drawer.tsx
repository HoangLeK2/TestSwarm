'use client';

import { ExternalLink } from 'lucide-react';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { ROUTES } from '@/config/routes';
import type { DlqEntry } from '../../types';
import { dlqDisplayMessage } from './dlq-message';

function formatTs(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

type Props = {
  entry: DlqEntry | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function DlqEntryDetailDrawer({ entry, open, onOpenChange }: Props) {
  const t = useTranslations('campaignsFeature.list');

  if (!entry) return null;

  const message = dlqDisplayMessage(entry, t('monitorDlqNoErrorMessage'));
  const refs = entry.artifact_refs ?? {};

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className='w-full overflow-y-auto sm:max-w-lg'>
        <SheetHeader>
          <SheetTitle>{t('monitorDlqDetailTitle')}</SheetTitle>
        </SheetHeader>
        <div className='mt-4 space-y-4 text-sm'>
          <div className='flex flex-wrap items-center gap-2'>
            <code className='font-semibold'>{entry.device_serial}</code>
            <Badge variant='outline'>{entry.status}</Badge>
          </div>

          <dl className='grid gap-3 text-xs'>
            <div>
              <dt className='text-muted-foreground'>
                {t('monitorDlqDetailExecution')}
              </dt>
              <dd className='mt-0.5 font-mono'>{entry.execution_id}</dd>
            </div>
            {entry.failed_step_id ? (
              <div>
                <dt className='text-muted-foreground'>
                  {t('monitorDlqFailedStep', { step: entry.failed_step_id })}
                </dt>
              </div>
            ) : null}
            <div>
              <dt className='text-muted-foreground'>
                {t('monitorDlqDetailError')}
              </dt>
              <dd className='mt-0.5 whitespace-pre-wrap break-words'>
                {message}
              </dd>
            </div>
            <div>
              <dt className='text-muted-foreground'>
                {t('monitorDlqRetryCount', { count: entry.retry_count })}
              </dt>
            </div>
            <div>
              <dt className='text-muted-foreground'>
                {t('monitorDlqDetailCreated')}
              </dt>
              <dd className='mt-0.5'>{formatTs(entry.created_at)}</dd>
            </div>
            {entry.last_attempt_at ? (
              <div>
                <dt className='text-muted-foreground'>
                  {t('monitorDlqLastAttempt', {
                    time: formatTs(entry.last_attempt_at)
                  })}
                </dt>
              </div>
            ) : null}
            {entry.close_reason ? (
              <div>
                <dt className='text-muted-foreground'>
                  {t('monitorDlqCloseReasonLabel')}
                </dt>
                <dd className='mt-0.5'>{entry.close_reason}</dd>
              </div>
            ) : null}
          </dl>

          {Object.keys(refs).length > 0 ? (
            <div>
              <p className='mb-2 text-xs font-medium text-muted-foreground'>
                {t('monitorDlqDetailArtifacts')}
              </p>
              <ul className='space-y-1'>
                {Object.entries(refs).map(([key, url]) =>
                  url ? (
                    <li key={key}>
                      <a
                        href={url}
                        target='_blank'
                        rel='noreferrer'
                        className='inline-flex items-center gap-1 text-xs text-primary hover:underline'
                      >
                        {key}
                        <ExternalLink size={12} />
                      </a>
                    </li>
                  ) : null
                )}
              </ul>
            </div>
          ) : null}

          <div className='flex flex-wrap gap-2 pt-2'>
            <Link
              href={ROUTES.CONTENT.BY_EXECUTION(entry.execution_id)}
              className='text-xs text-primary hover:underline'
            >
              {t('monitorDlqDetailViewContent')}
            </Link>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
