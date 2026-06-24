'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { CornerDownLeft, Eraser, Keyboard } from 'lucide-react';
import { useTranslations } from 'next-intl';
import {
  Collapsible,
  CollapsibleContent
} from '@/components/ui/collapsible';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import {
  computeLiveInputDeltas,
  normalizeLiveInputText
} from '../lib/live-input-delta';

type LiveInputCoreProps = {
  serial: string;
  wsSend: (obj: object) => void;
  disabled?: boolean;
};

const LIVE_INPUT_SYNC_MS = 80;

function useLiveInputCore({ serial, wsSend, disabled = false }: LiveInputCoreProps) {
  const [value, setValue] = useState('');
  const prevValueRef = useRef('');
  const composingRef = useRef(false);
  const syncTimerRef = useRef<number | null>(null);
  const pendingSyncRef = useRef<string | null>(null);

  const flushSync = useCallback(
    (nextRaw: string) => {
      const next = normalizeLiveInputText(nextRaw);
      const prev = prevValueRef.current;
      if (prev === next) return;
      if (!next) {
        wsSend({ type: 'input_text', serial, mode: 'live_clear' });
      } else {
        for (const delta of computeLiveInputDeltas(prev, next)) {
          if (delta.kind === 'append') {
            wsSend({
              type: 'input_text',
              serial,
              text: delta.text,
              append: true
            });
          } else if (delta.kind === 'reset_append') {
            wsSend({
              type: 'input_text',
              serial,
              text: delta.text,
              mode: 'live_replace'
            });
          } else if (delta.kind === 'delete') {
            for (let i = 0; i < delta.count; i += 1) {
              wsSend({ type: 'key', serial, key: 'delete' });
            }
          }
        }
      }
      prevValueRef.current = next;
    },
    [serial, wsSend]
  );

  const scheduleSync = useCallback(
    (nextRaw: string) => {
      pendingSyncRef.current = nextRaw;
      if (syncTimerRef.current != null) {
        window.clearTimeout(syncTimerRef.current);
      }
      syncTimerRef.current = window.setTimeout(() => {
        syncTimerRef.current = null;
        const pending = pendingSyncRef.current;
        pendingSyncRef.current = null;
        if (pending == null) return;
        flushSync(pending);
      }, LIVE_INPUT_SYNC_MS);
    },
    [flushSync]
  );

  useEffect(
    () => () => {
      if (syncTimerRef.current != null) {
        window.clearTimeout(syncTimerRef.current);
      }
    },
    []
  );

  const handleCompositionStart = useCallback(() => {
    composingRef.current = true;
  }, []);

  const handleCompositionEnd = useCallback(
    (nextRaw: string) => {
      composingRef.current = false;
      const next = normalizeLiveInputText(nextRaw);
      setValue(next);
      if (syncTimerRef.current != null) {
        window.clearTimeout(syncTimerRef.current);
        syncTimerRef.current = null;
      }
      pendingSyncRef.current = null;
      flushSync(next);
    },
    [flushSync]
  );

  const handleChange = useCallback(
    (nextRaw: string) => {
      if (disabled) return;
      const next = normalizeLiveInputText(nextRaw);
      setValue(next);
      if (composingRef.current) return;
      scheduleSync(next);
    },
    [disabled, scheduleSync]
  );

  const flushPending = useCallback(() => {
    if (syncTimerRef.current != null) {
      window.clearTimeout(syncTimerRef.current);
      syncTimerRef.current = null;
    }
    const pending = pendingSyncRef.current ?? value;
    pendingSyncRef.current = null;
    flushSync(pending);
  }, [flushSync, value]);

  const handleClear = useCallback(() => {
    if (disabled || !value) return;
    if (syncTimerRef.current != null) {
      window.clearTimeout(syncTimerRef.current);
      syncTimerRef.current = null;
    }
    pendingSyncRef.current = null;
    flushSync('');
    setValue('');
  }, [disabled, flushSync, value]);

  const handleEnter = useCallback(() => {
    if (disabled) return;
    flushPending();
    wsSend({ type: 'key', serial, key: 'enter' });
  }, [disabled, flushPending, serial, wsSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (disabled) return;
      if (e.key === 'Enter') {
        e.preventDefault();
        handleEnter();
      }
    },
    [disabled, handleEnter]
  );

  return {
    value,
    handleChange,
    handleClear,
    handleEnter,
    handleKeyDown,
    handleCompositionStart,
    handleCompositionEnd
  };
}

