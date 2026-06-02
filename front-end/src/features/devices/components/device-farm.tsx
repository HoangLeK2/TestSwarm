'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ROUTES } from '@/config/routes';
import { DeviceTilePreview } from './device-tile-preview';
import { ConnectDeviceDialog } from './connect-device-dialog';
import { DeviceStepsSheet } from './device-step-monitor';
import { useDeviceFarm } from '../hooks/use-device-farm';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious
} from '@/components/ui/pagination';
import { cn } from '@/lib/utils';
import { CoreEmptyState } from '@/components/core-empty-state';
import { Smartphone } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { farmApi } from '@/lib/farm-api';
import type { DeviceFarmStreamingConfig } from '../types';

const GRID_PAGE_SIZE = (() => {
  const raw = Number(process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PAGE_SIZE ?? 10);
  if (!Number.isFinite(raw)) return 10;
  return Math.max(1, Math.min(50, Math.round(raw)));
})();

export function DeviceFarm() {
  const t = useTranslations('devicesFarm');
  const tEmpty = useTranslations('coreEmptyState');
  const tHeader = useTranslations('devicesFarm.header');
  const tTable = useTranslations('components.table');
  const [connectDialogOpen, setConnectDialogOpen] = useState(false);
  const [stepsSerial, setStepsSerial] = useState<string | null>(null);
  const [serverAllowPreviewMjpeg, setServerAllowPreviewMjpeg] = useState(true);
  const [streamingConfig, setStreamingConfig] =
    useState<DeviceFarmStreamingConfig | null>(null);

  useEffect(() => {
    farmApi
      .get<{
        streaming_dashboard_preview_mjpeg?: boolean;
        streaming_mode?: string;
        streaming_auto_attach_scrcpy?: boolean;
        streaming_auto_attach_scrcpy_on_relay_online?: boolean;
      }>('/config')
      .then((res) => {
        const v = res.data?.streaming_dashboard_preview_mjpeg;
        if (typeof v === 'boolean') setServerAllowPreviewMjpeg(v);
        setStreamingConfig({
          mode: String(res.data?.streaming_mode ?? 'periodic'),
          autoAttachScrcpy: Boolean(
            res.data?.streaming_auto_attach_scrcpy ?? true
          ),
          autoAttachScrcpyOnRelayOnline: Boolean(
            res.data?.streaming_auto_attach_scrcpy_on_relay_online ?? true
          )
        });
      })
      .catch(() => {
        setStreamingConfig({
          mode: 'periodic',
          autoAttachScrcpy: true,
          autoAttachScrcpyOnRelayOnline: true
        });
      });
  }, []);

  const { devices, tasks, wsConnected, error } = useDeviceFarm();

  const activeDevices = useMemo(
    () =>
      devices.filter(
        (d) =>
          d.state && !['DISCONNECTED', 'DEAD'].includes(d.state.toUpperCase())
      ),
    [devices]
  );

  const [pageIndex, setPageIndex] = useState(0);
  const pageCount = Math.max(
    1,
    Math.ceil(activeDevices.length / GRID_PAGE_SIZE)
  );

  useEffect(() => {
    setPageIndex((prev) => Math.min(prev, pageCount - 1));
  }, [pageCount]);

  const pageDevices = useMemo(() => {
    const start = pageIndex * GRID_PAGE_SIZE;
    return activeDevices.slice(start, start + GRID_PAGE_SIZE);
  }, [activeDevices, pageIndex]);

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
          <section className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4'>
            {pageDevices.map((device) => (
              <DeviceTilePreview
                key={device.serial}
                device={device}
                serverAllowPreviewMjpeg={serverAllowPreviewMjpeg}
                streamingConfig={streamingConfig}
                onOpenSteps={openStepsMonitor}
              />
            ))}
          </section>
          <footer className='flex flex-col items-center gap-2 border-t border-border/40 pt-4 sm:flex-row sm:justify-between'>
            <p className='text-xs tabular-nums text-muted-foreground'>
              {tTable('total')}: {activeDevices.length}
              {pageCount > 1
                ? ` · ${tTable('pageOf', { current: pageIndex + 1, total: pageCount })}`
                : null}
            </p>
            {pageCount > 1 ? (
              <Pagination className='mx-0 w-auto'>
                <PaginationContent>
                  <PaginationItem>
                    <PaginationPrevious
                      href='#'
                      onClick={(e) => {
                        e.preventDefault();
                        setPageIndex((p) => Math.max(0, p - 1));
                      }}
                      className={cn(
                        'h-8',
                        pageIndex <= 0 && 'pointer-events-none opacity-50'
                      )}
                    />
                  </PaginationItem>
                  <PaginationItem>
                    <span className='flex h-8 min-w-[4.5rem] items-center justify-center rounded-md border border-border/60 bg-muted/40 px-3 text-xs font-medium tabular-nums'>
                      {pageIndex + 1} / {pageCount}
                    </span>
                  </PaginationItem>
                  <PaginationItem>
                    <PaginationNext
                      href='#'
                      onClick={(e) => {
                        e.preventDefault();
                        setPageIndex((p) => Math.min(pageCount - 1, p + 1));
                      }}
                      className={cn(
                        'h-8',
                        pageIndex >= pageCount - 1 &&
                          'pointer-events-none opacity-50'
                      )}
                    />
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            ) : null}
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
