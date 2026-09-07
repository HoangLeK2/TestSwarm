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
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { TablePaginationControls } from '@/components/ui/table/data-table-pagination';
import { CoreEmptyState } from '@/components/core-empty-state';
import { RefreshCw, Search, Smartphone, X } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { isVisibleDeviceFarmActiveDevice } from '../lib/device-farm-visible-devices';
import {
  ALL_RUNS,
  filterDeviceFarmDevices,
  listDeviceFarmRuns,
  type DeviceFarmActivityFilter
} from '../lib/device-farm-filter';
import {
  hasMediaPlanePreview,
  isGridWebRtcPreviewEnabled
} from '../lib/device-tile-preview-policy';
import {
  DEVICE_GRID_ESTIMATED_ROW_HEIGHT_PX,
  DEVICE_GRID_GAP_PX,
  DEVICE_GRID_TILE_WIDTH_PX,
  getDeviceGridColumnCount,
  getDeviceGridRenderMode,
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

  const activeDeviceCount = useMemo(
    () =>
      devices.filter(
        (device) =>
          isVisibleDeviceFarmActiveDevice(device) ||
          hasMediaPlanePreview(device)
      ).length,
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

  const [query, setQuery] = useState('');
  const [activity, setActivity] = useState<DeviceFarmActivityFilter>('all');
  const [runKey, setRunKey] = useState<string>(ALL_RUNS);
  const runs = useMemo(() => listDeviceFarmRuns(devices), [devices]);
  const filteredDevices = useMemo(
    () => filterDeviceFarmDevices(devices, { query, activity, runKey }),
    [devices, query, activity, runKey]
  );
  const isFiltered =
    query.trim().length > 0 || activity !== 'all' || runKey !== ALL_RUNS;
  const clearFilters = useCallback(() => {
    setQuery('');
    setActivity('all');
    setRunKey(ALL_RUNS);
  }, []);

  // A run that ends while it is the selected filter would otherwise leave the
  // grid permanently empty with no option in the list to explain why.
  useEffect(() => {
    if (runKey === ALL_RUNS) return;
    if (!runs.some((run) => run.key === runKey)) setRunKey(ALL_RUNS);
  }, [runKey, runs]);

  const isInitialLoading =
    requestStatus === 'idle' ||
    (requestStatus === 'loading' && lastUpdatedAt === null);
  const isInitialError = requestStatus === 'error' && lastUpdatedAt === null;
  const renderMode = getDeviceGridRenderMode({
    isInitialError,
    isInitialLoading,
    deviceCount: devices.length,
    filteredCount: filteredDevices.length
  });

  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_GRID_PAGE_SIZE);
  const pageCount = Math.max(1, Math.ceil(filteredDevices.length / pageSize));

  useEffect(() => {
    setPageIndex((prev) => Math.min(prev, pageCount - 1));
  }, [pageCount]);

  useEffect(() => {
    setPageIndex(0);
  }, [query, activity, runKey]);

  const pageDevices = useMemo(() => {
    const start = pageIndex * pageSize;
    return filteredDevices.slice(start, start + pageSize);
  }, [filteredDevices, pageIndex, pageSize]);

  // Callback ref, not useRef: measurement has to be wired the moment the grid
  // node attaches. Keying it off device counts instead looked equivalent and
  // was not — a WebSocket status frame can raise the count to 1 while the page
  // is still on the loading branch, so by the time the grid actually mounted
  // the deps had not changed, the effect never re-ran, scrollElement stayed
  // null, and the virtualizer sat disabled behind a header reading "1/1".
  const [gridElement, setGridElement] = useState<HTMLElement | null>(null);
  const virtualGridRef = useCallback(
    (node: HTMLElement | null) => setGridElement(node),
    []
  );
  const [scrollElement, setScrollElement] = useState<HTMLElement | null>(null);
  const [gridWidth, setGridWidth] = useState(0);
  const [scrollMargin, setScrollMargin] = useState(0);
  const syncGeometryRef = useRef<() => void>(() => {});

  useLayoutEffect(() => {
    if (!gridElement) {
      setScrollElement(null);
      return;
    }

    const scroller = findScrollableParent(gridElement);
    setScrollElement(scroller);

    const syncGeometry = () => {
      const gridRect = gridElement.getBoundingClientRect();
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

    syncGeometryRef.current = syncGeometry;
    syncGeometry();
    const resizeObserver = new ResizeObserver(syncGeometry);
    resizeObserver.observe(gridElement);
    resizeObserver.observe(scroller);
    window.addEventListener('resize', syncGeometry);
    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', syncGeometry);
      syncGeometryRef.current = () => {};
    };
  }, [gridElement]);

  // Siblings appearing above the grid (for example the refresh-error banner) move
  // it without resizing its box, and ResizeObserver does not fire on a move.
  useLayoutEffect(() => {
    syncGeometryRef.current();
  }, [error, isInitialLoading, filteredDevices.length, pageIndex, pageSize]);

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
            {devices.length > activeDeviceCount ? (
              <Badge variant='secondary' className='text-[10px]'>
                {tHeader('devicesRegistered', { count: devices.length })}
              </Badge>
            ) : null}
          </div>
        </div>
      </div>

      <div className='flex flex-wrap items-center gap-2'>
        <div className='relative min-w-[220px] flex-1 md:max-w-sm'>
          <Search className='pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground' />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('filters.searchPlaceholder')}
            aria-label={t('filters.searchPlaceholder')}
            className='pl-8'
          />
        </div>
        <Select
          value={activity}
          onValueChange={(value) =>
            setActivity(value as DeviceFarmActivityFilter)
          }
        >
          <SelectTrigger className='w-[190px]'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='all'>{t('filters.allStatuses')}</SelectItem>
            <SelectItem value='idle'>{t('filters.activityIdle')}</SelectItem>
            <SelectItem value='running'>
              {t('filters.activityRunning')}
            </SelectItem>
            <SelectItem value='manual'>
              {t('filters.activityManual')}
            </SelectItem>
            <SelectItem value='unavailable'>
              {t('filters.activityUnavailable')}
            </SelectItem>
          </SelectContent>
        </Select>
        {runs.length > 0 ? (
          <Select value={runKey} onValueChange={setRunKey}>
            <SelectTrigger className='w-[220px]'>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_RUNS}>{t('filters.allRuns')}</SelectItem>
              {runs.map((run) => (
                <SelectItem key={run.key} value={run.key}>
                  {run.label} ({run.count})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
        {isFiltered ? (
          <>
            <Button variant='ghost' size='sm' onClick={clearFilters}>
              <X className='mr-1 size-4' />
              {t('filters.clear')}
            </Button>
          </>
        ) : null}
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

      {renderMode === 'error' ? (
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
      ) : renderMode === 'loading' ? (
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
      ) : renderMode === 'empty-fleet' ? (
        <CoreEmptyState
          icon={Smartphone}
          title={tEmpty('fleet.title')}
          description={tEmpty('fleet.description')}
          trackingKey='fleet-empty'
          cta={{
            label: tEmpty('fleet.ctaPair'),
            href: ROUTES.DEVICES.MANAGE
          }}
          secondaryCta={{
            label: tEmpty('fleet.ctaRelay'),
            href: ROUTES.RELAY_AGENTS.ROOT
          }}
        />
      ) : renderMode === 'empty-filter' ? (
        <div className='rounded-md border border-border/60 px-4 py-10 text-center'>
          <div className='text-sm font-medium'>{t('filters.emptyTitle')}</div>
          <div className='mt-1 text-xs text-muted-foreground'>
            {t('filters.emptyHint')}
          </div>
          <Button
            className='mt-4'
            variant='outline'
            size='sm'
            onClick={clearFilters}
          >
            {t('filters.clear')}
          </Button>
        </div>
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
              total={filteredDevices.length}
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
