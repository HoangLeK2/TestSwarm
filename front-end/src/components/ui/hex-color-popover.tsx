'use client';

import { HexColorPicker } from 'react-colorful';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';

const FALLBACK = '#6366f1';

/** Normalize to #rrggbb for HexColorPicker + display */
export function sanitizeHex(v: string): string {
  const raw = (v || '').trim();
  if (!raw) return FALLBACK;
  const s = raw.startsWith('#') ? raw : `#${raw}`;
  if (/^#[0-9a-fA-F]{8}$/.test(s)) return s.slice(0, 7).toLowerCase();
  if (!/^#[0-9a-fA-F]{3}$|^#[0-9a-fA-F]{6}$/.test(s)) return FALLBACK;
  if (s.length === 4) {
    const r = s[1]!;
    const g = s[2]!;
    const b = s[3]!;
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  return s.slice(0, 7).toLowerCase();
}

type Props = {
  value: string;
  onChange: (hex: string) => void;
  disabled?: boolean;
  className?: string;
  'aria-label'?: string;
};

/** Radix Popover + react-colorful — avoids native color UI clipping inside dialogs. */
export function HexColorPopover({
  value,
  onChange,
  disabled,
  className,
  'aria-label': ariaLabel
}: Props) {
  const safe = sanitizeHex(value);

  return (
    <Popover modal={false}>
      <PopoverTrigger asChild>
        <Button
          type='button'
          variant='outline'
          disabled={disabled}
          className={cn(
            'h-10 w-full justify-start gap-3 px-3 font-normal',
            className
          )}
          aria-label={ariaLabel}
        >
          <span
            className='size-6 shrink-0 rounded-md border bg-background shadow-sm'
            style={{ backgroundColor: safe }}
          />
          <span className='font-mono text-xs text-muted-foreground'>
            {safe}
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align='start'
        side='top'
        sideOffset={8}
        collisionPadding={16}
        className='z-[10050] w-auto border bg-popover p-3 shadow-lg'
      >
        <HexColorPicker
          color={safe}
          onChange={(c) => onChange(sanitizeHex(c))}
          style={{ width: 200, height: 140 }}
        />
        <Input
          className='mt-2 h-8 font-mono text-xs'
          value={safe}
          onChange={(e) => onChange(sanitizeHex(e.target.value))}
          maxLength={7}
          spellCheck={false}
          aria-label={ariaLabel}
        />
      </PopoverContent>
    </Popover>
  );
}
