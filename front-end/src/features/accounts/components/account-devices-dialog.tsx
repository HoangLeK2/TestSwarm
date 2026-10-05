'use client';

import {
  useState,
  useCallback,
  useEffect,
  useMemo,
  type ReactNode
} from 'react';
import { Search, Smartphone, Unlink, Star } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import {
  useAccountDevices,
  useAssignDeviceToAccount,
  useAvailableAccountDevices,
  useDeviceAccounts,
  useSetPrimaryDeviceAccount,
  useUnassignDeviceFromAccount
} from '../hooks/use-accounts';
import type { AccountOut, DeviceOut } from '../services/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TablePaginationControls } from '@/components/ui/table/data-table-pagination';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';

function deviceLabel(d: { serial: string; name?: string | null }) {
  return d.name?.trim() || d.serial || '—';
}

const AVAILABLE_DEVICES_PAGE_SIZE = 5;

function LinkedDeviceRow({
  link,
  device,
  canUpdate,
  unassigning,
  t,
  onRemove
}: {
  link: {
    id: string;
    device_id: string;
    account_id: string;
    is_primary: boolean;
  };
  device?: { serial: string; name?: string | null };
  canUpdate: boolean;
  unassigning: boolean;
  t: (key: string, values?: Record<string, string | number>) => string;
  onRemove: () => void;
}) {
  return (
    <li className='space-y-3 rounded-lg border bg-background p-3 text-xs'>
      <div className='flex items-start gap-2'>
        <Smartphone className='mt-0.5 size-4 shrink-0 text-muted-foreground' />
        <span className='min-w-0 flex-1 truncate'>
          {device ? (
            <>
              <span className='block font-medium'>{deviceLabel(device)}</span>
              <span className='block text-[10px] text-muted-foreground'>
                {device.serial}
              </span>
            </>
          ) : (
            link.device_id
          )}
        </span>
        {link.is_primary && (
          <span className='flex items-center gap-1 text-[10px] text-yellow-600'>
            <Star size={12} fill='currentColor' />
            {t('primary')}
          </span>
        )}
      </div>
      {canUpdate ? (
        <div>
          <Button
            type='button'
            size='sm'
            variant='outline'
            className='h-8 gap-1.5 text-xs'
            disabled={unassigning}
            onClick={onRemove}
          >
            <Unlink size={13} />
            {t('removeLink')}
          </Button>
        </div>
      ) : null}
    </li>
  );
}

