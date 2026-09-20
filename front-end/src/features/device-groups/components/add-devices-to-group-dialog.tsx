'use client';

import { useState } from 'react';
import { Plus, Search, X } from 'lucide-react';
import { useTranslations } from 'next-intl';
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

interface Props {
  groupId: string;
}

const AVAILABLE_DEVICES_PAGE_SIZE = 5;

export function AddDevicesToGroupDialog({ groupId }: Props) {
  const t = useTranslations('deviceGroupsFeature.addDevicesDialog');
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [pageIndex, setPageIndex] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const { mutate, isPending } = useAddDevicesToGroup();
  const availableDevicesQuery = useAvailableGroupDevices(
    groupId,
    {
      q: searchQuery.trim() || undefined,
      limit: AVAILABLE_DEVICES_PAGE_SIZE,
      offset: pageIndex * AVAILABLE_DEVICES_PAGE_SIZE
    },
    { enabled: open }
  );

  const available = availableDevicesQuery.data?.items ?? [];
  const total = availableDevicesQuery.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / AVAILABLE_DEVICES_PAGE_SIZE));

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
          setSelected([]);
          setOpen(false);
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
            available.length === 0 && (
              <p className='text-sm text-muted-foreground'>{t('noDevices')}</p>
            )}
          {!availableDevicesQuery.isLoading &&
            !availableDevicesQuery.isError &&
            available.map((d: DeviceOut) => (
              <label
                key={d.id}
                className='flex cursor-pointer items-center gap-3 rounded-md border p-3 hover:bg-muted/50'
              >
                <Checkbox
                  checked={selected.includes(d.id)}
                  onCheckedChange={() => toggle(d.id)}
                />
                <div className='min-w-0 flex-1'>
                  <p className='truncate text-sm font-medium'>
                    {d.name || d.serial}
                  </p>
                  <p className='text-xs text-muted-foreground'>
                    {d.brand} {d.model}
                  </p>
                </div>
              </label>
            ))}
        </div>
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
