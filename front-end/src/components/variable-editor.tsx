'use client';

import { useState, useEffect, useCallback, useRef, KeyboardEvent } from 'react';
import { Plus, Trash2, ChevronDown, ChevronRight, Info } from 'lucide-react';
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
  { name: '${__NOW__}', desc: 'ISO timestamp hiện tại' },
  { name: '${__DATE__}', desc: 'YYYY-MM-DD' },
  { name: '${__TIME__}', desc: 'HH:MM:SS' },
  { name: '${__DEVICE_SERIAL__}', desc: 'Serial thiết bị đang chạy' },
  { name: '${__DEVICE_MODEL__}', desc: 'Model thiết bị' },
  { name: '${__RANDOM_INT_1_100__}', desc: 'Số ngẫu nhiên 1–100' },
  { name: '${__RANDOM_UUID__}', desc: 'UUID v4' },
  { name: '${__STEP_INDEX__}', desc: 'Index bước hiện tại' },
];

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
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
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
          placeholder={tags.length === 0 ? 'Nhập giá trị, Enter để thêm…' : '+'}
        />
      )}
      {tags.length === 0 && disabled && (
        <span className='text-muted-foreground/50'>Danh sách trống</span>
      )}
    </div>
  );
}

// ── Type selector ──────────────────────────────────────────────────────────────

function TypeSelect({
  value,
  onChange,
  disabled,
}: {
  value: VarType;
  onChange: (t: VarType) => void;
  disabled?: boolean;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as VarType)} disabled={disabled}>
      <SelectTrigger size='sm' className='w-[100px] shrink-0 text-xs'>
        <SelectValue />
      </SelectTrigger>
      <SelectContent className='z-[10001]'>
        <SelectItem value='string'>Chuỗi</SelectItem>
        <SelectItem value='number'>Số</SelectItem>
        <SelectItem value='list'>Danh sách</SelectItem>
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
  const [entries, setEntries] = useState<VarEntry[]>(() => toEntries(variables));
  const [builtinsOpen, setBuiltinsOpen] = useState(false);
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

  return (
    <div className='space-y-3'>
      {/* Header row */}
      {entries.length > 0 && (
        <div className='flex gap-2 px-0.5'>
          <span className='w-[130px] text-[10px] font-medium uppercase tracking-wide text-muted-foreground'>Tên biến</span>
          <span className='w-[100px] text-[10px] font-medium uppercase tracking-wide text-muted-foreground'>Loại</span>
          <span className='flex-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground'>Giá trị</span>
          <span className='w-7' />
        </div>
      )}

      {/* Rows */}
      {entries.map((entry, i) => (
        <div key={i} className='flex items-start gap-2'>
          {/* Key */}
          <Input
            value={entry.key}
            onChange={(e) => update(i, { key: e.target.value })}
            placeholder='tên_biến'
            disabled={disabled}
            className='h-8 w-[130px] shrink-0 font-mono text-xs'
          />

          {/* Type */}
          <TypeSelect
            value={entry.type}
            onChange={(t) => update(i, { type: t, strVal: '', listVal: [] })}
            disabled={disabled}
          />

          {/* Value */}
          <div className='flex-1'>
            {entry.type === 'list' ? (
              <ListTagInput
                tags={entry.listVal}
                onChange={(tags) => update(i, { listVal: tags })}
                disabled={disabled}
              />
            ) : (
              <Input
                type={entry.type === 'number' ? 'number' : 'text'}
                value={entry.strVal}
                onChange={(e) => update(i, { strVal: e.target.value })}
                placeholder={entry.type === 'number' ? '0' : entry.key ? `\${${entry.key}}` : 'Giá trị…'}
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
          <p className='font-medium'>Chưa có biến nào.</p>
          <p className='mt-0.5 text-[11px]'>
            Dùng biến trong kịch bản qua cú pháp{' '}
            <code className='rounded bg-muted px-1 font-mono'>{'${tên_biến}'}</code>.
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
        Thêm biến
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
            <span className='font-medium'>Biến hệ thống có sẵn</span>
          </button>
          {builtinsOpen && (
            <div className='grid grid-cols-2 gap-x-4 gap-y-1 border-t px-3 py-2'>
              {BUILTINS.map((b) => (
                <div key={b.name} className='flex flex-col'>
                  <code className='text-[10px] font-mono text-primary'>{b.name}</code>
                  <span className='text-[10px] text-muted-foreground'>{b.desc}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
