'use client';

import { useSafeMode } from '@/features/core/services/use-safe-mode';
import { useServerStatus } from '@/features/core/services/use-server-status';

/**
 * Status banner for config safe-mode and DB-degraded safe mode.
 */
export function SafeModeBanner({ className = '' }: { className?: string }) {
  const { read_only, stream_hierarchy } = useSafeMode();
  const { safe_mode, db_connected } = useServerStatus();

  if (!read_only && stream_hierarchy && !safe_mode && db_connected) return null;

  const parts: string[] = [];
  if (safe_mode || !db_connected) {
    parts.push(
      'Hệ thống đang ở chế độ giới hạn (safe mode). Một số chức năng tạm không dùng được. Auto-refresh trong 30s…'
    );
  }
  if (read_only) parts.push('Read-only (không cho sửa/điều khiển)');
  if (!stream_hierarchy) parts.push('UI hierarchy stream tắt');

  return (
    <div
      role='status'
      className={`rounded-md border border-amber-400/40 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-900 shadow-sm dark:border-amber-300/30 dark:bg-amber-950/40 dark:text-amber-200 ${className}`}
    >
      {parts.join(' · ')}
    </div>
  );
}
