'use client';

import { useEffect, useMemo, useState } from 'react';
import { Plus, Search, X } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import {
  useAddDevicesToGroup,
  useAvailableGroupDevices
} from '../hooks/use-device-groups';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { TablePaginationControls } from '@/components/ui/table/data-table-pagination';
import type { DeviceOut } from '@/features/devices/services/manage-api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import {
  deviceDisplayName,
  deviceModelLabel,
  deviceSecondarySerial
} from '@/features/devices/lib/device-display-name';

interface Props {
  groupId: string;
}

const AVAILABLE_DEVICES_PAGE_SIZE = 5;

export function AddDevicesToGroupDialog({ groupId }: Props) {
  const t = useTranslations('deviceGroupsFeature.addDevicesDialog');
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
  const [pageIndex, setPageIndex] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const { mutate, isPending } = useAddDevicesToGroup();

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSearchQuery(searchQuery.trim()),
      250
    );
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  const availableDevicesQuery = useAvailableGroupDevices(
    groupId,
    {
      q: debouncedSearchQuery || undefined,
      limit: AVAILABLE_DEVICES_PAGE_SIZE,
      offset: pageIndex * AVAILABLE_DEVICES_PAGE_SIZE
    },
    { enabled: open }
  );

  const available = useMemo(
    () => availableDevicesQuery.data?.items ?? [],
    [availableDevicesQuery.data?.items]
  );
  const total = availableDevicesQuery.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / AVAILABLE_DEVICES_PAGE_SIZE));
  const isRefreshingResults =
    availableDevicesQuery.isFetching && !availableDevicesQuery.isLoading;
  const selectedNames = useMemo(
    () =>
      available
        .filter((device) => selected.includes(device.id))
        .map((device) => deviceDisplayName(device)),
    [available, selected]
  );

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSubmit = () => {
    if (!selected.length) return;
    mutate(
      { groupId, deviceIds: selected },
      {
        onSuccess: () => {
          toast.success(t('addSuccess', { count: selected.length }));
          setSelected([]);
          setOpen(false);
        },
        onError: (err) => {
          toast.error(formatFarmApiError(err, t('addFailed')));
        }
      }
    );
  };

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setSelected([]);
      setSearchQuery('');
      setPageIndex(0);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline'>
          <Plus size={16} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <div className='relative pt-2'>
          <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
          <Input
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value);
              setPageIndex(0);
            }}
            placeholder={t('searchPlaceholder')}
            aria-label={t('searchLabel')}
            className='h-9 pl-8 pr-8'
          />
          {searchQuery ? (
            <Button
              type='button'
              variant='ghost'
              size='icon'
              className='absolute right-1 top-1/2 size-7 -translate-y-1/2 text-muted-foreground'
              onClick={() => {
                setSearchQuery('');
                setPageIndex(0);
              }}
              aria-label={t('searchClear')}
            >
              <X className='size-3.5' />
            </Button>
          ) : null}
        </div>
        <div className='max-h-64 space-y-2 overflow-y-auto pt-2'>
          {availableDevicesQuery.isLoading && (
            <p className='text-sm text-muted-foreground'>{t('loading')}</p>
          )}
          {availableDevicesQuery.isError && (
            <p className='text-sm text-destructive'>{t('loadError')}</p>
          )}
          {!availableDevicesQuery.isLoading &&
            !availableDevicesQuery.isError &&
            isRefreshingResults && (
              <p className='text-xs text-muted-foreground'>{t('refreshing')}</p>
            )}
          {!availableDevicesQuery.isLoading &&
            !availableDevicesQuery.isError &&
            available.length === 0 && (
              <p className='text-sm text-muted-foreground'>{t('noDevices')}</p>
            )}
          {!availableDevicesQuery.isLoading &&
            !availableDevicesQuery.isError &&
            available.map((d: DeviceOut) => (
              <label
                key={d.id}
                className='flex cursor-pointer items-center gap-3 rounded-md border p-3 hover:bg-muted/50 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60'
              >
                <Checkbox
                  checked={selected.includes(d.id)}
                  disabled={isRefreshingResults}
                  onCheckedChange={() => toggle(d.id)}
                  aria-label={t('selectDevice', {
                    device: deviceDisplayName(d)
                  })}
                />
                <div className='min-w-0 flex-1'>
                  <p className='truncate text-sm font-medium'>
                    {deviceDisplayName(d)}
                  </p>
                  <div className='space-y-0.5 text-xs text-muted-foreground'>
                    {deviceSecondarySerial(d) ? (
                      <p className='truncate'>
                        {t('serialLabel', {
                          serial: deviceSecondarySerial(d)
                        })}
                      </p>
                    ) : null}
                    {deviceModelLabel(d) ? (
                      <p className='truncate'>{deviceModelLabel(d)}</p>
                    ) : null}
                  </div>
                </div>
              </label>
            ))}
        </div>
        {selected.length ? (
          <div className='rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground'>
            <p className='font-medium text-foreground'>
              {t('selectedSummary', { count: selected.length })}
            </p>
            {selectedNames.length ? (
              <p className='mt-1 truncate'>
                {selectedNames.slice(0, 3).join(', ')}
                {selected.length > selectedNames.length
                  ? t('selectedMore', {
                      count: selected.length - selectedNames.length
                    })
                  : ''}
              </p>
            ) : null}
          </div>
        ) : null}
        <TablePaginationControls
          pageIndex={pageIndex}
          pageCount={pageCount}
          pageSize={AVAILABLE_DEVICES_PAGE_SIZE}
          total={total}
          showRowsPerPage={false}
          className='px-0 py-1'
          onPageIndexChange={(nextPage) => {
            if (availableDevicesQuery.isFetching) return;
            setPageIndex(Math.max(0, Math.min(pageCount - 1, nextPage)));
          }}
          onPageSizeChange={() => undefined}
        />
        <Button
          onClick={handleSubmit}
          disabled={
            isPending ||
            availableDevicesQuery.isLoading ||
            availableDevicesQuery.isError ||
            isRefreshingResults ||
            selected.length === 0
          }
          className='w-full'
        >
          {isPending ? t('adding') : t('submit', { count: selected.length })}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
