'use client';

import { useState, useEffect, useCallback, useRef, KeyboardEvent } from 'react';
import {
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  CircleHelp,
  Braces
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';
import { normalizeScenarioVariables } from '@/lib/scenario-variables';

type VarType = 'string' | 'number' | 'list';

type VarEntry = {
  key: string;
  type: VarType;
  strVal: string;
  listVal: string[];
};

const BUILTINS = [
  { name: '${__NOW__}', descKey: 'builtins.now', group: 'system' },
  { name: '${__DATE__}', descKey: 'builtins.date', group: 'system' },
  { name: '${__TIME__}', descKey: 'builtins.time', group: 'system' },
  {
    name: '${__DEVICE_SERIAL__}',
    descKey: 'builtins.deviceSerial',
    group: 'system'
  },
  {
    name: '${__DEVICE_MODEL__}',
    descKey: 'builtins.deviceModel',
    group: 'system'
  },
  {
    name: '${__RANDOM_INT_1_100__}',
    descKey: 'builtins.randomInt',
    group: 'system'
  },
  {
    name: '${__RANDOM_UUID__}',
    descKey: 'builtins.randomUuid',
    group: 'system'
  },
  { name: '${__STEP_INDEX__}', descKey: 'builtins.stepIndex', group: 'system' },
  {
    name: '${GROUP_NAME}',
    descKey: 'builtins.groupName',
    group: 'sourcePool'
  },
  {
    name: '${GROUP_URL}',
    descKey: 'builtins.groupUrl',
    group: 'sourcePool'
  },
  {
    name: '${GROUP_SEARCH_QUERY}',
    descKey: 'builtins.groupSearchQuery',
    group: 'sourcePool'
  },
  {
    name: '${GROUP_SELECTOR_BY}',
    descKey: 'builtins.groupSelectorBy',
    group: 'sourcePool'
  },
  {
    name: '${GROUP_SELECTOR_VALUE}',
    descKey: 'builtins.groupSelectorValue',
    group: 'sourcePool'
  },
  {
    name: '${GROUP_FALLBACK_SELECTOR_BY}',
    descKey: 'builtins.groupFallbackSelectorBy',
    group: 'sourcePool'
  },
  {
    name: '${GROUP_FALLBACK_SELECTOR_VALUE}',
    descKey: 'builtins.groupFallbackSelectorValue',
    group: 'sourcePool'
  },
  {
    name: '${PAGE_KEYWORDS}',
    descKey: 'builtins.pageKeywords',
    group: 'pageDiscovery'
  },
  {
    name: '${PAGE_KEYWORD_COUNT}',
    descKey: 'builtins.pageKeywordCount',
    group: 'pageDiscovery'
  },
  {
    name: '${MAX_ITEMS_PER_KEYWORD}',
    descKey: 'builtins.maxItemsPerKeyword',
    group: 'pageDiscovery'
  },
  {
    name: '${MAX_PAGES}',
    descKey: 'builtins.maxPages',
    group: 'pageDiscovery'
  },
  {
    name: '${__ACCOUNT_ID__}',
    descKey: 'builtins.accountId',
    group: 'account'
  },
  {
    name: '${__ACCOUNT_USERNAME__}',
    descKey: 'builtins.accountUsername',
    group: 'account'
  },
  {
    name: '${__ACCOUNT_PASSWORD__}',
    descKey: 'builtins.accountPassword',
    group: 'account'
  },
  {
    name: '${__ACCOUNT_DISPLAY_NAME__}',
    descKey: 'builtins.accountDisplayName',
    group: 'account'
  },
  {
    name: '${__ACCOUNT_PLATFORM__}',
    descKey: 'builtins.accountPlatform',
    group: 'account'
  }
] as const;

const SYSTEM_BUILTINS = BUILTINS.filter((b) => b.group === 'system');
const ACCOUNT_BUILTINS = BUILTINS.filter((b) => b.group === 'account');
const SOURCE_POOL_BUILTINS = BUILTINS.filter((b) => b.group === 'sourcePool');
const PAGE_DISCOVERY_BUILTINS = BUILTINS.filter(
  (b) => b.group === 'pageDiscovery'
);

function toEntries(vars: Record<string, any>): VarEntry[] {
  return Object.entries(normalizeScenarioVariables(vars)).map(
    ([key, value]) => {
      if (Array.isArray(value)) {
        return { key, type: 'list', strVal: '', listVal: value.map(String) };
      }
      if (typeof value === 'number') {
        return { key, type: 'number', strVal: String(value), listVal: [] };
      }
      return {
        key,
        type: 'string',
        strVal: typeof value === 'string' ? value : JSON.stringify(value),
        listVal: []
      };
    }
  );
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
  if (Array.isArray(result.PAGE_KEYWORDS)) {
    const keywords = result.PAGE_KEYWORDS.map((item: unknown) =>
      String(item).trim()
    ).filter(Boolean);
    result.PAGE_KEYWORDS = keywords;
    result.PAGE_KEYWORD_COUNT = keywords.length;
  }
  return result;
}

function syncDerivedEntryValues(entries: VarEntry[]): VarEntry[] {
  const keywordEntry = entries.find(
    (entry) => entry.key.trim() === 'PAGE_KEYWORDS' && entry.type === 'list'
  );
  if (!keywordEntry) return entries;
  const count = keywordEntry.listVal.map((item) => item.trim()).filter(Boolean)
    .length;
  let changed = false;
  const next = entries.map((entry) => {
    if (entry.key.trim() !== 'PAGE_KEYWORD_COUNT') return entry;
    if (entry.type === 'number' && entry.strVal === String(count)) return entry;
    changed = true;
    return { ...entry, type: 'number' as const, strVal: String(count), listVal: [] };
  });
  return changed ? next : entries;
}

function countDefined(entries: VarEntry[]) {
  return entries.filter((e) => e.key.trim()).length;
}

function ListTagInput({
  tags,
  onChange,
  disabled,
  t
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
    <div
      className={cn(
        'flex min-h-9 flex-wrap items-center gap-1 rounded-md border bg-background px-2 py-1.5 text-xs focus-within:border-ring focus-within:ring-1 focus-within:ring-ring/50',
        disabled && 'cursor-not-allowed opacity-50'
      )}
    >
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

function TypeSelect({
  value,
  onChange,
  disabled,
  t
}: {
  value: VarType;
  onChange: (t: VarType) => void;
  disabled?: boolean;
  t: (key: string) => string;
}) {
  return (
    <Select
      value={value}
      onValueChange={(v) => onChange(v as VarType)}
      disabled={disabled}
    >
      <SelectTrigger size='sm' className='h-8 w-[96px] shrink-0 text-xs'>
        <SelectValue />
      </SelectTrigger>
      <SelectContent className='z-[calc(var(--z-floating)+100)]'>
        <SelectItem value='string'>{t('types.string')}</SelectItem>
        <SelectItem value='number'>{t('types.number')}</SelectItem>
        <SelectItem value='list'>{t('types.list')}</SelectItem>
      </SelectContent>
    </Select>
  );
}

function VarCard({
  entry,
  index,
  disabled,
  lockKey,
  allowRemove,
  copiedKey,
  onUpdate,
  onRemove,
  onCopyToken,
  getValuePlaceholder,
  t
}: {
  entry: VarEntry;
  index: number;
  disabled?: boolean;
  lockKey?: boolean;
  allowRemove?: boolean;
  copiedKey: string | null;
  onUpdate: (index: number, patch: Partial<VarEntry>) => void;
  onRemove: (index: number) => void;
  onCopyToken: (key: string) => void;
  getValuePlaceholder: (entry: VarEntry) => string;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  const token = entry.key.trim() ? `\${${entry.key}}` : '';
  const copied = copiedKey === entry.key;

  return (
    <div className='rounded-lg border border-border/60 bg-muted/15 p-3 transition-colors hover:border-border'>
      <div className='flex items-start gap-2'>
        <Input
          value={entry.key}
          onChange={(e) => onUpdate(index, { key: e.target.value })}
          placeholder={t('keyPlaceholder')}
          disabled={disabled || lockKey}
          readOnly={lockKey}
          title={entry.key}
          className={cn(
            'h-8 min-w-0 flex-1 font-mono text-xs',
            lockKey && 'bg-muted/40'
          )}
        />
        <TypeSelect
          value={entry.type}
          onChange={(type) =>
            onUpdate(index, { type, strVal: '', listVal: [] })
          }
          disabled={disabled || lockKey}
          t={t}
        />
        {allowRemove !== false ? (
          <Button
            type='button'
            size='icon'
            variant='ghost'
            className='size-8 shrink-0 text-muted-foreground hover:text-destructive'
            disabled={disabled}
            onClick={() => onRemove(index)}
            title={t('removeVariable')}
          >
            <Trash2 size={14} />
          </Button>
        ) : null}
      </div>

      <div className='mt-2'>
        {entry.type === 'list' ? (
          <ListTagInput
            tags={entry.listVal}
            onChange={(tags) => onUpdate(index, { listVal: tags })}
            disabled={disabled}
            t={t}
          />
        ) : (
          <Input
            type={entry.type === 'number' ? 'number' : 'text'}
            value={entry.strVal}
            onChange={(e) => onUpdate(index, { strVal: e.target.value })}
            placeholder={getValuePlaceholder(entry)}
            disabled={disabled}
            title={entry.strVal}
            className='h-8 w-full text-xs'
          />
        )}
      </div>

      {token ? (
        <div className='mt-2.5 flex flex-wrap items-center gap-2 border-t border-border/40 pt-2.5'>
          <code className='rounded-md bg-primary/5 px-2 py-0.5 font-mono text-[11px] text-primary'>
            {token}
          </code>
          <Button
            type='button'
            size='sm'
            variant='secondary'
            className='h-7 gap-1 text-[11px]'
            disabled={disabled}
            onClick={() => onCopyToken(entry.key)}
          >
            {copied ? (
              <Check size={12} className='text-green-600' />
            ) : (
              <Copy size={12} />
            )}
            {copied ? t('copied') : t('copy')}
          </Button>
          <span className='text-[11px] text-muted-foreground'>
            {t('useInSteps')}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function BuiltinGroup({
  title,
  items,
  copiedKey,
  onCopy,
  t
}: {
  title: string;
  items: (typeof BUILTINS)[number][];
  copiedKey: string | null;
  onCopy: (name: string) => void;
  t: (key: string) => string;
}) {
  return (
    <Collapsible>
      <CollapsibleTrigger className='flex w-full items-center gap-2 rounded-md px-1 py-1.5 text-left text-xs font-medium text-foreground hover:bg-muted/50 [&[data-state=open]>svg:first-child]:rotate-90'>
        <ChevronRight size={14} className='shrink-0 transition-transform' />
        <span className='flex-1'>{title}</span>
        <Badge variant='secondary' className='h-5 text-[10px] font-normal'>
          {items.length}
        </Badge>
      </CollapsibleTrigger>
      <CollapsibleContent className='pt-1'>
        <div className='grid gap-1 sm:grid-cols-2'>
          {items.map((b) => (
            <button
              key={b.name}
              type='button'
              onClick={() => onCopy(b.name)}
              className='flex flex-col items-start rounded-md px-2 py-1.5 text-left hover:bg-muted/60 focus:bg-muted/60 focus:outline-none'
              title={`Copy ${b.name}`}
            >
              <span className='flex items-center gap-1.5'>
                {copiedKey === b.name ? (
                  <Check size={11} className='text-green-600' />
                ) : (
                  <Copy size={11} className='text-muted-foreground' />
                )}
                <code className='font-mono text-[10px] text-primary'>
                  {b.name}
                </code>
              </span>
              <span className='pl-5 text-[10px] leading-snug text-muted-foreground'>
                {t(b.descKey)}
              </span>
            </button>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export type VariableEntry = VarEntry;

interface Props {
  variables: Record<string, any>;
  onChange: (variables: Record<string, any>) => void;
  disabled?: boolean;
  /** Allow creating new variable keys (scenario editor). Off for campaign create. */
  allowAdd?: boolean;
  /** Lock variable names/types — only values are editable. */
  lockKeys?: boolean;
  /** Allow removing rows from the list. */
  allowRemove?: boolean;
  /** Show built-in variables reference panel */
  showBuiltins?: boolean;
  /** Toolbar: add, guide, builtins toggle */
  showToolbar?: boolean;
  /** Hint below the variable list */
  showFooterTip?: boolean;
}

export function VariableEditor({
  variables,
  onChange,
  disabled,
  allowAdd = true,
  lockKeys = false,
  allowRemove = true,
  showBuiltins = true,
  showToolbar = true,
  showFooterTip = true
}: Props) {
  const t = useTranslations('components.variableEditor');
  const [entries, setEntries] = useState<VarEntry[]>(() =>
    toEntries(variables)
  );
  const [builtinsOpen, setBuiltinsOpen] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const internalChange = useRef(false);

  useEffect(() => {
    if (internalChange.current) {
      internalChange.current = false;
      return;
    }
    setEntries((prev) => {
      const fromParent = toEntries(variables);
      const drafts = prev.filter((e) => !e.key.trim());
      if (drafts.length === 0) return fromParent;
      return [...fromParent, ...drafts];
    });
  }, [variables]);

  const commit = useCallback(
    (newEntries: VarEntry[]) => {
      const nextEntries = syncDerivedEntryValues(newEntries);
      setEntries(nextEntries);
      internalChange.current = true;
      onChange(toRecord(nextEntries));
    },
    [onChange]
  );

  const update = useCallback(
    (index: number, patch: Partial<VarEntry>) => {
      commit(entries.map((e, i) => (i === index ? { ...e, ...patch } : e)));
    },
    [entries, commit]
  );

  const add = useCallback(() => {
    setEntries((prev) => [
      ...prev,
      { key: '', type: 'string', strVal: '', listVal: [] }
    ]);
  }, []);

  const remove = useCallback(
    (index: number) => commit(entries.filter((_, i) => i !== index)),
    [entries, commit]
  );

  const copyToClipboard = useCallback(async (text: string, id: string) => {
    const markCopied = () => {
      setCopiedKey(id);
      window.setTimeout(
        () => setCopiedKey((current) => (current === id ? null : id)),
        1200
      );
    };
    try {
      await navigator.clipboard.writeText(text);
      markCopied();
    } catch {
      try {
        const el = document.createElement('textarea');
        el.value = text;
        el.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
        document.body.appendChild(el);
        el.focus();
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        markCopied();
      } catch {
        // ignore
      }
    }
  }, []);

  const copyToken = useCallback(
    (key: string) => {
      if (!key.trim()) return;
      void copyToClipboard(`\${${key}}`, key);
    },
    [copyToClipboard]
  );

  const copyBuiltin = useCallback(
    (name: string) => {
      void copyToClipboard(name, name);
    },
    [copyToClipboard]
  );

  const getValuePlaceholder = useCallback(
    (entry: VarEntry) => {
      if (entry.type === 'number') {
        return t('valuePlaceholderNumber');
      }
      if (entry.type === 'string') {
        return entry.key
          ? t('valuePlaceholderStringWithRef', { key: entry.key })
          : t('valuePlaceholderString');
      }
      return '';
    },
    [t]
  );

  const definedCount = countDefined(entries);

  return (
    <div className='space-y-3'>
      {showToolbar ? (
        <div className='flex flex-wrap items-center gap-2'>
          {allowAdd ? (
            <Button
              type='button'
              size='sm'
              disabled={disabled}
              onClick={add}
              className='h-8 gap-1 text-xs'
            >
              <Plus size={14} />
              {t('addVariable')}
            </Button>
          ) : null}
          {showBuiltins ? (
            <Popover open={builtinsOpen} onOpenChange={setBuiltinsOpen}>
              <PopoverTrigger asChild>
                <Button
                  type='button'
                  size='sm'
                  variant='outline'
                  disabled={disabled}
                  className={cn(
                    'h-8 text-xs',
                    builtinsOpen && 'border-primary/30 bg-primary/[0.04]'
                  )}
                >
                  {builtinsOpen ? (
                    <ChevronDown size={14} className='mr-1' />
                  ) : (
                    <ChevronRight size={14} className='mr-1' />
                  )}
                  {t('builtinsTitle')}
                </Button>
              </PopoverTrigger>
              <PopoverContent
                className='z-[calc(var(--z-floating)+100)] w-[min(100vw-2rem,28rem)] space-y-2 p-3'
                align='start'
              >
                <p className='text-xs font-semibold text-foreground'>
                  {t('builtinsReferenceTitle')}
                </p>
                <BuiltinGroup
                  title={t('builtinGroups.system')}
                  items={SYSTEM_BUILTINS}
                  copiedKey={copiedKey}
                  onCopy={copyBuiltin}
                  t={t}
                />
                <BuiltinGroup
                  title={t('builtinGroups.account')}
                  items={ACCOUNT_BUILTINS}
                  copiedKey={copiedKey}
                  onCopy={copyBuiltin}
                  t={t}
                />
                <p className='text-[10px] text-muted-foreground'>
                  {t('systemAccountHint')}
                </p>
                <p className='pt-2 text-xs font-semibold text-foreground'>
                  {t('sourcePoolVariablesTitle')}
                </p>
                <BuiltinGroup
                  title={t('sourcePoolVariablesSubtitle')}
                  items={SOURCE_POOL_BUILTINS}
                  copiedKey={copiedKey}
                  onCopy={copyBuiltin}
                  t={t}
                />
                <p className='text-[10px] text-muted-foreground'>
                  {t('sourcePoolVariablesHint')}
                </p>
                <BuiltinGroup
                  title={t('pageDiscoveryVariablesTitle')}
                  items={PAGE_DISCOVERY_BUILTINS}
                  copiedKey={copiedKey}
                  onCopy={copyBuiltin}
                  t={t}
                />
                <p className='text-[10px] text-muted-foreground'>
                  {t('pageDiscoveryVariablesHint')}
                </p>
              </PopoverContent>
            </Popover>
          ) : null}
          <Popover>
            <PopoverTrigger asChild>
              <Button
                type='button'
                size='sm'
                variant='ghost'
                className='h-8 gap-1 text-xs text-muted-foreground'
              >
                <CircleHelp size={14} />
                {t('quickGuide.title')}
              </Button>
            </PopoverTrigger>
            <PopoverContent
              className='z-[calc(var(--z-floating)+1)] w-80 space-y-2 p-3 text-xs'
              align='start'
            >
              <p className='font-medium text-foreground'>
                {t('quickGuide.title')}
              </p>
              <p className='text-muted-foreground'>{t('quickGuide.step1')}</p>
              <p className='text-muted-foreground'>{t('quickGuide.step2')}</p>
              <p className='text-muted-foreground'>
                {t('quickGuide.step3Prefix')}{' '}
                <code className='rounded bg-muted px-1 font-mono'>
                  {'${ten_bien}'}
                </code>
                .
              </p>
            </PopoverContent>
          </Popover>
          {definedCount > 0 ? (
            <Badge variant='secondary' className='ml-auto h-6 text-[11px]'>
              {t('variableCount', { count: definedCount })}
            </Badge>
          ) : null}
        </div>
      ) : null}

      {entries.length === 0 ? (
        <div className='flex flex-col items-center gap-3 rounded-lg border border-dashed border-border/80 bg-muted/10 px-4 py-8 text-center'>
          <div className='flex size-10 items-center justify-center rounded-full bg-muted/60'>
            <Braces size={18} className='text-muted-foreground' />
          </div>
          <div className='space-y-1'>
            <p className='text-sm font-medium text-foreground'>
              {allowAdd ? t('emptyTitle') : t('emptyFromScenarioTitle')}
            </p>
            <p className='text-[11px] text-muted-foreground'>
              {allowAdd ? (
                <>
                  {t('emptyHintPrefix')}{' '}
                  <code className='rounded bg-muted px-1 font-mono'>
                    {'${ten_bien}'}
                  </code>
                  .
                </>
              ) : (
                t('emptyFromScenarioHint')
              )}
            </p>
          </div>
          {allowAdd ? (
            <Button
              type='button'
              size='sm'
              disabled={disabled}
              onClick={add}
              className='h-8 gap-1 text-xs'
            >
              <Plus size={14} />
              {t('emptyCreateFirst')}
            </Button>
          ) : null}
        </div>
      ) : (
        <div className='space-y-2'>
          {entries.map((entry, i) => (
            <VarCard
              key={i}
              entry={entry}
              index={i}
              disabled={disabled}
              lockKey={lockKeys}
              allowRemove={allowRemove}
              copiedKey={copiedKey}
              onUpdate={update}
              onRemove={remove}
              onCopyToken={copyToken}
              getValuePlaceholder={getValuePlaceholder}
              t={t}
            />
          ))}
        </div>
      )}

      {showFooterTip ? (
        <p className='rounded-md bg-muted/40 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground'>
          {t('footerTipLead')}{' '}
          <code className='rounded bg-muted/80 px-1 py-0.5 font-mono text-[11px] text-foreground'>
            {'${'}
          </code>{' '}
          {t('footerTipTrail')}
        </p>
      ) : null}
    </div>
  );
}