function LiveInputIconButton({
  label,
  hint,
  onClick,
  disabled,
  primary,
  children
}: {
  label: string;
  hint: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type='button'
          aria-label={label}
          disabled={disabled}
          onClick={onClick}
          className={cn(
            'flex size-7 shrink-0 items-center justify-center rounded-full transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 focus-visible:ring-offset-zinc-900',
            disabled
              ? 'cursor-not-allowed text-zinc-600'
              : primary
                ? 'bg-primary text-primary-foreground shadow-sm hover:bg-primary/90'
                : 'text-zinc-400 hover:bg-white/10 hover:text-zinc-100'
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side='top' className='max-w-[200px] text-xs'>
        {hint}
      </TooltipContent>
    </Tooltip>
  );
}

export type DeviceLiveInputBarProps = LiveInputCoreProps & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  className?: string;
};

/** Compact live input bar — matches device control rail styling. */
export function DeviceLiveInputBar({
  serial,
  wsSend,
  disabled = false,
  open,
  onOpenChange,
  className
}: DeviceLiveInputBarProps) {
  const t = useTranslations('devicesControlRecord.liveInput');
  const inputRef = useRef<HTMLInputElement>(null);
  const {
    value,
    handleChange,
    handleClear,
    handleEnter,
    handleKeyDown,
    handleCompositionStart,
    handleCompositionEnd
  } = useLiveInputCore({
    serial,
    wsSend,
    disabled
  });

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(
      () => inputRef.current?.focus({ preventScroll: true }),
      120
    );
    return () => window.clearTimeout(timer);
  }, [open]);

  return (
    <Collapsible
      open={open}
      onOpenChange={onOpenChange}
      className={cn('w-full', className)}
    >
      <CollapsibleContent className='overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down'>
        <div
          className={cn(
            'flex items-center gap-0.5 rounded-2xl bg-zinc-900 p-1',
            'shadow-lg ring-1 ring-black/20'
          )}
        >
          <label htmlFor={`live-input-${serial}`} className='sr-only'>
            {t('label')}
          </label>
          <div className='flex min-w-0 flex-1 items-center gap-1.5 pl-2.5'>
            <Keyboard
              className='size-3.5 shrink-0 text-zinc-500'
              aria-hidden
            />
            <input
              ref={inputRef}
              id={`live-input-${serial}`}
              type='text'
              value={value}
              onChange={(e) => handleChange(e.target.value)}
              onCompositionStart={handleCompositionStart}
              onCompositionEnd={(e) =>
                handleCompositionEnd(e.currentTarget.value)
              }
              onKeyDown={handleKeyDown}
              placeholder={t('placeholder')}
              disabled={disabled}
              title={t('focusHint')}
              className={cn(
                'min-w-0 flex-1 bg-transparent py-1.5 text-xs text-zinc-100',
                'placeholder:text-zinc-500',
                'outline-none disabled:cursor-not-allowed disabled:opacity-50'
              )}
              aria-label={t('label')}
              autoComplete='off'
              spellCheck={false}
              lang='vi'
            />
          </div>
          <div className='flex shrink-0 items-center gap-0.5 pr-0.5'>
            <LiveInputIconButton
              label={t('clear')}
              hint={t('clearHint')}
              onClick={handleClear}
              disabled={disabled || !value}
            >
              <Eraser className='size-3.5' aria-hidden />
            </LiveInputIconButton>
            <LiveInputIconButton
              label={t('send')}
              hint={t('enterHint')}
              onClick={handleEnter}
              disabled={disabled}
              primary
            >
              <CornerDownLeft className='size-3.5' aria-hidden />
            </LiveInputIconButton>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** @deprecated Use DeviceLiveInputBar */
export const DeviceLiveInputPanel = DeviceLiveInputBar;
