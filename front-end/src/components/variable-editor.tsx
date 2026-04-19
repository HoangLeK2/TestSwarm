'use client';

import { useState, useEffect, useCallback, useRef, KeyboardEvent } from 'react';
import { Plus, Trash2, ChevronDown, ChevronRight, Info, Copy, Check } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';


type VarType = 'string' | 'number' | 'list';

type VarEntry = {
  key: string;
  type: VarType;
  strVal: string;   // for string / number
  listVal: string[]; // for list
};


const BUILTINS = [
  { name: '${__NOW__}', descKey: 'builtins.now', group: 'system' },
  { name: '${__DATE__}', descKey: 'builtins.date', group: 'system' },
  { name: '${__TIME__}', descKey: 'builtins.time', group: 'system' },
  { name: '${__DEVICE_SERIAL__}', descKey: 'builtins.deviceSerial', group: 'system' },
  { name: '${__DEVICE_MODEL__}', descKey: 'builtins.deviceModel', group: 'system' },
  { name: '${__RANDOM_INT_1_100__}', descKey: 'builtins.randomInt', group: 'system' },
  { name: '${__RANDOM_UUID__}', descKey: 'builtins.randomUuid', group: 'system' },
  { name: '${__STEP_INDEX__}', descKey: 'builtins.stepIndex', group: 'system' },
  { name: '${__ACCOUNT_ID__}', descKey: 'builtins.accountId', group: 'account' },
  { name: '${__ACCOUNT_USERNAME__}', descKey: 'builtins.accountUsername', group: 'account' },
  { name: '${__ACCOUNT_PASSWORD__}', descKey: 'builtins.accountPassword', group: 'account' },
  { name: '${__ACCOUNT_DISPLAY_NAME__}', descKey: 'builtins.accountDisplayName', group: 'account' },
  { name: '${__ACCOUNT_PLATFORM__}', descKey: 'builtins.accountPlatform', group: 'account' },
] as const;

function toEntries(vars: Record<string, any>): VarEntry[] {
  return Object.entries(vars).map(([key, value]) => {
    if (Array.isArray(value)) {
      return { key, type: 'list', strVal: '', listVal: value.map(String) };
    }
    if (typeof value === 'number') {
      return { key, type: 'number', strVal: String(value), listVal: [] };
    }
    return { key, type: 'string', strVal: typeof value === 'string' ? value : JSON.stringify(value), listVal: [] };
  });
}

function toRecord(entries: VarEntry[]): Record<string, any> {
  const result: Record<string, any> = {};
  for (const e of entries) {
    if (!e.key.trim()) continue;
    if (e.type === 'list') {
      result[e.key] = e.listVal.filter(Boolean);
    } else if (e.type === 'number') {
      const n = parseFloat(e.strVal);
      result[e.key] = isNaN(n) ? e.strVal : n;
    } else {
      result[e.key] = e.strVal;
    }
  }
  return result;
}

// ── List tag input ─────────────────────────────────────────────────────────────

function ListTagInput({
  tags,
  onChange,
  disabled,
  t,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
  t: (key: string) => string;
}) {
  const [draft, setDraft] = useState('');

  const addTag = () => {
    const trimmed = draft.trim();
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed]);
    }
    setDraft('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag();
    } else if (e.key === 'Backspace' && !draft && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  };

  return (
    <div className={cn(
      'flex min-h-8 flex-wrap items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs focus-within:border-ring focus-within:ring-1 focus-within:ring-ring/50',
      disabled && 'opacity-50 cursor-not-allowed',
    )}>
      {tags.map((tag, i) => (
        <Badge
          key={i}
          variant='secondary'
          className='h-5 gap-1 rounded px-1.5 text-[10px] font-normal'
        >
          {tag}
          {!disabled && (
            <button
              type='button'
              className='ml-0.5 opacity-60 hover:opacity-100'
              onClick={() => onChange(tags.filter((_, j) => j !== i))}
            >
              ×
            </button>
          )}
        </Badge>
      ))}
      {!disabled && (
        <input
          className='min-w-[80px] flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground/50'
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={addTag}
          placeholder={tags.length === 0 ? t('listInputPlaceholder') : '+'}
        />
      )}
      {tags.length === 0 && disabled && (
        <span className='text-muted-foreground/50'>{t('listEmpty')}</span>
      )}
    </div>
  );
}

// ── Type selector ──────────────────────────────────────────────────────────────

