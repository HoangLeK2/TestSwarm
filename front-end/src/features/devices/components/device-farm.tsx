'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { ROUTES } from '@/config/routes';
import { DeviceFarmHeader } from './header';
import { DeviceTilePreview } from './device-tile-preview';
import { ConnectDeviceDialog } from './connect-device-dialog';
import { useDeviceFarm } from '../hooks/use-device-farm';
import { Button } from '@/components/ui/button';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination';
import { cn } from '@/lib/utils';
import { Smartphone, Plus } from 'lucide-react';
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
  const [connectDialogOpen, setConnectDialogOpen] = useState(false);
  const [serverAllowPreviewMjpeg, setServerAllowPreviewMjpeg] = useState(true);
  const [streamingConfig, setStreamingConfig] = useState<DeviceFarmStreamingConfig | null>(null);

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
          autoAttachScrcpy: Boolean(res.data?.streaming_auto_attach_scrcpy ?? true),
          autoAttachScrcpyOnRelayOnline: Boolean(
            res.data?.streaming_auto_attach_scrcpy_on_relay_online ?? true
          ),
        });
      })
      .catch(() => {
        setStreamingConfig({
          mode: 'periodic',
          autoAttachScrcpy: true,
          autoAttachScrcpyOnRelayOnline: true,
        });
      });
  }, []);
  const {
    devices,
    tasks,
    wsConnected,
    error,
    logs,
    modes,
    wifiDenseposeUrl,
    wsSend,
    handleToggleMode,
    handleRestart,
  } = useDeviceFarm();

  const activeDevices = devices.filter(
    (d) => d.state && !['DISCONNECTED', 'DEAD'].includes(d.state.toUpperCase())
  );

  const [pageIndex, setPageIndex] = useState(0);
  const pageCount = Math.max(1, Math.ceil(activeDevices.length / GRID_PAGE_SIZE));

  useEffect(() => {
    setPageIndex((prev) => Math.min(prev, pageCount - 1));
  }, [pageCount]);

  const pageDevices = useMemo(() => {
    const start = pageIndex * GRID_PAGE_SIZE;
    return activeDevices.slice(start, start + GRID_PAGE_SIZE);
  }, [activeDevices, pageIndex]);

  return (
    <div className='min-h-screen bg-background text-foreground'>
      <DeviceFarmHeader
        total={devices.length}
        tasks={(Array.isArray(tasks) ? tasks : []).filter((t) =>
          ['PENDING', 'RUNNING', 'REQUEUED'].includes(t.status)
        ).length}
        wsConnected={wsConnected}
        wifiDenseposeUrl={wifiDenseposeUrl}
      />

      <main className='mx-auto flex max-w-7xl flex-col gap-4 px-4 pb-8 pt-4'>
        {error && (
          <div className='rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive'>
            <div className='font-medium'>{t('backendErrorTitle')}</div>
            <div className='text-xs opacity-80'>{t('backendErrorHint')}</div>
            <pre className='mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px]'>{error}</pre>
          </div>
        )}

        {activeDevices.length === 0 ? (
          <div className='flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-20 text-center'>
            <Smartphone className='mb-4 size-12 text-muted-foreground' />
            <p className='mb-1 text-sm font-medium text-foreground'>{t('noConnectedDevices')}</p>
            <p className='mb-5 text-xs text-muted-foreground'>{t('noConnectedDevicesHint')}</p>
            <div className='flex flex-wrap items-center justify-center gap-2'>
              {/* <Button size='sm' onClick={() => setConnectDialogOpen(true)}>
                <QrCode size={14} className='mr-1.5' />
                {t('connectDevice')}
              </Button> */}
              <Button asChild size='sm' variant='outline'>
                <Link href={ROUTES.DEVICES.MANAGE}>
                  <Plus size={14} className='mr-1.5' />
                  {t('addDevice')}
                </Link>
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <p className='text-xs text-muted-foreground'>
                {t('gridPageSummary', {
                  page: pageIndex + 1,
                  pages: pageCount,
                  shown: pageDevices.length,
                  total: activeDevices.length,
                })}
              </p>
              {pageCount > 1 && (
                <Pagination className='mx-0 w-auto justify-end'>
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
                          pageIndex >= pageCount - 1 && 'pointer-events-none opacity-50'
                        )}
                      />
                    </PaginationItem>
                  </PaginationContent>
                </Pagination>
              )}
            </div>
            <section className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4'>
              {pageDevices.map((device) => (
                <DeviceTilePreview
                  key={device.serial}
                  device={device}
                  serverAllowPreviewMjpeg={serverAllowPreviewMjpeg}
                  streamingConfig={streamingConfig}
                />
              ))}
            </section>
          </>
        )}
      </main>
      <ConnectDeviceDialog
        open={connectDialogOpen}
        onOpenChange={setConnectDialogOpen}
        liveCount={devices.length}
      />
    </div>
  );
}
