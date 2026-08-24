'use client';

import { useState } from 'react';
import { ChevronDown, Copy, Check } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import { humanizeSessionGateMessage } from '../../lib/session-gate-message';

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

  const text = result.textPreview ?? '';
  const hasValue = !!result.savedAs;
  const isEmpty = hasValue && !text;
  const canExpand = text.length > COLLAPSED_CHARS;
  const shown =
    expanded || !canExpand ? text : `${text.slice(0, COLLAPSED_CHARS)}…`;

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
        'mt-1 rounded-md border px-2 py-1.5 text-[11px] leading-relaxed',
        result.ok
          ? 'border-emerald-500/30 bg-emerald-50/50 dark:bg-emerald-950/20'
          : 'border-destructive/30 bg-destructive/5'
      )}
    >
      <div className='flex items-start gap-1.5'>
        <div className='min-w-0 flex-1'>
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
              <p className='mt-0.5 whitespace-pre-wrap break-words font-mono text-[11px] text-foreground'>
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
            <p className='text-muted-foreground' title={result.message}>
              {humanizeSessionGateMessage(result.message, tGate) ??
                result.message}
            </p>
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
