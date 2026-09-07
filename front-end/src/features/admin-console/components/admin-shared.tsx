'use client';

import { AlertCircle, Copy, Loader2, Search } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { TableCell, TableRow } from '@/components/ui/table';
import { TablePaginationControls } from '@/components/ui/table/data-table-pagination';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { ADMIN_ALL_WORKSPACES } from '../hooks/use-admin-workspace-scope';

export const ADMIN_PAGE_SIZE = 25;

export function AdminPageHeader({
  title,
  description,
  action
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className='flex flex-col gap-3 border-b bg-background px-4 py-4 md:flex-row md:items-center md:justify-between md:px-6'>
      <div className='min-w-0'>
        <h1 className='text-xl font-semibold tracking-normal text-foreground'>
          {title}
        </h1>
        <p className='mt-1 max-w-3xl text-sm text-muted-foreground'>
          {description}
        </p>
      </div>
      {action ? <div className='shrink-0'>{action}</div> : null}
    </div>
  );
}

const STATUS_TONE = {
  ok: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300',
  warn: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300',
  bad: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300',
  muted:
    'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300'
} as const;

// Covers account/workspace statuses plus runtime.core.device_client.DeviceState.
// Unlisted values fall back to the raw string with no tone — safe, but it means
// a new backend state shows up untranslated, so add it here when one lands.
const STATUS_TONES: Record<string, keyof typeof STATUS_TONE> = {
  online: 'ok',
  active: 'ok',
  ready: 'ok',
  busy: 'warn',
  stale: 'warn',
  suspended: 'warn',
  connecting: 'warn',
  dead: 'bad',
  error: 'bad',
  offline: 'muted',
  disabled: 'muted',
  archived: 'muted',
  disconnected: 'muted'
};

export function StatusBadge({ value }: { value?: string | null }) {
  const t = useTranslations('adminConsole.common.statuses');
  const status = (value || 'unknown').toLowerCase();
  const key = status as Parameters<typeof t>[0];
  const tone = STATUS_TONES[status];
  return (
    <Badge variant='outline' className={tone ? STATUS_TONE[tone] : ''}>
      {t.has(key) ? t(key) : status}
    </Badge>
  );
}

export function SearchField({
  value,
  onChange,
  placeholder
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div className='relative min-w-[220px] flex-1 md:max-w-sm'>
      <Search className='pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground' />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className='pl-8'
      />
    </div>
  );
}

export function AdminTableSkeleton({ columns = 6 }: { columns?: number }) {
  return (
    <>
      {Array.from({ length: 6 }).map((_, row) => (
        <TableRow key={row} className='hover:bg-transparent'>
          {Array.from({ length: columns }).map((__, col) => (
            <TableCell key={col}>
              <Skeleton className='h-4 w-full max-w-[160px]' />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

export function AdminErrorState({
  message,
  onRetry
}: {
  message: string;
  onRetry: () => void;
}) {
  const t = useTranslations('adminConsole.common');
  return (
    <div className='flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm'>
      <div className='flex min-w-0 items-center gap-2 text-destructive'>
        <AlertCircle className='size-4 shrink-0' />
        <span className='truncate'>{message}</span>
      </div>
      <Button size='sm' variant='outline' onClick={onRetry}>
        {t('retry')}
      </Button>
    </div>
  );
}

export function AdminWorkspaceScopeSelect({
  value,
  onChange,
  workspaces,
  allowGlobalScope,
  workspaceLabel,
  allWorkspacesLabel,
  triggerClassName
}: {
  value: string;
  onChange: (value: string) => void;
  workspaces: Array<{ id: string; businessName?: string | null }>;
  allowGlobalScope: boolean;
  workspaceLabel: string;
  allWorkspacesLabel: string;
  triggerClassName?: string;
}) {
  const valueForSelect =
    !allowGlobalScope && value === ADMIN_ALL_WORKSPACES ? undefined : value;
  return (
    <Select value={valueForSelect} onValueChange={onChange}>
      <SelectTrigger className={triggerClassName ?? 'w-full md:w-[260px]'}>
        <SelectValue placeholder={workspaceLabel} />
      </SelectTrigger>
      <SelectContent>
        {allowGlobalScope ? (
          <SelectItem value={ADMIN_ALL_WORKSPACES}>
            {allWorkspacesLabel}
          </SelectItem>
        ) : null}
        {workspaces.map((workspace) => (
          <SelectItem key={workspace.id} value={workspace.id}>
            {workspace.businessName || workspace.id}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function AdminPagination({
  offset,
  limit,
  total,
  onOffsetChange
}: {
  offset: number;
  limit: number;
  total: number;
  onOffsetChange: (offset: number) => void;
}) {
  const pageIndex = Math.floor(offset / limit);
  const pageCount = Math.max(1, Math.ceil(total / limit));
  return (
    <TablePaginationControls
      className='border-t px-3 py-3'
      pageIndex={pageIndex}
      pageCount={pageCount}
      pageSize={limit}
      total={total}
      showRowsPerPage={false}
      onPageIndexChange={(nextPage) => onOffsetChange(nextPage * limit)}
      onPageSizeChange={() => undefined}
    />
  );
}

export function SecretDialog({
  open,
  title,
  description,
  secret,
  onClose
}: {
  open: boolean;
  title: string;
  description: string;
  secret: string | null;
  onClose: () => void;
}) {
  const t = useTranslations('adminConsole.common');
  const copySecret = async () => {
    if (!secret) return;
    await navigator.clipboard.writeText(secret);
    toast.success(t('copied'));
  };
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {secret ? (
          <div className='flex items-center gap-2 rounded-md border bg-muted/40 p-3'>
            <code className='min-w-0 flex-1 break-all text-xs'>{secret}</code>
            <Button
              size='icon'
              variant='outline'
              className='size-8'
              onClick={copySecret}
            >
              <Copy className='size-4' />
            </Button>
          </div>
        ) : null}
        <DialogFooter>
          <Button onClick={onClose}>{t('close')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SubmitSpinner() {
  return <Loader2 className='mr-2 size-4 animate-spin' />;
}
