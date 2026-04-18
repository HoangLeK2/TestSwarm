'use client';

import { useState } from 'react';
import { AlertTriangle, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  useDismissDlqEntry,
  useDlqEntries,
  useRetryDlqEntry,
} from '../../hooks/use-campaigns';

function fmtDate(value: string | null): string {
  if (!value) return '—';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleString('vi-VN', { hour12: false });
}

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'pending') return 'destructive';
  if (status === 'retrying') return 'default';
  if (status === 'dismissed') return 'secondary';
  return 'outline';
}

function statusLabel(status: string): string {
  if (status === 'pending') return 'đang chờ';
  if (status === 'retrying') return 'đang thử lại';
  if (status === 'dismissed') return 'đã bỏ qua';
  return status;
}

export function DlqPanel() {
  const { data = [], isLoading } = useDlqEntries(true, 'pending');
  const retryMut = useRetryDlqEntry();
  const dismissMut = useDismissDlqEntry();
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null);

  return (
    <div className='border-t bg-red-500/[0.02] p-3'>
      <div className='mb-2 flex items-center gap-2'>
        <AlertTriangle size={14} className='text-red-600 dark:text-red-400' />
        <p className='text-xs font-semibold'>Hàng đợi lỗi (DLQ)</p>
        <Badge variant={data.length > 0 ? 'destructive' : 'secondary'} className='ml-auto'>
          {data.length}
        </Badge>
      </div>

      {isLoading ? (
        <div className='flex items-center gap-2 py-2 text-[11px] text-muted-foreground'>
          <Loader2 size={12} className='animate-spin' />
          Đang tải DLQ...
        </div>
      ) : null}

      {!isLoading && data.length === 0 ? (
        <p className='py-2 text-[11px] text-muted-foreground'>Không có lỗi pending trong DLQ.</p>
      ) : null}

      <div className='max-h-56 space-y-2 overflow-y-auto pr-1'>
        {data.map((entry) => {
          const isRowPending =
            activeEntryId === entry.id && (retryMut.isPending || dismissMut.isPending);

          return (
            <div key={entry.id} className='rounded-md border bg-background p-2'>
              <div className='mb-1 flex items-center gap-2'>
                <code className='truncate text-[10px] font-semibold'>{entry.device_serial}</code>
                <Badge variant={statusVariant(entry.status)}>{statusLabel(entry.status)}</Badge>
                <span className='ml-auto text-[10px] text-muted-foreground'>
                  thử lại: {entry.retry_count}
                </span>
              </div>

              <p
                className={cn(
                  'mb-2 line-clamp-2 text-[11px]',
                  entry.error ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'
                )}
                title={entry.error ?? ''}
              >
                {entry.error || 'Không có error message'}
              </p>

              <div className='mb-2 grid grid-cols-2 gap-2 text-[10px] text-muted-foreground'>
                <span title={entry.execution_id}>lần chạy: {entry.execution_id.slice(0, 8)}</span>
                <span className='text-right'>lần cuối: {fmtDate(entry.last_attempt_at)}</span>
              </div>

              <div className='flex items-center justify-end gap-1.5'>
                <Button
                  size='sm'
                  variant='outline'
                  className='h-6 gap-1 px-2 text-[10px]'
                  disabled={isRowPending}
                  onClick={() => {
                    setActiveEntryId(entry.id);
                    retryMut.mutate(entry.id, {
                      onSuccess: () => toast.success('Đã đánh dấu retry'),
                      onError: () => toast.error('Thử lại thất bại'),
                      onSettled: () => setActiveEntryId(null),
                    });
                  }}
                >
                  <RefreshCw size={10} className={isRowPending && retryMut.isPending ? 'animate-spin' : ''} />
                  Thử lại
                </Button>
                <Button
                  size='sm'
                  variant='ghost'
                  className='h-6 gap-1 px-2 text-[10px] text-muted-foreground'
                  disabled={isRowPending}
                  onClick={() => {
                    setActiveEntryId(entry.id);
                    dismissMut.mutate(entry.id, {
                      onSuccess: () => toast.success('Đã dismiss DLQ item'),
                      onError: () => toast.error('Bỏ qua thất bại'),
                      onSettled: () => setActiveEntryId(null),
                    });
                  }}
                >
                  <Trash2 size={10} />
                  Bỏ qua
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