function TypeSelect({
  value,
  onChange,
  disabled,
  t,
}: {
  value: VarType;
  onChange: (t: VarType) => void;
  disabled?: boolean;
  t: (key: string) => string;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as VarType)} disabled={disabled}>
      <SelectTrigger size='sm' className='w-[100px] shrink-0 text-xs'>
        <SelectValue />
      </SelectTrigger>
      <SelectContent className='z-[10001]'>
        <SelectItem value='string'>{t('types.string')}</SelectItem>
        <SelectItem value='number'>{t('types.number')}</SelectItem>
        <SelectItem value='list'>{t('types.list')}</SelectItem>
      </SelectContent>
    </Select>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export type VariableEntry = VarEntry; // re-export for external use if needed

interface Props {
  variables: Record<string, any>;
  onChange: (variables: Record<string, any>) => void;
  disabled?: boolean;
  /** Show built-in variables reference panel */
  showBuiltins?: boolean;
}

export function VariableEditor({ variables, onChange, disabled, showBuiltins = true }: Props) {
  const t = useTranslations('components.variableEditor');
  const [entries, setEntries] = useState<VarEntry[]>(() => toEntries(variables));
  const [builtinsOpen, setBuiltinsOpen] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const internalChange = useRef(false);

  // Sync from parent only for external resets (not our own onChange)
  useEffect(() => {
    if (internalChange.current) {
      internalChange.current = false;
      return;
    }
    setEntries(toEntries(variables));
  }, [variables]);

  const commit = useCallback(
    (newEntries: VarEntry[]) => {
      setEntries(newEntries);
      internalChange.current = true;
      onChange(toRecord(newEntries));
    },
    [onChange],
  );

  const update = useCallback(
    (index: number, patch: Partial<VarEntry>) => {
      commit(entries.map((e, i) => (i === index ? { ...e, ...patch } : e)));
    },
    [entries, commit],
  );

  const add = useCallback(() => {
    commit([...entries, { key: '', type: 'string', strVal: '', listVal: [] }]);
  }, [entries, commit]);

  const remove = useCallback(
    (index: number) => commit(entries.filter((_, i) => i !== index)),
    [entries, commit],
  );

  const copyToken = useCallback(async (key: string) => {
    if (!key.trim()) return;
    const token = `\${${key}}`;
    const markCopied = () => {
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey((current) => (current === key ? null : current)), 1200);
    };
    try {
      await navigator.clipboard.writeText(token);
      markCopied();
    } catch {
      // Fallback for contexts without Clipboard API (mirrors use-control-record.ts::copyJson).
      try {
        const el = document.createElement('textarea');
        el.value = token;
        el.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
        document.body.appendChild(el);
        el.focus();
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        markCopied();
      } catch {
        // Ignore clipboard failures to keep editor interactions simple.
      }
    }
  }, []);

  const copyBuiltin = useCallback(async (name: string) => {
    const markCopied = () => {
      setCopiedKey(name);
      window.setTimeout(() => setCopiedKey((current) => (current === name ? null : current)), 1200);
    };
    try {
      await navigator.clipboard.writeText(name);
      markCopied();
    } catch {
      try {
        const el = document.createElement('textarea');
        el.value = name;
        el.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
        document.body.appendChild(el);
        el.focus();
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        markCopied();
      } catch {
        // swallow
      }
    }
  }, []);

  const getValuePlaceholder = useCallback((entry: VarEntry) => {
    if (entry.type === 'number') {
      return t('valuePlaceholderNumber');
    }
    if (entry.type === 'string') {
      return entry.key
        ? t('valuePlaceholderStringWithRef', { key: entry.key })
        : t('valuePlaceholderString');
    }
    return '';
  }, [t]);

  return (
    <div className='space-y-3'>
      <div className='rounded-md border bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground'>
        <p className='font-medium text-foreground'>{t('quickGuide.title')}</p>
        <p className='mt-1'>{t('quickGuide.step1')}</p>
        <p>{t('quickGuide.step2')}</p>
        <p>
          {t('quickGuide.step3Prefix')}{' '}
          <code className='rounded bg-muted px-1 font-mono'>{'${ten_bien}'}</code>.
        </p>
      </div>

      {/* Header row */}
      {entries.length > 0 && (
        <div className='flex gap-2 px-0.5'>
          <span className='w-[130px] text-[10px] font-medium uppercase tracking-wide text-muted-foreground'>{t('columns.variableName')}</span>
          <span className='w-[100px] text-[10px] font-medium uppercase tracking-wide text-muted-foreground'>{t('columns.type')}</span>
          <span className='flex-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground'>{t('columns.value')}</span>
          <span className='w-7' />
        </div>
      )}

      {/* Rows */}
      {entries.map((entry, i) => (
        <div key={i} className='flex items-start gap-2'>
          {/* Key */}
          <div className='w-[130px] shrink-0 space-y-1'>
            <Input
              value={entry.key}
              onChange={(e) => update(i, { key: e.target.value })}
              placeholder={t('keyPlaceholder')}
              disabled={disabled}
              className='h-8 font-mono text-xs'
            />
            {entry.key.trim() && (
              <button
                type='button'
                className='flex items-center gap-1 text-[10px] text-primary hover:underline'
                onClick={() => copyToken(entry.key)}
              >
                {copiedKey === entry.key ? <Check size={10} /> : <Copy size={10} />}
                <code className='font-mono'>{`\${${entry.key}}`}</code>
              </button>
            )}
          </div>

          {/* Type */}
          <TypeSelect
            value={entry.type}
            onChange={(t) => update(i, { type: t, strVal: '', listVal: [] })}
            disabled={disabled}
            t={t}
          />

          {/* Value */}
          <div className='flex-1'>
            {entry.type === 'list' ? (
              <ListTagInput
                tags={entry.listVal}
                onChange={(tags) => update(i, { listVal: tags })}
                disabled={disabled}
                t={t}
              />
            ) : (
              <Input
                type={entry.type === 'number' ? 'number' : 'text'}
                value={entry.strVal}
                onChange={(e) => update(i, { strVal: e.target.value })}
                placeholder={getValuePlaceholder(entry)}
                disabled={disabled}
                className='h-8 text-xs'
              />
            )}
          </div>

          {/* Delete */}
          <Button
            type='button'
            size='icon'
            variant='ghost'
            className='mt-0.5 size-7 shrink-0 text-muted-foreground hover:text-destructive'
            disabled={disabled}
            onClick={() => remove(i)}
          >
            <Trash2 size={12} />
          </Button>
        </div>
      ))}

      {entries.length === 0 && (
        <div className='rounded-md border border-dashed px-3 py-3 text-xs text-muted-foreground'>
          <p className='font-medium'>{t('emptyTitle')}</p>
          <p className='mt-0.5 text-[11px]'>
            {t('emptyHintPrefix')}{' '}
            <code className='rounded bg-muted px-1 font-mono'>{'${ten_bien}'}</code>.
          </p>
        </div>
      )}

      {/* Add button */}
      <Button
        type='button'
        size='sm'
        variant='outline'
        disabled={disabled}
        onClick={add}
        className='h-7 text-xs'
      >
        <Plus size={12} className='mr-1' />
        {t('addVariable')}
      </Button>

      {/* Built-in variables reference */}
      {showBuiltins && (
        <div className='rounded-md border bg-muted/30'>
          <button
            type='button'
            className='flex w-full items-center gap-1.5 px-3 py-2 text-left text-[11px] text-muted-foreground hover:text-foreground'
            onClick={() => setBuiltinsOpen((v) => !v)}
          >
            {builtinsOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            <Info size={11} />
            <span className='font-medium'>{t('builtinsTitle')}</span>
          </button>
          {builtinsOpen && (
            <div className='space-y-2 border-t px-3 py-2'>
              <div className='grid grid-cols-2 gap-x-4 gap-y-1'>
                {BUILTINS.map((b) => (
                  <button
                    key={b.name}
                    type='button'
                    onClick={() => copyBuiltin(b.name)}
                    className='flex flex-col items-start rounded px-1 py-0.5 text-left hover:bg-muted/60 focus:bg-muted/60 focus:outline-none'
                    title={`Copy ${b.name}`}
                  >
                    <span className='flex items-center gap-1'>
                      {copiedKey === b.name ? (
                        <Check size={10} className='text-green-600' />
                      ) : (
                        <Copy size={10} className='text-muted-foreground' />
                      )}
                      <code className='text-[10px] font-mono text-primary'>{b.name}</code>
                    </span>
                    <span className='pl-3.5 text-[10px] text-muted-foreground'>{t(b.descKey)}</span>
                  </button>
                ))}
              </div>
              <p className='text-[10px] text-muted-foreground'>{t('systemAccountHint')}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
