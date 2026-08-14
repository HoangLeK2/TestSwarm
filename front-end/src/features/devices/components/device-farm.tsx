'use client';

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useQuery } from '@tanstack/react-query';
import { ROUTES } from '@/config/routes';
import { DeviceTilePreview } from './device-tile-preview';
import { ConnectDeviceDialog } from './connect-device-dialog';
import { useDeviceFarm } from '../hooks/use-device-farm';
import { fetchConfig } from '../services/api';
import type { DeviceScreenTransport } from './device-screen';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { TablePaginationControls } from '@/components/ui/table/data-table-pagination';
import { CoreEmptyState } from '@/components/core-empty-state';
import { RefreshCw, Smartphone } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { isVisibleDeviceFarmActiveDevice } from '../lib/device-farm-visible-devices';
import {
  hasMediaPlanePreview,
  isGridWebRtcPreviewEnabled
} from '../lib/device-tile-preview-policy';
import {
  DEVICE_GRID_ESTIMATED_ROW_HEIGHT_PX,
  DEVICE_GRID_GAP_PX,
  DEVICE_GRID_TILE_WIDTH_PX,
  getDeviceGridColumnCount,
  getDeviceGridRowBounds,
  getDeviceGridRowCount
} from '../lib/device-farm-virtual-grid';

const DEFAULT_GRID_PAGE_SIZE = (() => {
  const raw = Number(process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PAGE_SIZE ?? 10);
  if (!Number.isFinite(raw)) return 10;
  return Math.max(10, Math.min(50, Math.round(raw)));
})();
const GRID_WEBRTC_PREVIEW = isGridWebRtcPreviewEnabled(
  process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_WEBRTC_PREVIEW
);

function findScrollableParent(element: HTMLElement): HTMLElement {
  let current = element.parentElement;
  while (current) {
    const overflowY = window.getComputedStyle(current).overflowY;
    if (overflowY === 'auto' || overflowY === 'scroll') return current;
    current = current.parentElement;
  }
  return document.documentElement;
}

