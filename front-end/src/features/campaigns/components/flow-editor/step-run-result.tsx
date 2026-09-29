'use client';

import { useState } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  Code2,
  Copy
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import { humanizeSessionGateMessage } from '../../lib/session-gate-message';
import { humanizeStepRunMessage } from './step-run-message';

/** What a step wrote, as reported by the preview stream's `step_done` event. */
export type StepRunResult = {
  ok: boolean;
  message?: string;
  /** Variable the step filled, when it produced one. */
  savedAs?: string;
  /** Bounded preview of the value — the full value stays in the runtime. */
  textPreview?: string;
  textLength?: number;
  textTruncated?: boolean;
  boxCount?: number;
};

type Props = {
  result: StepRunResult;
  /** Rendered next to the value — lets the author chain the result forward. */
  action?: React.ReactNode;
};

const COLLAPSED_CHARS = 120;

/**
 * Outcome strip under a step card after a test run.
 *
 * A successful run used to show only a green tick, so an author had no way to
 * tell whether OCR read the right thing — or anything at all.
 */
export function StepRunResultStrip({ result, action }: Props) {
  const t = useTranslations('campaignsFeature.stepEditor.runResult');
  const tGate = useTranslations('executionMessages');
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);

  const text = result.textPreview ?? '';
  const hasValue = !!result.savedAs;
  const isEmpty = hasValue && !text;
  const canExpand = text.length > COLLAPSED_CHARS;
  const shown =
    expanded || !canExpand ? text : `${text.slice(0, COLLAPSED_CHARS)}…`;
  const friendlyMessage =
    humanizeSessionGateMessage(result.message, tGate) ??
    humanizeStepRunMessage(result.message, t);
  const fallbackMessage = result.ok
    ? t('completeFallback')
    : t('failedFallback');
  const primaryMessage = friendlyMessage ?? fallbackMessage;
  const hasTechnicalMessage =
    Boolean(result.message) && result.message !== primaryMessage;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard is best-effort; the text stays selectable either way.
    }
  };

  return (
    <div
      className={cn(
        'mt-1 rounded-md border px-2.5 py-2 text-[11px] leading-relaxed',
        result.ok
          ? 'border-emerald-500/25 bg-emerald-50/45 dark:bg-emerald-950/20'
          : 'border-destructive/30 bg-destructive/5'
      )}
    >
      <div className='flex items-start gap-2'>
        <span
          className={cn(
            'mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-md bg-background ring-1',
            result.ok
              ? 'text-emerald-700 ring-emerald-200 dark:text-emerald-300 dark:ring-emerald-900'
              : 'text-destructive ring-destructive/20'
          )}
        >
          {result.ok ? (
            <CheckCircle2 className='size-3.5' aria-hidden />
          ) : (
            <AlertCircle className='size-3.5' aria-hidden />
          )}
        </span>
        <div className='min-w-0 flex-1'>
          <div className='flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5'>
            <span className='font-medium text-foreground'>
              {hasValue
                ? t('savedTitle')
                : result.ok
                  ? t('okTitle')
                  : t('errorTitle')}
            </span>
            {hasValue && (
              <span className='text-muted-foreground'>
                {t('savedTo', { variable: result.savedAs ?? '' })}
              </span>
            )}
          </div>

          {hasValue && (
            <div className='flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5'>
              <code className='rounded bg-background/70 px-1 font-mono text-[10px] text-foreground'>
                ${'{'}
                {result.savedAs}
                {'}'}
              </code>
              <span className='text-muted-foreground'>
                {isEmpty
                  ? t('empty')
                  : t('charCount', { count: result.textLength ?? text.length })}
                {result.boxCount != null && !isEmpty
                  ? ` · ${t('boxCount', { count: result.boxCount })}`
                  : ''}
              </span>
            </div>
          )}

          {text ? (
            <>
              <p className='mt-1 whitespace-pre-wrap break-words rounded border border-border/60 bg-background/75 px-2 py-1 font-mono text-[11px] text-foreground'>
                {shown}
              </p>
              {/* The tail never left the runtime, so expanding cannot reveal it
                  — say so rather than let a clipped read look like a short one. */}
              {result.textTruncated && expanded && (
                <p className='mt-0.5 text-[10px] text-muted-foreground'>
                  {t('previewTruncated', {
                    shown: text.length,
                    total: result.textLength ?? text.length
                  })}
                </p>
              )}
            </>
          ) : (
            <p className='mt-0.5 text-muted-foreground' title={result.message}>
              {primaryMessage}
            </p>
          )}

          {hasTechnicalMessage && (
            <div className='mt-1.5'>
              <button
                type='button'
                className='inline-flex h-6 items-center gap-1 rounded-md border border-border bg-background px-2 text-[10px] font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
                onClick={() => setShowTechnical((value) => !value)}
                aria-expanded={showTechnical}
              >
                <Code2 className='size-3' aria-hidden />
                {showTechnical ? t('hideTechnical') : t('showTechnical')}
              </button>
              {showTechnical && (
                <pre className='mt-1 max-h-24 overflow-auto rounded-md border border-border/70 bg-background/80 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-muted-foreground'>
                  {result.message}
                </pre>
              )}
            </div>
          )}
        </div>

        {text && (
          <div className='flex shrink-0 items-center gap-0.5'>
            {canExpand && (
              <button
                type='button'
                onClick={() => setExpanded((v) => !v)}
                className='rounded p-0.5 text-muted-foreground hover:bg-background hover:text-foreground'
                aria-label={expanded ? t('collapse') : t('expand')}
              >
                <ChevronDown
                  className={cn(
                    'size-3.5 transition-transform',
                    expanded && 'rotate-180'
                  )}
                />
              </button>
            )}
            <button
              type='button'
              onClick={copy}
              className='rounded p-0.5 text-muted-foreground hover:bg-background hover:text-foreground'
              aria-label={t('copy')}
            >
              {copied ? (
                <Check className='size-3.5 text-emerald-600' />
              ) : (
                <Copy className='size-3.5' />
              )}
            </button>
          </div>
        )}
      </div>

      {action && <div className='mt-1.5'>{action}</div>}
    </div>
  );
}
