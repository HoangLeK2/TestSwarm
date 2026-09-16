'use client';

import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import {
  ADMIN_PAGE_SIZE,
  AdminErrorState,
  AdminPageHeader,
  AdminPagination,
  AdminTableSkeleton,
  AdminWorkspaceScopeSelect,
  SearchField,
  StatusBadge,
  SubmitSpinner
} from './admin-shared';
import { useAdminWorkspaceScope } from '../hooks/use-admin-workspace-scope';
import {
  adminApi,
  type AdminDeviceOut,
  formatAdminApiError
} from '../services/admin-api';

const ALL = '__all__';

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

export function AdminDevicesPage() {
  const t = useTranslations('adminConsole.devices');
  const qc = useQueryClient();
  const scope = useAdminWorkspaceScope();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState(ALL);
  const [assigned, setAssigned] = useState(ALL);
  const [offset, setOffset] = useState(0);
  const [transferDevice, setTransferDevice] = useState<AdminDeviceOut | null>(
    null
  );

  const workspaceParams = { offset: 0, limit: 100 };
  const workspaces = useQuery({
    queryKey: ['admin-workspaces-assignable', workspaceParams],
    queryFn: () => adminApi.listAssignableWorkspaces(workspaceParams)
  });

  const params = useMemo(
    () => ({
      search: search || undefined,
      status: status === ALL ? undefined : status,
      workspaceId: scope.scopedWorkspaceId,
      assigned: assigned === ALL ? undefined : assigned === 'assigned',
      offset,
      limit: ADMIN_PAGE_SIZE
    }),
    [assigned, offset, scope.scopedWorkspaceId, search, status]
  );

  const devices = useQuery({
    queryKey: ['admin-devices', params],
    queryFn: () => adminApi.listDevices(params),
    refetchInterval: 20_000
  });

  const transferMutation = useMutation({
    mutationFn: ({
      deviceId,
      workspaceId,
      userId
    }: {
      deviceId: string;
      workspaceId?: string;
      userId?: string;
    }) => adminApi.transferDevice(deviceId, { workspaceId, userId }),
    onSuccess: () => {
      setTransferDevice(null);
      toast.success(t('toast.assignmentUpdated'));
      void qc.invalidateQueries({ queryKey: ['admin-devices'] });
      void qc.invalidateQueries({ queryKey: ['admin-summary'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader title={t('title')} description={t('description')} />
      <div className='space-y-4 p-4 md:p-6'>
        <div className='grid gap-3 rounded-md border bg-background p-3 lg:grid-cols-[minmax(220px,1fr)_220px_170px_170px]'>
          <SearchField
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder={t('searchPlaceholder')}
          />
          <AdminWorkspaceScopeSelect
            value={scope.workspaceId}
            onChange={(value) => {
              scope.setWorkspaceId(value);
              setOffset(0);
            }}
            workspaces={scope.workspaces}
            allowGlobalScope={scope.allowGlobalScope}
            workspaceLabel={t('filters.workspace')}
            allWorkspacesLabel={t('filters.allWorkspaces')}
            // Default trigger is 260px; this grid column is 220px.
            triggerClassName='w-full'
          />
          <Select
            value={status}
            onValueChange={(value) => {
              setStatus(value);
              setOffset(0);
            }}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder={t('filters.status')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('filters.allStatuses')}</SelectItem>
              <SelectItem value='paired'>{t('statuses.paired')}</SelectItem>
              <SelectItem value='online'>{t('statuses.online')}</SelectItem>
              <SelectItem value='offline'>{t('statuses.offline')}</SelectItem>
              <SelectItem value='disabled'>{t('statuses.disabled')}</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={assigned}
            onValueChange={(value) => {
              setAssigned(value);
              setOffset(0);
            }}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder={t('filters.assignment')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('filters.allDevices')}</SelectItem>
              <SelectItem value='assigned'>{t('filters.assigned')}</SelectItem>
              <SelectItem value='unassigned'>
                {t('filters.unassigned')}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {devices.isError ? (
          <AdminErrorState
            message={formatAdminApiError(devices.error)}
            onRetry={() => void devices.refetch()}
          />
        ) : null}

        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.device')}</TableHead>
                  <TableHead>{t('table.workspace')}</TableHead>
                  <TableHead>{t('table.managedBy')}</TableHead>
                  <TableHead>{t('table.status')}</TableHead>
                  <TableHead>{t('table.state')}</TableHead>
                  <TableHead>{t('table.relay')}</TableHead>
                  <TableHead>{t('table.lastSeen')}</TableHead>
                  <TableHead className='text-right'>{t('table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {devices.isLoading ? <AdminTableSkeleton columns={8} /> : null}
                {devices.data?.items.map((device) => (
                  <TableRow key={device.id}>
                    <TableCell>
                      <div className='min-w-[220px]'>
                        <p className='font-medium'>
                          {device.name || device.serial}
                        </p>
                        <p className='text-xs text-muted-foreground'>
                          {device.serial}{' '}
                          {device.model ? `· ${device.model}` : ''}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      {device.workspaceName || device.workspaceId}
                    </TableCell>
                    <TableCell>
                      {device.managedByWorkspaceName ||
                        device.managedByWorkspaceId ||
                        '-'}
                    </TableCell>
                    <TableCell>
                      <StatusBadge value={device.status} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge value={device.state} />
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {device.relay_serial || device.adb_serial || '-'}
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {dateLabel(device.last_seen)}
                    </TableCell>
                    <TableCell className='text-right'>
                      <Button
                        type='button'
                        size='sm'
                        variant='outline'
                        disabled={!device.transferable}
                        title={
                          device.transferable
                            ? t('actions.transfer')
                            : t('actions.notTransferable')
                        }
                        onClick={() => setTransferDevice(device)}
                      >
                        {t('actions.transfer')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!devices.isLoading && devices.data?.items.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={8}
                      className='h-28 text-center text-sm text-muted-foreground'
                    >
                      {t('empty')}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
          <AdminPagination
            offset={offset}
            limit={ADMIN_PAGE_SIZE}
            total={devices.data?.total ?? 0}
            onOffsetChange={setOffset}
          />
        </div>
      </div>
      <DeviceTransferDialog
        device={transferDevice}
        workspaces={workspaces.data?.items ?? []}
        pending={transferMutation.isPending}
        onClose={() => setTransferDevice(null)}
        onSubmit={(deviceId, targetWorkspaceId) =>
          transferMutation.mutate({ deviceId, workspaceId: targetWorkspaceId })
        }
      />
    </div>
  );
}

function DeviceTransferDialog({
  device,
  workspaces,
  pending,
  onClose,
  onSubmit
}: {
  device: AdminDeviceOut | null;
  workspaces: Array<{ id: string; businessName: string }>;
  pending: boolean;
  onClose: () => void;
  onSubmit: (deviceId: string, workspaceId: string) => void;
}) {
  const t = useTranslations('adminConsole.devices.transferDialog');
  const tCommon = useTranslations('adminConsole.devices.common');
  const [workspaceId, setWorkspaceId] = useState('');
  useEffect(() => {
    setWorkspaceId('');
  }, [device?.id]);
  const target = workspaceId || device?.workspaceId || '';
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (device && target) onSubmit(device.id, target);
  };
  return (
    <Dialog open={!!device} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        {device ? (
          <form className='space-y-4' onSubmit={submit}>
            <div className='rounded-md border bg-muted/30 p-3 text-sm'>
              <p className='font-medium'>{device.name || device.serial}</p>
              <p className='text-xs text-muted-foreground'>
                {device.workspaceName || device.workspaceId}
              </p>
            </div>
            <div>
              <Label className='mb-2 block'>{t('destinationWorkspace')}</Label>
              <Select value={target} onValueChange={setWorkspaceId}>
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {workspaces.map((workspace) => (
                    <SelectItem key={workspace.id} value={workspace.id}>
                      {workspace.businessName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type='button' variant='outline' onClick={onClose}>
                {tCommon('cancel')}
              </Button>
              <Button type='submit' disabled={pending || !target}>
                {pending ? <SubmitSpinner /> : null}
                {t('transfer')}
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
