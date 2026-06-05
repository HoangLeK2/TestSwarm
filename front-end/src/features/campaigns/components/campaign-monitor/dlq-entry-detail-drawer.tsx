'use client';

import { useCallback, useMemo } from 'react';
import {
  AlertCircle,
  ChevronDown,
  Copy,
  ExternalLink,
  Hash,
  ImageIcon,
  Smartphone
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { toast } from 'sonner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { ROUTES } from '@/config/routes';
import { Z_CAMPAIGN_MONITOR_NESTED } from '@/lib/z-index';
import { cn } from '@/lib/utils';
import { useCampaignExecutions } from '../../hooks/use-campaigns';
import type { DlqEntry, ExecutionOut } from '../../types';
import { dlqDisplayMessage } from './dlq-message';
import {
  executionRunTypeLabel,
  executionScenarioLabel,
  executionStatusLabel,
  findExecutionForDlq,
  formatTs
} from './dlq-run-summary';
import { dlqStatusLabel, dlqStatusVariant } from './dlq-status';

function RunSummaryValue({
  execution,
  t
}: {
  execution: ExecutionOut | undefined;
  t: (key: string) => string;
}) {
  if (!execution) {
    return (
      <p className='text-sm text-muted-foreground'>
        {t('monitorDlqDetailRunPending')}
      </p>
    );
  }

  const scenario = executionScenarioLabel(execution);

  return (
    <div className='space-y-1.5'>
      <Badge variant='outline' className='text-xs font-normal'>
        {executionStatusLabel(execution.status, t)}
      </Badge>
      {scenario ? (
        <p className='text-sm'>
          <span className='text-muted-foreground'>
            {t('monitorDlqDetailRunScenario')}:{' '}
          </span>
          {scenario}
        </p>
      ) : null}
      <p className='text-sm text-muted-foreground'>
        {t('monitorDlqDetailRunStarted')}:{' '}
        <span className='text-foreground'>
          {formatTs(execution.started_at ?? execution.created_at)}
        </span>
      </p>
      {execution.finished_at ? (
        <p className='text-sm text-muted-foreground'>
          {t('monitorDlqDetailRunFinished')}:{' '}
          <span className='text-foreground'>
            {formatTs(execution.finished_at)}
          </span>
        </p>
      ) : null}
      {execution.run_type ? (
        <p className='text-sm text-muted-foreground'>
          {t('monitorDlqDetailRunType')}:{' '}
          <span className='text-foreground'>
            {executionRunTypeLabel(execution.run_type, t)}
          </span>
        </p>
      ) : null}
    </div>
  );
}

const ARTIFACT_LABEL_KEYS: Record<string, string> = {
  url: 'monitorDlqArtifactUrl',
  screenshot_post: 'monitorDlqArtifactScreenshotPost',
  screenshot_pre: 'monitorDlqArtifactScreenshotPre'
};

function DetailRow({
  label,
  value,
  mono = false,
  copyValue
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  copyValue?: string;
}) {
  const t = useTranslations('campaignsFeature.list');

  const handleCopy = useCallback(async () => {
    if (!copyValue) return;
    try {
      await navigator.clipboard.writeText(copyValue);
      toast.success(t('monitorDlqCopied'));
    } catch {
      toast.error(t('monitorDlqCopy'));
    }
  }, [copyValue, t]);

  return (
    <div className='flex items-start gap-3 px-4 py-3'>
      <span className='min-w-[7.5rem] shrink-0 text-xs text-muted-foreground'>
        {label}
      </span>
      <span
        className={cn(
          'min-w-0 flex-1 text-sm leading-snug text-foreground',
          mono && 'break-all font-mono text-xs'
        )}
      >
        {value}
      </span>
      {copyValue ? (
        <Button
          type='button'
          variant='ghost'
          size='icon'
          className='size-8 shrink-0'
          onClick={() => void handleCopy()}
          aria-label={t('monitorDlqCopy')}
        >
          <Copy className='size-3.5' />
        </Button>
      ) : null}
    </div>
  );
}

type Props = {
  entry: DlqEntry | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  campaignId?: string;
};

export function DlqEntryDetailDrawer({
  entry,
  open,
  onOpenChange,
  campaignId
}: Props) {
  const t = useTranslations('campaignsFeature.list');
  const { data: executions = [] } = useCampaignExecutions(
    campaignId ?? '',
    open && Boolean(campaignId)
  );

  const execution = useMemo(
    () =>
      entry ? findExecutionForDlq(executions, entry.execution_id) : undefined,
    [executions, entry]
  );
  const replayExecution = useMemo(
    () =>
      entry?.replayed_to_execution_id
        ? findExecutionForDlq(executions, entry.replayed_to_execution_id)
        : undefined,
    [executions, entry]
  );
  const runSubtitle = entry
    ? execution
      ? executionStatusLabel(execution.status, t)
      : dlqStatusLabel(entry.status, t)
    : '';

  if (!entry) return null;

  const fallback = t('monitorDlqNoErrorMessage');
  const message = dlqDisplayMessage(entry, fallback);
  const hasMessage = message !== fallback;
  const errorRaw = entry.error?.trim() || '';
  const reasonRaw = entry.failure_reason?.trim() || '';
  const showReason = Boolean(reasonRaw && reasonRaw !== errorRaw);
  const showError = Boolean(errorRaw);
  const refs = Object.entries(entry.artifact_refs ?? {}).filter(([, url]) =>
    Boolean(url)
  );
  const previewUrl =
    refs.find(
      ([k]) => k === 'screenshot_post' || k === 'screenshot_pre'
    )?.[1] ??
    refs.find(([k]) => k === 'url')?.[1] ??
    null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        zIndex={Z_CAMPAIGN_MONITOR_NESTED}
        side='right'
        className='flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-md'
      >
        <SheetHeader className='shrink-0 space-y-2 border-b px-6 py-5 text-left'>
          <div className='flex flex-wrap items-center gap-2'>
            <Badge variant={dlqStatusVariant(entry.status)}>
              {dlqStatusLabel(entry.status, t)}
            </Badge>
            {entry.retry_count > 0 ? (
              <Badge variant='outline' className='tabular-nums'>
                {t('monitorDlqRetryCount', { count: entry.retry_count })}
              </Badge>
            ) : null}
          </div>
          <SheetTitle className='text-lg'>
            {t('monitorDlqDetailTitle')}
          </SheetTitle>
          <SheetDescription className='text-sm'>
            {t('monitorDlqDetailSubtitle', {
              device: entry.device_serial,
              runShort: runSubtitle
            })}
          </SheetDescription>
        </SheetHeader>

        <ScrollArea className='min-h-0 flex-1'>
          <div className='space-y-4 px-6 py-4'>
            <section className='space-y-2'>
              <h3 className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
                {t('monitorDlqDetailSectionError')}
              </h3>
              {hasMessage ? (
                <Alert variant='destructive'>
                  <AlertCircle className='size-4' />
                  <AlertTitle className='text-sm'>
                    {entry.failed_step_id
                      ? t('monitorDlqFailedStep', {
                          step: entry.failed_step_id
                        })
                      : t('monitorDlqDetailError')}
                  </AlertTitle>
                  <AlertDescription className='space-y-2'>
                    {showReason ? (
                      <div>
                        <p className='text-xs font-medium text-destructive/90'>
                          {t('monitorDlqDetailFailureReason')}
                        </p>
                        <p className='whitespace-pre-wrap break-words text-sm'>
                          {reasonRaw}
                        </p>
                      </div>
                    ) : null}
                    {showError ? (
                      <div>
                        {showReason ? (
                          <p className='text-xs font-medium text-destructive/90'>
                            {t('monitorDlqDetailErrorDetail')}
                          </p>
                        ) : null}
                        <p className='whitespace-pre-wrap break-words text-sm'>
                          {errorRaw}
                        </p>
                      </div>
                    ) : null}
                    {!showReason && !showError && hasMessage ? (
                      <p className='whitespace-pre-wrap break-words text-sm'>
                        {message}
                      </p>
                    ) : null}
                  </AlertDescription>
                </Alert>
              ) : (
                <Alert>
                  <AlertCircle className='size-4' />
                  <AlertTitle className='text-sm'>
                    {t('monitorDlqDetailNoErrorTitle')}
                  </AlertTitle>
                  <AlertDescription className='text-sm leading-relaxed'>
                    {t('monitorDlqDetailNoErrorBody')}
                  </AlertDescription>
                </Alert>
              )}
            </section>

            <Card className='gap-0 py-0 shadow-none'>
              <CardHeader className='border-b px-4 py-3'>
                <CardTitle className='flex items-center gap-2 text-sm'>
                  <Smartphone className='size-4 text-muted-foreground' />
                  {t('monitorDlqDetailSectionRun')}
                </CardTitle>
              </CardHeader>
              <CardContent className='p-0'>
                <DetailRow
                  label={t('monitorDlqDetailDevice')}
                  value={entry.device_serial}
                  mono
                  copyValue={entry.device_serial}
                />
                <Separator />
                <DetailRow
                  label={t('monitorDlqDetailRunStatus')}
                  value={<RunSummaryValue execution={execution} t={t} />}
                />
                {entry.failed_step_id ? (
                  <>
                    <Separator />
                    <DetailRow
                      label={t('monitorDlqDetailFailedStepLabel')}
                      value={
                        <Badge
                          variant='secondary'
                          className='font-mono text-xs'
                        >
                          {entry.failed_step_id}
                        </Badge>
                      }
                      copyValue={entry.failed_step_id}
                    />
                  </>
                ) : null}
                <Separator />
                <DetailRow
                  label={t('monitorDlqDetailRetries')}
                  value={String(entry.retry_count)}
                />
                <Separator />
                <DetailRow
                  label={t('monitorDlqDetailCreated')}
                  value={formatTs(entry.created_at)}
                />
                {entry.failed_at ? (
                  <>
                    <Separator />
                    <DetailRow
                      label={t('monitorDlqDetailFailedAt')}
                      value={formatTs(entry.failed_at)}
                    />
                  </>
                ) : null}
                {entry.last_attempt_at ? (
                  <>
                    <Separator />
                    <DetailRow
                      label={t('monitorDlqDetailLastAttempt')}
                      value={formatTs(entry.last_attempt_at)}
                    />
                  </>
                ) : null}
                {entry.replayed_to_execution_id ? (
                  <>
                    <Separator />
                    <DetailRow
                      label={t('monitorDlqDetailReplayRun')}
                      value={
                        <RunSummaryValue execution={replayExecution} t={t} />
                      }
                    />
                  </>
                ) : null}
                {entry.close_reason ? (
                  <>
                    <Separator />
                    <DetailRow
                      label={t('monitorDlqCloseReasonLabel')}
                      value={entry.close_reason}
                    />
                  </>
                ) : null}
                {entry.closed_at ? (
                  <>
                    <Separator />
                    <DetailRow
                      label={t('monitorDlqDetailClosedAt')}
                      value={formatTs(entry.closed_at)}
                    />
                  </>
                ) : null}
                <Separator />
                <Collapsible className='group px-4 py-2'>
                  <CollapsibleTrigger className='flex w-full items-center justify-between gap-2 rounded-md py-2 text-left text-xs font-medium text-muted-foreground hover:text-foreground'>
                    <span className='flex items-center gap-2'>
                      <Hash className='size-3.5' />
                      {t('monitorDlqDetailTechnicalIds')}
                    </span>
                    <ChevronDown className='size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180' />
                  </CollapsibleTrigger>
                  <CollapsibleContent className='space-y-0 pb-2'>
                    <p className='mb-2 text-[11px] leading-snug text-muted-foreground'>
                      {t('monitorDlqDetailTechnicalIdsHint')}
                    </p>
                    <DetailRow
                      label={t('monitorDlqDetailRun')}
                      value={entry.execution_id}
                      mono
                      copyValue={entry.execution_id}
                    />
                    <DetailRow
                      label={t('monitorDlqDetailDlqId')}
                      value={entry.id}
                      mono
                      copyValue={entry.id}
                    />
                    {entry.replayed_to_execution_id ? (
                      <DetailRow
                        label={t('monitorDlqDetailReplayRun')}
                        value={entry.replayed_to_execution_id}
                        mono
                        copyValue={entry.replayed_to_execution_id}
                      />
                    ) : null}
                  </CollapsibleContent>
                </Collapsible>
              </CardContent>
            </Card>

            {refs.length > 0 ? (
              <Card className='gap-0 py-0 shadow-none'>
                <CardHeader className='border-b px-4 py-3'>
                  <CardTitle className='flex items-center gap-2 text-sm'>
                    <ImageIcon className='size-4 text-muted-foreground' />
                    {t('monitorDlqDetailArtifacts')}
                  </CardTitle>
                </CardHeader>
                <CardContent className='flex flex-col gap-2 p-4'>
                  {refs.map(([key, url]) => (
                    <Button
                      key={key}
                      variant='outline'
                      size='sm'
                      className='h-auto justify-start gap-2 px-3 py-2 text-left'
                      asChild
                    >
                      <a href={url} target='_blank' rel='noreferrer'>
                        <span className='min-w-0 flex-1 truncate text-xs font-medium'>
                          {t(
                            ARTIFACT_LABEL_KEYS[key] ?? 'monitorDlqArtifactUrl'
                          )}
                        </span>
                        <ExternalLink className='size-3.5 shrink-0 opacity-60' />
                      </a>
                    </Button>
                  ))}
                </CardContent>
              </Card>
            ) : null}
          </div>
        </ScrollArea>

        <SheetFooter className='shrink-0 flex-col gap-2 border-t bg-muted/20 px-6 py-4 sm:flex-col'>
          <Button asChild className='w-full'>
            <Link href={ROUTES.CONTENT.BY_EXECUTION(entry.execution_id)}>
              {t('monitorDlqDetailViewContent')}
            </Link>
          </Button>
          {previewUrl ? (
            <Button variant='outline' className='w-full' asChild>
              <a href={previewUrl} target='_blank' rel='noreferrer'>
                <ImageIcon className='mr-2 size-4' />
                {t('monitorDlqViewScreenshot')}
              </a>
            </Button>
          ) : null}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
