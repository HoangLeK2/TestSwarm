'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ROUTES } from '@/config/routes';
import { DeviceTilePreview } from './device-tile-preview';
import { ConnectDeviceDialog } from './connect-device-dialog';
import { DeviceStepsSheet } from './device-step-monitor';
import { useDeviceFarm } from '../hooks/use-device-farm';
import { Badge } from '@/components/ui/badge';
import { TablePaginationControls } from '@/components/ui/table/data-table-pagination';
import { CoreEmptyState } from '@/components/core-empty-state';
import { Smartphone } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { isVisibleDeviceFarmActiveDevice } from '../lib/device-farm-visible-devices';

const DEFAULT_GRID_PAGE_SIZE = (() => {
  const raw = Number(process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PAGE_SIZE ?? 10);
  if (!Number.isFinite(raw)) return 10;
  return Math.max(1, Math.min(50, Math.round(raw)));
})();

export function DeviceFarm() {
  const t = useTranslations('devicesFarm');
  const tEmpty = useTranslations('coreEmptyState');
  const tHeader = useTranslations('devicesFarm.header');
  const [connectDialogOpen, setConnectDialogOpen] = useState(false);
  const [stepsSerial, setStepsSerial] = useState<string | null>(null);

  const { devices, tasks, wsConnected, error } = useDeviceFarm();

  const activeDevices = useMemo(
    () => devices.filter(isVisibleDeviceFarmActiveDevice),
    [devices]
  );

  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_GRID_PAGE_SIZE);
  const pageCount = Math.max(1, Math.ceil(activeDevices.length / pageSize));

  useEffect(() => {
    setPageIndex((prev) => Math.min(prev, pageCount - 1));
  }, [pageCount]);

  const pageDevices = useMemo(() => {
    const start = pageIndex * pageSize;
    return activeDevices.slice(start, start + pageSize);
  }, [activeDevices, pageIndex, pageSize]);

  const activeTaskCount = (Array.isArray(tasks) ? tasks : []).filter((task) =>
    ['PENDING', 'RUNNING', 'REQUEUED'].includes(task.status)
  ).length;

  const openStepsMonitor = useCallback((serial: string) => {
    setStepsSerial(serial);
  }, []);

  const handleStepsOpenChange = useCallback((open: boolean) => {
    if (!open) setStepsSerial(null);
  }, []);

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-center justify-end gap-2 text-[11px] text-muted-foreground'>
        <span className='inline-flex items-center gap-1 rounded-full border border-border bg-card/70 px-2 py-0.5'>
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              wsConnected ? 'bg-emerald-400' : 'animate-pulse bg-amber-400'
            }`}
          />
          <span id='ws-label' className='text-[10px]'>
            {wsConnected ? tHeader('realtimeOk') : tHeader('realtimeLost')}
          </span>
        </span>
        <div className='hidden items-center gap-1.5 sm:flex'>
          <Badge id='stat-total' variant='outline' className='text-[10px]'>
            {tHeader('devicesReady', { count: activeDevices.length })}
          </Badge>
          {devices.length > activeDevices.length ? (
            <Badge variant='secondary' className='text-[10px]'>
              {tHeader('devicesRegistered', { count: devices.length })}
            </Badge>
          ) : null}
          <Badge
            id='stat-tasks'
            variant={activeTaskCount > 0 ? 'default' : 'outline'}
            className='text-[10px]'
          >
            {tHeader('tasks', { count: activeTaskCount })}
          </Badge>
        </div>
      </div>

      {error && (
        <div className='rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive'>
          <div className='font-medium'>{t('backendErrorTitle')}</div>
          <div className='text-xs opacity-80'>{t('backendErrorHint')}</div>
          <pre className='mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px]'>
            {error}
          </pre>
        </div>
      )}

      {activeDevices.length === 0 ? (
        <CoreEmptyState
          icon={Smartphone}
          title={
            devices.length > 0 ? t('allDevicesOffline') : tEmpty('fleet.title')
          }
          description={
            devices.length > 0
              ? t('allDevicesOfflineHint', { count: devices.length })
              : tEmpty('fleet.description')
          }
          trackingKey='fleet-empty'
          cta={
            devices.length === 0
              ? {
                  label: tEmpty('fleet.ctaPair'),
                  href: ROUTES.DEVICES.MANAGE
                }
              : undefined
          }
          secondaryCta={
            devices.length === 0
              ? {
                  label: tEmpty('fleet.ctaRelay'),
                  href: ROUTES.RELAY_AGENTS.ROOT
                }
              : undefined
          }
        />
      ) : (
        <>
          <section
            className='grid justify-start gap-4'
            style={{
              gridTemplateColumns:
                'repeat(auto-fill, minmax(min(100%, 280px), 320px))'
            }}
          >
            {pageDevices.map((device) => (
              <DeviceTilePreview
                key={device.serial}
                device={device}
                onOpenSteps={openStepsMonitor}
              />
            ))}
          </section>
          <footer className='border-t border-border/40 pt-4'>
            <TablePaginationControls
              total={activeDevices.length}
              pageIndex={pageIndex}
              pageCount={pageCount}
              pageSize={pageSize}
              onPageIndexChange={setPageIndex}
              onPageSizeChange={(nextPageSize) => {
                setPageSize(nextPageSize);
                setPageIndex(0);
              }}
            />
          </footer>
        </>
      )}

      {stepsSerial ? (
        <DeviceStepsSheet
          serial={stepsSerial}
          open
          onOpenChange={handleStepsOpenChange}
        />
      ) : null}

      <ConnectDeviceDialog
        open={connectDialogOpen}
        onOpenChange={setConnectDialogOpen}
        liveCount={devices.length}
      />
    </div>
  );
}