export function DeviceFarm() {
  const t = useTranslations('devicesFarm');
  const tEmpty = useTranslations('coreEmptyState');
  const tHeader = useTranslations('devicesFarm.header');
  const [connectDialogOpen, setConnectDialogOpen] = useState(false);
  const { data: appConfig } = useQuery({
    queryKey: ['device-farm', 'config'],
    queryFn: fetchConfig,
    staleTime: 60_000
  });
  const gridStreamTransport = useMemo<DeviceScreenTransport>(
    () =>
      GRID_WEBRTC_PREVIEW && appConfig?.webrtc_enabled ? 'webrtc' : 'auto',
    [appConfig?.webrtc_enabled]
  );

  const {
    devices,
    wsConnected,
    error,
    requestStatus,
    lastUpdatedAt,
    refreshDevices
  } = useDeviceFarm({
    liveRefreshMs: 15_000,
    loadTasks: false,
    loadRegisteredDevices: false,
    refreshRegisteredOnFocus: false,
    liveSnapshotAuthoritative: true
  });

  const activeDevices = useMemo(
    () =>
      devices.filter(
        (device) =>
          isVisibleDeviceFarmActiveDevice(device) ||
          hasMediaPlanePreview(device)
      ),
    [devices]
  );
  const readyDeviceCount = useMemo(
    () =>
      devices.filter((device) =>
        device.health
          ? device.health.command.status === 'ready'
          : isVisibleDeviceFarmActiveDevice(device) &&
            device.state?.toUpperCase() !== 'BUSY'
      ).length,
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

  const virtualGridRef = useRef<HTMLElement>(null);
  const [scrollElement, setScrollElement] = useState<HTMLElement | null>(null);
  const [gridWidth, setGridWidth] = useState(0);
  const [scrollMargin, setScrollMargin] = useState(0);

  useLayoutEffect(() => {
    const grid = virtualGridRef.current;
    if (!grid) return;

    const scroller = findScrollableParent(grid);
    setScrollElement(scroller);

    const syncGeometry = () => {
      const gridRect = grid.getBoundingClientRect();
      const scrollerRect = scroller.getBoundingClientRect();
      const nextWidth = Math.max(0, gridRect.width);
      const nextScrollMargin = Math.max(
        0,
        gridRect.top - scrollerRect.top + scroller.scrollTop
      );
      setGridWidth((current) =>
        Math.abs(current - nextWidth) < 0.5 ? current : nextWidth
      );
      setScrollMargin((current) =>
        Math.abs(current - nextScrollMargin) < 0.5 ? current : nextScrollMargin
      );
    };

    syncGeometry();
    const resizeObserver = new ResizeObserver(syncGeometry);
    resizeObserver.observe(grid);
    resizeObserver.observe(scroller);
    window.addEventListener('resize', syncGeometry);
    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', syncGeometry);
    };
  }, [error, pageDevices.length]);

  const columnCount = useMemo(
    () => getDeviceGridColumnCount(gridWidth, pageDevices.length),
    [gridWidth, pageDevices.length]
  );
  const rowCount = getDeviceGridRowCount(pageDevices.length, columnCount);
  const getScrollElement = useCallback(() => scrollElement, [scrollElement]);
  const getVirtualRowKey = useCallback(
    (rowIndex: number) => {
      const firstDevice = pageDevices[rowIndex * columnCount];
      return `${columnCount}:${firstDevice?.serial ?? rowIndex}`;
    },
    [columnCount, pageDevices]
  );
  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement,
    estimateSize: () => DEVICE_GRID_ESTIMATED_ROW_HEIGHT_PX,
    getItemKey: getVirtualRowKey,
    gap: DEVICE_GRID_GAP_PX,
    overscan: 1,
    scrollMargin,
    enabled: scrollElement !== null && rowCount > 0,
    useFlushSync: false
  });
  const isInitialLoading =
    requestStatus === 'idle' ||
    (requestStatus === 'loading' && lastUpdatedAt === null);
  const isInitialError = requestStatus === 'error' && lastUpdatedAt === null;

  const lastUpdatedLabel = lastUpdatedAt
    ? new Intl.DateTimeFormat(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      }).format(new Date(lastUpdatedAt))
    : null;

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div>
          <h1 className='text-xl font-semibold'>{t('pageTitle')}</h1>
          <p className='mt-1 text-xs text-muted-foreground'>
            {lastUpdatedLabel
              ? t('lastUpdated', { time: lastUpdatedLabel })
              : t('waitingForData')}
          </p>
        </div>
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
              {lastUpdatedAt
                ? tHeader('devicesReady', { count: readyDeviceCount })
                : isInitialError
                  ? tHeader('devicesReadyUnavailable')
                  : tHeader('devicesReadyLoading')}
            </Badge>
            {devices.length > activeDevices.length ? (
              <Badge variant='secondary' className='text-[10px]'>
                {tHeader('devicesRegistered', { count: devices.length })}
              </Badge>
            ) : null}
          </div>
        </div>
      </div>

      {error && lastUpdatedAt && (
        <div className='flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-sm text-amber-800 dark:text-amber-200'>
          <div>
            <div className='font-medium'>{t('refreshErrorTitle')}</div>
            <div className='text-xs opacity-80'>{t('refreshErrorHint')}</div>
            {error ? (
              <p className='mt-1 font-mono text-[11px]'>{error}</p>
            ) : null}
          </div>
          <Button
            variant='outline'
            size='sm'
            onClick={() => void refreshDevices()}
          >
            <RefreshCw className='mr-2 size-4' />
            {t('retry')}
          </Button>
        </div>
      )}

      {isInitialError ? (
        <div className='rounded-md border border-destructive/40 bg-destructive/5 px-4 py-8 text-center text-sm text-destructive'>
          <div className='font-medium'>{t('backendErrorTitle')}</div>
          <div className='mt-1 text-xs opacity-80'>{t('loadErrorHint')}</div>
          {error ? <p className='mt-2 font-mono text-[11px]'>{error}</p> : null}
          <Button
            className='mt-4'
            variant='outline'
            size='sm'
            onClick={() => void refreshDevices()}
          >
            <RefreshCw className='mr-2 size-4' />
            {t('retry')}
          </Button>
        </div>
      ) : isInitialLoading ? (
        <div
          className='grid grid-cols-[repeat(auto-fit,minmax(240px,320px))] gap-4'
          aria-label={t('loadingDevices')}
        >
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className='h-[520px] animate-pulse rounded-lg border bg-muted/30'
            />
          ))}
        </div>
      ) : activeDevices.length === 0 ? (
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
          <section ref={virtualGridRef} className='w-full'>
            <div
              className='relative w-full'
              style={{ height: rowVirtualizer.getTotalSize() }}
            >
              {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                const { start, end } = getDeviceGridRowBounds(
                  virtualRow.index,
                  columnCount,
                  pageDevices.length
                );
                return (
                  <div
                    key={virtualRow.key}
                    ref={rowVirtualizer.measureElement}
                    data-index={virtualRow.index}
                    className='absolute left-0 top-0 grid w-full justify-start gap-4'
                    style={{
                      gridTemplateColumns: `repeat(${end - start}, minmax(0, min(100%, ${DEVICE_GRID_TILE_WIDTH_PX}px)))`,
                      transform: `translateY(${virtualRow.start - scrollMargin}px)`,
                      contain: 'layout paint'
                    }}
                  >
                    {pageDevices.slice(start, end).map((device) => (
                      <DeviceTilePreview
                        key={device.serial}
                        device={device}
                        streamTransport={gridStreamTransport}
                      />
                    ))}
                  </div>
                );
              })}
            </div>
          </section>
          <footer className='border-t border-border/40 pt-4'>
            <TablePaginationControls
              total={activeDevices.length}
              pageIndex={pageIndex}
              pageCount={pageCount}
              pageSize={pageSize}
              pageSizeOptions={[10, 20, 30, 40, 50]}
              onPageIndexChange={setPageIndex}
              onPageSizeChange={(nextPageSize) => {
                setPageSize(nextPageSize);
                setPageIndex(0);
              }}
            />
          </footer>
        </>
      )}

      <ConnectDeviceDialog
        open={connectDialogOpen}
        onOpenChange={setConnectDialogOpen}
        liveCount={devices.length}
      />
    </div>
  );
}
