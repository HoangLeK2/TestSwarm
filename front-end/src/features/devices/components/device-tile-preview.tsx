'use client';

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import Link from 'next/link';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { ROUTES } from '@/config/routes';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  DeviceAndroidFrame,
  mockupOuterHeightPx
} from './device-android-frame';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';
import { DeviceStepMonitorButton } from './device-step-monitor';
import { Badge } from '@/components/ui/badge';
import { useTabNetworkActive } from '../hooks/use-tab-network-active';
import { isVisibleDeviceFarmActiveDevice } from '../lib/device-farm-visible-devices';
import {
  acquireSnapshotPreviewWarmup,
  type SnapshotPreviewWarmupHandle
} from '../services/snapshot-preview-warmup';
import { useH264Video } from '../hooks/use-h264-canvas';
import { requestIdr } from '../services/ws';
import { deviceFarmMediaBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';

/** Lazy by default so multiple dashboard tabs do not exhaust browser stream connections. */
const GRID_PREVIEW_EAGER =
  (process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PREVIEW_EAGER ?? '0').trim() !==
  '0';
const GRID_PREVIEW_H264 =
  (process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PREVIEW_H264 ?? '1').trim() !==
  '0';
const DASHBOARD_PREVIEW_REFRESH_MS = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_DASHBOARD_PREVIEW_MS ?? 1_000
  );
  if (!Number.isFinite(raw)) return 1_000;
  return Math.max(500, Math.min(5_000, Math.round(raw)));
})();
const DASHBOARD_PREVIEW_MAX_AGE_MS = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_DASHBOARD_PREVIEW_MAX_AGE_MS ??
      DASHBOARD_PREVIEW_REFRESH_MS
  );
  if (!Number.isFinite(raw)) return DASHBOARD_PREVIEW_REFRESH_MS;
  return Math.max(500, Math.min(10_000, Math.round(raw)));
})();

interface DeviceTilePreviewProps {
  device: Device;
  onOpenSteps?: (serial: string) => void;
}

