'use client';

import { useCallback } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export type VariableEntry = { key: string; value: string };

interface Props {
  variables: Record<string, any>;
  onChange: (variables: Record<string, any>) => void;
  placeholder?: { key?: string; value?: string };
  disabled?: boolean;
}

function toEntries(vars: Record<string, any>): VariableEntry[] {
  return Object.entries(vars).map(([key, value]) => ({
    key,
    value: typeof value === 'string' ? value : JSON.stringify(value)
  }));
}

function toRecord(entries: VariableEntry[]): Record<string, any> {
  const result: Record<string, any> = {};
  for (const { key, value } of entries) {
    if (!key.trim()) continue;
    try {
      result[key] = JSON.parse(value);
    } catch {
      result[key] = value;
    }
  }
  return result;
}

export function VariableEditor({
  variables,
  onChange,
  placeholder,
  disabled
}: Props) {
  const entries = toEntries(variables);

  const update = useCallback(
    (index: number, field: 'key' | 'value', val: string) => {
      const next = [...toEntries(variables)];
      next[index] = { ...next[index], [field]: val };
      onChange(toRecord(next));
    },
    [variables, onChange]
  );

  const add = useCallback(() => {
    const next = [...toEntries(variables), { key: '', value: '' }];
    onChange(toRecord(next));
  }, [variables, onChange]);

  const remove = useCallback(
    (index: number) => {
      const next = toEntries(variables).filter((_, i) => i !== index);
      onChange(toRecord(next));
    },
    [variables, onChange]
  );

  return (
    <div className='space-y-2'>
      {entries.length === 0 && (
        <p className='text-xs text-muted-foreground'>
          No variables defined
        </p>
      )}
      {entries.map((entry, i) => (
        <div key={i} className='flex items-center gap-2'>
          <Input
            value={entry.key}
            onChange={(e) => update(i, 'key', e.target.value)}
            placeholder={placeholder?.key ?? 'Variable name'}
            disabled={disabled}
            className='h-8 flex-1 font-mono text-xs'
          />
          <Input
            value={entry.value}
            onChange={(e) => update(i, 'value', e.target.value)}
            placeholder={placeholder?.value ?? 'Value or ${__BUILTIN__}'}
            disabled={disabled}
            className='h-8 flex-1 text-xs'
          />
          <Button
            type='button'
            size='icon'
            variant='ghost'
            className='size-7 shrink-0 text-destructive'
            disabled={disabled}
            onClick={() => remove(i)}
          >
            <Trash2 size={12} />
          </Button>
        </div>
      ))}
      <Button
        type='button'
        size='sm'
        variant='outline'
        disabled={disabled}
        onClick={add}
        className='text-xs'
      >
        <Plus size={12} className='mr-1' />
        Add variable
      </Button>
    </div>
  );
}
