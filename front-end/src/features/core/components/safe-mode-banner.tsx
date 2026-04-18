'use client';

import { useSafeMode } from '@/features/core/services/use-safe-mode';

/**
 * Compact status banner rendered at the top of pages that expose write
 * actions. Nothing renders when safe-mode is off, so it's safe to drop in
 * anywhere without extra conditionals at the call site.
 */
export function SafeModeBanner({ className = '' }: { className?: string }) {
  const { read_only, stream_hierarchy } = useSafeMode();

  if (!read_only && stream_hierarchy) return null;

  const parts: string[] = [];
  if (read_only) parts.push('Read-only (không cho sửa/điều khiển)');
  if (!stream_hierarchy) parts.push('UI hierarchy stream tắt');

  return (
    <div
      role='status'
      className={`rounded-md border border-amber-400/40 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-900 shadow-sm dark:border-amber-300/30 dark:bg-amber-950/40 dark:text-amber-200 ${className}`}
    >
      Safe mode: {parts.join(' · ')}
    </div>
  );
}