function DeviceTilePreviewInner({
  device,
  onOpenSteps
}: DeviceTilePreviewProps) {
  const t = useTranslations('devicesFarm');
  const id = serialToId(device.serial);
  const isActive = isVisibleDeviceFarmActiveDevice(device);

  const previewZoneRef = useRef<HTMLDivElement>(null);
  const previewCanvasRef = useRef<HTMLCanvasElement>(null);
  const previewWarmupRef = useRef<SnapshotPreviewWarmupHandle | null>(null);
  const [inView, setInView] = useState(false);
  const [lazyLoadStream, setLazyLoadStream] = useState(false);

  useLayoutEffect(() => {
    if (GRID_PREVIEW_EAGER) return;
    const el = previewZoneRef.current;
    if (!el) return;
    const margin = 140;
    const sync = () => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight;
      setInView(r.bottom > -margin && r.top < vh + margin);
    };
    sync();
    window.addEventListener('scroll', sync, { passive: true, capture: true });
    window.addEventListener('resize', sync);
    window.addEventListener('focus', sync);
    window.addEventListener('pageshow', sync);
    document.addEventListener('visibilitychange', sync);
    const io =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(() => sync(), {
            root: null,
            rootMargin: `${margin}px`,
            threshold: 0.04
          });
    io?.observe(el);
    return () => {
      io?.disconnect();
      window.removeEventListener('scroll', sync, { capture: true });
      window.removeEventListener('resize', sync);
      window.removeEventListener('focus', sync);
      window.removeEventListener('pageshow', sync);
      document.removeEventListener('visibilitychange', sync);
    };
  }, []);

  const tabActive = useTabNetworkActive();
  const [hasFrame, setHasFrame] = useState(false);
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [displayedPreviewUrl, setDisplayedPreviewUrl] = useState<string | null>(
    null
  );
  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);

  useEffect(() => {
    if (GRID_PREVIEW_EAGER) return;
    if (!inView) {
      const t = window.setTimeout(() => setLazyLoadStream(false), 700);
      return () => window.clearTimeout(t);
    }
    setLazyLoadStream(true);
    return undefined;
  }, [inView]);

  const loadStream =
    tabActive && (GRID_PREVIEW_EAGER ? isActive : lazyLoadStream);

  const previewUrl = useMemo(() => {
    if (GRID_PREVIEW_H264) return null;
    if (!tabActive) return null;
    if (!isActive || !loadStream) return null;
    const base = `${deviceFarmMediaBase}/screenshot/${encodeURIComponent(device.serial)}?_r=${previewAttempt}&max_age_ms=${DASHBOARD_PREVIEW_MAX_AGE_MS}`;
    const token = tokenStorage.getAuthToken();
    return token ? `${base}&token=${encodeURIComponent(token)}` : base;
  }, [device.serial, isActive, loadStream, previewAttempt, tabActive]);

  const showPreviewImg = Boolean(displayedPreviewUrl);

  /** Compact grid preview — readable enough for scanning without dominating the dashboard. */
  const previewMockupScreenWidth = 198;
  const previewMockupHeightPx = useMemo(
    () => mockupOuterHeightPx(previewMockupScreenWidth),
    [previewMockupScreenWidth]
  );
  const tileWidthPx = previewMockupScreenWidth + 90;

  const isUnresponsive =
    isActive && loadStream && !hasFrame && loadingElapsedSec >= 12;

  useEffect(() => {
    setHasFrame(false);
    setDisplayedPreviewUrl(null);
    setPreviewAttempt(0);
  }, [device.serial]);

  useH264Video(
    GRID_PREVIEW_H264 && tabActive && isActive && loadStream
      ? device.serial
      : '',
    previewCanvasRef,
    {
      notifyStallWithVisibleFrame: true,
      onFrame: useCallback(() => {
        setHasFrame(true);
      }, [])
    }
  );

  useEffect(() => {
    if (!GRID_PREVIEW_H264) return;
    if (!isActive || !loadStream || !tabActive) {
      previewWarmupRef.current?.release();
      previewWarmupRef.current = null;
      return;
    }

    const handle = acquireSnapshotPreviewWarmup(device.serial);
    previewWarmupRef.current = handle;
    let cancelled = false;
    handle?.attached.then((attached) => {
      if (!cancelled && attached) {
        requestIdr(device.serial, 0);
      }
    });
    return () => {
      cancelled = true;
      handle?.release();
      if (previewWarmupRef.current === handle) {
        previewWarmupRef.current = null;
      }
    };
  }, [device.serial, isActive, loadStream, tabActive]);

  useEffect(() => {
    if (!previewUrl) return;
    let cancelled = false;
    const image = new Image();
    image.onload = () => {
      if (cancelled) return;
      setDisplayedPreviewUrl(previewUrl);
      setHasFrame(true);
    };
    image.src = previewUrl;
    return () => {
      cancelled = true;
      image.onload = null;
    };
  }, [previewUrl]);

  useEffect(() => {
    if (GRID_PREVIEW_H264) return;
    if (!isActive || !loadStream) return;
    const timer = window.setInterval(() => {
      setPreviewAttempt((n) => n + 1);
    }, DASHBOARD_PREVIEW_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [isActive, loadStream]);

  useEffect(() => {
    if (GRID_PREVIEW_H264) return;
    if (!isActive || !loadStream) {
      previewWarmupRef.current?.release();
      previewWarmupRef.current = null;
      return;
    }
    if (loadingElapsedSec < 2 || previewWarmupRef.current) return;
    const handle = acquireSnapshotPreviewWarmup(device.serial);
    previewWarmupRef.current = handle;
    handle?.attached.then((ok) => {
      if (!ok && previewWarmupRef.current === handle) {
        previewWarmupRef.current = null;
      }
    });
  }, [device.serial, isActive, loadingElapsedSec, loadStream]);

  useEffect(() => {
    return () => {
      previewWarmupRef.current?.release();
      previewWarmupRef.current = null;
    };
  }, [device.serial]);

  useEffect(() => {
    if (!isActive || !loadStream || hasFrame) {
      setLoadingElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setLoadingElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => window.clearInterval(timer);
  }, [device.serial, hasFrame, isActive, loadStream]);

  return (
    <Card
      id={`tile-${id}`}
      data-serial={device.serial}
      className='flex h-full max-w-full flex-col overflow-hidden rounded-xl border border-border/70 bg-card/70 shadow-sm backdrop-blur-sm transition-colors hover:border-primary/35'
      style={{ width: tileWidthPx }}
    >
      <CardContent className='flex flex-1 flex-col p-0'>
        <div className='border-b border-border/60 px-3 py-3'>
          <div className='flex min-w-0 items-start justify-between gap-2'>
            <div className='min-w-0'>
              <div className='flex min-w-0 items-center gap-1.5'>
                <p className='truncate text-sm font-semibold leading-5 text-foreground'>
                  {device.brand} {device.model}
                </p>
                {!isActive ? (
                  <Badge
                    variant='outline'
                    className='shrink-0 border-red-500/30 bg-red-500/10 text-[10px] text-red-700 dark:text-red-300'
                  >
                    {t('badgeOffline')}
                  </Badge>
                ) : isUnresponsive ? (
                  <Badge
                    variant='outline'
                    className='shrink-0 border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-800 dark:text-amber-200'
                  >
                    {t('badgeUnresponsive')}
                  </Badge>
                ) : null}
              </div>
              <p className='mt-0.5 truncate font-mono text-[11px] leading-4 text-muted-foreground'>
                {device.serial}
              </p>
            </div>
          </div>

          <div className='mt-2 flex min-w-0 items-center gap-1.5'>
            {onOpenSteps ? (
              <DeviceStepMonitorButton
                serial={device.serial}
                isBusy={device.state?.toUpperCase() === 'BUSY'}
                onOpen={onOpenSteps}
              />
            ) : null}
            {isActive ? (
              <Button
                asChild
                size='sm'
                className='h-8 min-w-0 flex-1 px-3 text-xs font-semibold'
              >
                <Link
                  href={ROUTES.DEVICES.CONTROL_RECORD_WITH_SERIAL(
                    device.serial
                  )}
                >
                  {t('controlDevice')}
                </Link>
              </Button>
            ) : (
              <Button
                size='sm'
                className='h-8 min-w-0 flex-1 px-3 text-xs font-semibold'
                disabled
              >
                {t('controlDevice')}
              </Button>
            )}
          </div>
        </div>

        <div className='flex flex-1 flex-col items-center bg-background/25'>
          <div
            className='flex w-full shrink-0 justify-center px-3 py-4'
            style={{
              minHeight: previewMockupHeightPx + 32
            }}
          >
            <DeviceAndroidFrame
              screenWidth={previewMockupScreenWidth}
              deviceWidth={device.screen_width}
              deviceHeight={device.screen_height}
              className='h-full shrink-0'
            >
              <div
                ref={previewZoneRef}
                className='relative h-full min-h-0 w-full overflow-hidden bg-zinc-950'
              >
                {showPreviewImg && (
                  // eslint-disable-next-line @next/next/no-img-element -- dashboard preview uses cached screenshot polling.
                  <img
                    src={displayedPreviewUrl!}
                    alt=''
                    role='presentation'
                    decoding='async'
                    className={cn(
                      'pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-500',
                      hasFrame && !GRID_PREVIEW_H264
                        ? 'opacity-100'
                        : 'opacity-0'
                    )}
                    draggable={false}
                  />
                )}
                {GRID_PREVIEW_H264 && (
                  <canvas
                    ref={previewCanvasRef}
                    aria-hidden='true'
                    className={cn(
                      'pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-500',
                      hasFrame ? 'opacity-100' : 'opacity-0'
                    )}
                  />
                )}
                {!isActive ? (
                  <div className='absolute inset-0 z-10 flex items-center justify-center bg-zinc-950 px-2 text-center text-[11px] text-muted-foreground'>
                    {t('deviceInactive')}
                  </div>
                ) : !loadStream ? (
                  <div className='absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-gradient-to-b from-zinc-800 to-zinc-950 px-2 text-center'>
                    <div className='h-4 w-4 animate-spin rounded-full border-2 border-zinc-400/70 border-t-transparent' />
                    <p className='text-[10px] text-muted-foreground'>
                      {t('previewScrollToLoad')}
                    </p>
                  </div>
                ) : (
                  <div
                    className={cn(
                      'absolute inset-0 z-10 flex flex-col items-center justify-center bg-gradient-to-b from-zinc-800 to-zinc-950 transition-opacity duration-500',
                      hasFrame ? 'pointer-events-none opacity-0' : 'opacity-100'
                    )}
                    aria-live='polite'
                    aria-hidden={hasFrame}
                  >
                    <span className='sr-only'>
                      {isUnresponsive
                        ? t('streamUnresponsive')
                        : t('streamWaitingFirstFrame')}
                    </span>
                    {!isUnresponsive ? (
                      <>
                        <div className='h-5 w-5 animate-spin rounded-full border-2 border-zinc-400/80 border-t-transparent' />
                        <p className='mt-2 text-[10px] text-muted-foreground'>
                          {t('streamWaitingFirstFrame')}
                        </p>
                      </>
                    ) : (
                      <p className='px-2 text-center text-[10px] text-amber-200/90'>
                        {t('streamUnresponsive')}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </DeviceAndroidFrame>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function tilePreviewPropsEqual(
  prev: DeviceTilePreviewProps,
  next: DeviceTilePreviewProps
) {
  if (prev.device.serial !== next.device.serial) return false;
  if (prev.onOpenSteps !== next.onOpenSteps) return false;
  const pd = prev.device;
  const nd = next.device;
  return (
    pd.state === nd.state &&
    pd.brand === nd.brand &&
    pd.model === nd.model &&
    pd.battery === nd.battery &&
    pd.scenario_active === nd.scenario_active &&
    pd.screen_width === nd.screen_width &&
    pd.screen_height === nd.screen_height
  );
}

export const DeviceTilePreview = memo(
  DeviceTilePreviewInner,
  tilePreviewPropsEqual
);