export function AccountDevicesDialog({
  account,
  canUpdate,
  trigger
}: {
  account: AccountOut;
  canUpdate: boolean;
  trigger?: ReactNode;
}) {
  const t = useTranslations('accountsFeature.devicesDialog');
  const [open, setOpen] = useState(false);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [makePrimary, setMakePrimary] = useState(true);
  const [deviceQuery, setDeviceQuery] = useState('');
  const [devicePageIndex, setDevicePageIndex] = useState(0);
  const [selectedDeviceSnapshot, setSelectedDeviceSnapshot] =
    useState<DeviceOut | null>(null);

  const { data: links = [] } = useAccountDevices(open ? account.id : '');
  const availableDeviceParams = useMemo(
    () => ({
      q: deviceQuery.trim() || undefined,
      limit: AVAILABLE_DEVICES_PAGE_SIZE,
      offset: devicePageIndex * AVAILABLE_DEVICES_PAGE_SIZE
    }),
    [devicePageIndex, deviceQuery]
  );
  const availableDevices = useAvailableAccountDevices(
    account.id,
    availableDeviceParams,
    { enabled: open && canUpdate }
  );
  const { mutateAsync: assignDevice, isPending: assigning } =
    useAssignDeviceToAccount();
  const setPrimary = useSetPrimaryDeviceAccount();
  const { mutate: unassignDevice, isPending: unassigning } =
    useUnassignDeviceFromAccount();

  const available = availableDevices.data?.items ?? [];
  const availableTotal = availableDevices.data?.total ?? 0;
  const devicePageCount = Math.max(
    1,
    Math.ceil(availableTotal / AVAILABLE_DEVICES_PAGE_SIZE)
  );
  // From the unfiltered set: typing a new search must not hide the assign
  // button for the device already picked.
  const selectedDevice =
    available.find((d) => d.id === selectedDeviceId) ||
    (selectedDeviceSnapshot?.id === selectedDeviceId
      ? selectedDeviceSnapshot
      : null);
  const { data: selectedDeviceAccounts = [] } =
    useDeviceAccounts(selectedDeviceId);
  const currentPrimaryLink = selectedDeviceAccounts.find(
    (link) => link.is_primary
  );

  useEffect(() => {
    setDevicePageIndex((current) =>
      Math.min(current, Math.max(0, devicePageCount - 1))
    );
  }, [devicePageCount]);

  const handleAssign = useCallback(async () => {
    if (!selectedDeviceId) return;
    try {
      await assignDevice({ accountId: account.id, deviceId: selectedDeviceId });
      if (makePrimary) {
        await setPrimary.mutateAsync({
          deviceId: selectedDeviceId,
          accountId: account.id
        });
      }
      toast.success(
        t('assignSuccess', {
          account: account.display_name || account.username,
          device: selectedDevice
            ? deviceLabel(selectedDevice)
            : selectedDeviceId
        })
      );
      setSelectedDeviceId('');
      setSelectedDeviceSnapshot(null);
    } catch {
      toast.error(t('assignError'));
    }
  }, [
    account,
    assignDevice,
    makePrimary,
    selectedDevice,
    selectedDeviceId,
    setPrimary,
    t
  ]);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setDeviceQuery('');
          setDevicePageIndex(0);
          setSelectedDeviceSnapshot(null);
        }
        setOpen(next);
      }}
    >
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size='sm' variant='outline' className='h-8 gap-1.5 text-xs'>
            <Smartphone size={14} />
            {t('trigger')}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <p className='text-sm text-muted-foreground'>
            {account.display_name || account.username} · {account.platform}
          </p>
        </DialogHeader>
        <div className='space-y-4 pt-2'>
          {/* Linked devices */}
          {links.length > 0 && (
            <div className='rounded-lg border border-border/60 bg-muted/20 p-3'>
              <p className='mb-2 text-xs font-medium'>
                {t('linkedDevices', { count: links.length })}
              </p>
              <ul className='max-h-64 space-y-2 overflow-y-auto'>
                {links.map((link) => (
                  <LinkedDeviceRow
                    key={link.id}
                    link={link}
                    canUpdate={canUpdate}
                    unassigning={unassigning}
                    t={t}
                    onRemove={() =>
                      unassignDevice(
                        { accountId: account.id, deviceId: link.device_id },
                        {
                          onSuccess: () => toast.success(t('removeSuccess')),
                          onError: () => toast.error(t('removeError'))
                        }
                      )
                    }
                  />
                ))}
              </ul>
            </div>
          )}

          {/* Available devices */}
          {canUpdate ? (
            <div>
              <p className='mb-2 text-xs font-medium'>
                {t('availableDevices')}
              </p>
              {availableDevices.isLoading ? (
                <p className='text-sm text-muted-foreground'>{t('loading')}</p>
              ) : availableTotal === 0 && !deviceQuery.trim() ? (
                <p className='text-sm text-muted-foreground'>
                  {t('noAvailable')}
                </p>
              ) : (
                <div className='space-y-3'>
                  <div className='relative'>
                    <Search className='absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
                    <Input
                      value={deviceQuery}
                      onChange={(event) => {
                        setDeviceQuery(event.target.value);
                        setDevicePageIndex(0);
                      }}
                      placeholder={t('searchPlaceholder')}
                      aria-label={t('searchPlaceholder')}
                      className='h-8 pl-8 text-sm'
                    />
                  </div>
                  {availableTotal === 0 ? (
                    <p className='text-sm text-muted-foreground'>
                      {t('noSearchMatch')}
                    </p>
                  ) : (
                    <div className='rounded-lg border border-border/60'>
                      <ul className='space-y-1 p-2'>
                        {available.map((d) => (
                          <li
                            key={d.id}
                            className='flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50'
                          >
                            <input
                              type='radio'
                              name='account-device'
                              checked={selectedDeviceId === d.id}
                              onChange={() => {
                                setSelectedDeviceId(d.id);
                                setSelectedDeviceSnapshot(d);
                              }}
                            />
                            <button
                              type='button'
                              className='min-w-0 flex-1 text-left'
                              onClick={() => {
                                setSelectedDeviceId(d.id);
                                setSelectedDeviceSnapshot(d);
                              }}
                            >
                              <span className='block truncate text-sm font-medium'>
                                {deviceLabel(d)}
                              </span>
                              <span className='block truncate text-[10px] text-muted-foreground'>
                                {d.serial}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                      <TablePaginationControls
                        pageIndex={devicePageIndex}
                        pageCount={devicePageCount}
                        pageSize={AVAILABLE_DEVICES_PAGE_SIZE}
                        total={availableTotal}
                        showRowsPerPage={false}
                        className='border-t px-2 py-1'
                        onPageIndexChange={(nextPage) =>
                          setDevicePageIndex(
                            Math.max(0, Math.min(devicePageCount - 1, nextPage))
                          )
                        }
                        onPageSizeChange={() => undefined}
                      />
                    </div>
                  )}
                  {selectedDevice && (
                    <div className='space-y-2 rounded-lg border bg-muted/20 p-3 text-xs'>
                      {currentPrimaryLink && (
                        <p className='text-amber-700 dark:text-amber-300'>
                          {t('replacePrimaryWarning')}
                        </p>
                      )}
                      <label className='flex items-center gap-2'>
                        <input
                          type='checkbox'
                          checked={makePrimary}
                          onChange={(event) =>
                            setMakePrimary(event.target.checked)
                          }
                        />
                        {t('makePrimary')}
                      </label>
                      <Button
                        className='w-full'
                        disabled={assigning || setPrimary.isPending}
                        onClick={handleAssign}
                      >
                        {t('assignAction', {
                          account: account.display_name || account.username,
                          device: deviceLabel(selectedDevice)
                        })}
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
