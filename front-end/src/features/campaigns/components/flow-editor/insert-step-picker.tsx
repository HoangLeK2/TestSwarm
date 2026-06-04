'use client';

import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { Search } from 'lucide-react';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { createDefaultStep, type FlowStep } from '../scenario-steps/types';
import { findInsertMenuItem, type InsertMenuGroupKey } from './constants';
import { useCampaignFlowI18n } from './flow-i18n';
import { StepIcon } from './step-icon';

const RECENT_STORAGE_KEY = 'device-farm.flow-insert-recent';
const MAX_RECENT = 3;
/** Fixed list viewport — matches legacy insert menu (~22rem). */
const LIST_PANEL_CLASS = 'h-[min(22rem,55vh)]';

type ListedItem = {
  type: string;
  label: string;
  description: string;
  groupLabel?: string;
};

function loadRecentTypes(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(RECENT_STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed)
      ? parsed.filter((v): v is string => typeof v === 'string')
      : [];
  } catch {
    return [];
  }
}

function pushRecentType(type: string) {
  if (typeof window === 'undefined') return;
  const next = [type, ...loadRecentTypes().filter((t) => t !== type)].slice(
    0,
    MAX_RECENT
  );
  localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify(next));
}

function StepPickerRow({
  item,
  onSelect
}: {
  item: ListedItem;
  onSelect: () => void;
}) {
  return (
    <button
      type='button'
      className={cn(
        'flex w-full items-start gap-3 rounded-lg border border-transparent px-2 py-2 text-left',
        'transition-colors hover:border-border/60 hover:bg-muted/50',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
      )}
      onClick={onSelect}
    >
      <span
        className={cn(
          'flex size-9 shrink-0 items-center justify-center rounded-lg',
          'bg-muted/80 ring-1 ring-border/50'
        )}
      >
        <StepIcon type={item.type} size={16} />
      </span>
      <span className='min-w-0 flex-1'>
        <span className='block text-sm font-medium leading-snug text-foreground'>
          {item.label}
        </span>
        {item.description ? (
          <span className='mt-0.5 block text-[11px] leading-relaxed text-muted-foreground'>
            {item.description}
          </span>
        ) : null}
        {item.groupLabel ? (
          <span className='mt-1 inline-block text-[10px] text-muted-foreground/80'>
            {item.groupLabel}
          </span>
        ) : null}
      </span>
    </button>
  );
}

export function InsertStepPicker({
  trigger,
  onInsert,
  contentSide = 'right',
  contentAlign = 'start',
  sideOffset = 10
}: {
  trigger: ReactNode;
  onInsert: (step: FlowStep) => void;
  contentSide?: 'top' | 'right' | 'bottom' | 'left';
  contentAlign?: 'start' | 'center' | 'end';
  sideOffset?: number;
}) {
  const { getInsertMenu, tInsert } = useCampaignFlowI18n();
  const insertMenu = getInsertMenu();
  const defaultCategory =
    insertMenu.find((g) => g.groupKey === 'actions')?.groupKey ??
    insertMenu[0]?.groupKey ??
    'actions';

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<InsertMenuGroupKey>(defaultCategory);
  const [recentVersion, setRecentVersion] = useState(0);

  const recentItems = useMemo(() => {
    void recentVersion;
    return loadRecentTypes()
      .map((type) => findInsertMenuItem(insertMenu, type))
      .filter((item): item is NonNullable<typeof item> => item != null)
      .map((item) => ({
        type: item.type,
        label: item.label,
        description: item.description
      }));
  }, [insertMenu, recentVersion]);

  const listedItems = useMemo((): ListedItem[] => {
    const q = query.trim().toLowerCase();
    if (q) {
      const out: ListedItem[] = [];
      for (const group of insertMenu) {
        for (const item of group.items) {
          if (
            item.label.toLowerCase().includes(q) ||
            item.description.toLowerCase().includes(q) ||
            item.type.toLowerCase().includes(q)
          ) {
            out.push({
              ...item,
              groupLabel: group.group
            });
          }
        }
      }
      return out;
    }
    const group = insertMenu.find((g) => g.groupKey === category);
    return group?.items ?? [];
  }, [insertMenu, query, category]);

  const recentTypeSet = useMemo(
    () => new Set(recentItems.map((i) => i.type)),
    [recentItems]
  );

  const visibleItems = useMemo(() => {
    if (query.trim() || recentItems.length === 0) return listedItems;
    return listedItems.filter((item) => !recentTypeSet.has(item.type));
  }, [listedItems, query, recentItems.length, recentTypeSet]);

  const handleSelect = useCallback(
    (type: string) => {
      pushRecentType(type);
      setRecentVersion((v) => v + 1);
      onInsert(createDefaultStep(type));
      setOpen(false);
      setQuery('');
    },
    [onInsert]
  );

  const tabs = insertMenu.map((g) => ({
    id: g.groupKey,
    label: tInsert(`tabs.${g.groupKey}` as 'tabs.actions')
  }));

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery('');
      }}
    >
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        side={contentSide}
        align={contentAlign}
        sideOffset={sideOffset}
        className='w-[min(20rem,calc(100vw-2rem))] overflow-hidden p-0'
      >
        <div className='border-b border-border/60 bg-muted/30 px-3 pb-2.5 pt-3'>
          <p className='text-sm font-semibold text-foreground'>
            {tInsert('pickerTitle')}
          </p>
          <p className='mt-0.5 text-[11px] text-muted-foreground'>
            {tInsert('pickerSubtitle')}
          </p>
          <div className='relative mt-2.5'>
            <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={tInsert('searchPlaceholder')}
              className='h-9 pl-8 text-xs'
            />
          </div>
          <div
            className={cn(
              'mt-2 flex min-h-7 flex-wrap gap-1.5',
              query.trim() && 'pointer-events-none invisible'
            )}
            aria-hidden={!!query.trim()}
          >
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type='button'
                onClick={() => setCategory(tab.id)}
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors',
                  category === tab.id
                    ? 'border-primary/40 bg-primary/10 text-foreground'
                    : 'border-border/60 bg-background text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div
          className={cn(
            'flex flex-col overflow-hidden px-2 py-2',
            LIST_PANEL_CLASS
          )}
        >
          <div className='min-h-0 flex-1 overflow-y-auto'>
            {!query.trim() && recentItems.length > 0 ? (
              <div className='mb-2'>
                <p className='px-1 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground'>
                  {tInsert('recentTitle')}
                </p>
                <div className='space-y-0.5'>
                  {recentItems.map((item) => (
                    <StepPickerRow
                      key={`recent-${item.type}`}
                      item={item}
                      onSelect={() => handleSelect(item.type)}
                    />
                  ))}
                </div>
              </div>
            ) : null}

            {!query.trim() ? (
              <p className='px-1 pb-1 text-[10px] text-muted-foreground'>
                {insertMenu.find((g) => g.groupKey === category)?.description}
              </p>
            ) : null}

            <div className='space-y-0.5'>
              {visibleItems.map((item) => (
                <StepPickerRow
                  key={item.type}
                  item={item}
                  onSelect={() => handleSelect(item.type)}
                />
              ))}
            </div>

            {visibleItems.length === 0 &&
            (query.trim() ? true : recentItems.length === 0) ? (
              <div className='flex min-h-[12rem] items-center justify-center py-8'>
                <p className='px-2 text-center text-xs text-muted-foreground'>
                  {tInsert('noResults')}
                </p>
              </div>
            ) : null}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
