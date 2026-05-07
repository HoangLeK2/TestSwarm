'use client';

import { Braces } from 'lucide-react';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

export const DEFAULT_DEVICE_VARIABLES = {
  group: '',
  save_collection: '',
};

export function parseDeviceVarsJson(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text || '{}') as unknown;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('JSON phải là object, ví dụ {"group": "abc"}');
  }
  return parsed as Record<string, unknown>;
}

export function formatDeviceVarsJson(vars: Record<string, unknown>) {
  return JSON.stringify(vars, null, 2);
}

export function formatInitialDeviceVars(vars: Record<string, unknown>) {
  return formatDeviceVarsJson(Object.keys(vars).length ? vars : DEFAULT_DEVICE_VARIABLES);
}

type DeviceVarsJsonPanelProps = {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  draft: string;
  onDraftChange: (value: string) => void;
  loading?: boolean;
  jsonError?: string;
  deviceLabel?: string;
  className?: string;
  editorClassName?: string;
  emptyClassName?: string;
};

export function DeviceVarsJsonPanel({
  enabled,
  onEnabledChange,
  draft,
  onDraftChange,
  loading = false,
  jsonError = '',
  deviceLabel,
  className,
  editorClassName,
  emptyClassName,
}: DeviceVarsJsonPanelProps) {
  return (
    <div className={cn('min-h-0', className)}>
      <div className='mb-3 flex items-center justify-between gap-3'>
        <div className='min-w-0'>
          <div className='flex items-center gap-2 text-xs font-medium'>
            <Braces size={13} />
            Biến thiết bị cho kịch bản
          </div>
          {deviceLabel && (
            <p className='mt-0.5 truncate text-[11px] text-muted-foreground'>
              {deviceLabel}
            </p>
          )}
        </div>
      </div>

      <div className='mb-3 flex items-center justify-between rounded border bg-muted/20 px-3 py-2'>
        <div className='min-w-0'>
          <p className='text-xs font-medium'>Dùng biến riêng thiết bị</p>
          <p className='mt-0.5 text-[11px] text-muted-foreground'>
            Tắt để chạy bằng biến global của campaign/kịch bản.
          </p>
        </div>
        <Switch
          checked={enabled}
          disabled={loading}
          onCheckedChange={onEnabledChange}
          aria-label='Dùng biến riêng thiết bị'
        />
      </div>

      {enabled ? (
        <Textarea
          className={cn('min-h-[420px] resize-none font-mono text-xs leading-5', editorClassName)}
          value={draft}
          disabled={loading}
          spellCheck={false}
          onChange={(event) => onDraftChange(event.target.value)}
        />
      ) : (
        <div
          className={cn(
            'flex min-h-[420px] items-center justify-center rounded-md border border-dashed bg-muted/10 px-6 text-center text-xs text-muted-foreground',
            emptyClassName,
          )}
        >
          Thiết bị này sẽ không inject biến riêng. Scenario sẽ dùng biến global đã cấu hình ở campaign/kịch bản.
        </div>
      )}

      <div className='mt-2 flex min-h-5 items-center justify-between gap-3 text-[11px]'>
        <span className='text-muted-foreground'>
          {loading
            ? 'Đang tải cấu hình đã lưu...'
            : enabled
              ? 'Điền value vào JSON mẫu; key sẽ được map thành __DEVICE_* khi chạy.'
              : 'Đang dùng biến global.'}
        </span>
        {jsonError && <span className='text-destructive'>{jsonError}</span>}
      </div>
    </div>
  );
}
