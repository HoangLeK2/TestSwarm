'use client';

import {
  memo,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import Link from 'next/link';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { deviceFarmMediaBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';
import { ROUTES } from '@/config/routes';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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

/** Lazy by default so multiple dashboard tabs do not exhaust browser stream connections. */
const GRID_PREVIEW_EAGER =
  (process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PREVIEW_EAGER ?? '0').trim() !==
  '0';
const DASHBOARD_PREVIEW_REFRESH_MS = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_DASHBOARD_PREVIEW_MS ?? 1_000
  );
  if (!Number.isFinite(raw)) return 1_000;
  return Math.max(500, Math.min(5_000, Math.round(raw)));
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
    if (typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(
      (entries) => setInView(Boolean(entries[0]?.isIntersecting)),
      { root: null, rootMargin: `${margin}px`, threshold: 0.04 }
    );
    io.observe(el);
    return () => io.disconnect();
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

  /** Compact grid preview — readable enough for scanning without dominating the dashboard. */
  const previewMockupScreenWidth = 216;
  const previewMockupHeightPx = useMemo(
    () => mockupOuterHeightPx(previewMockupScreenWidth),
    [previewMockupScreenWidth]
  );

  const previewUrl = useMemo(() => {
    if (!tabActive) return null;
    if (!isActive || !loadStream) return null;
    const base = `${deviceFarmMediaBase}/screenshot/${encodeURIComponent(device.serial)}?_r=${previewAttempt}`;
    const token = tokenStorage.getAuthToken();
    return token ? `${base}&token=${encodeURIComponent(token)}` : base;
  }, [device.serial, isActive, loadStream, previewAttempt, tabActive]);

  const showPreviewImg = Boolean(displayedPreviewUrl);

  const isUnresponsive =
    isActive && loadStream && !hasFrame && loadingElapsedSec >= 12;

  useEffect(() => {
    setHasFrame(false);
    setDisplayedPreviewUrl(null);
    setPreviewAttempt(0);
  }, [device.serial]);

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
    if (!isActive || !loadStream) return;
    const timer = window.setInterval(() => {
      setPreviewAttempt((n) => n + 1);
    }, DASHBOARD_PREVIEW_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [isActive, loadStream]);

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
      className='flex h-full flex-col overflow-hidden border-border bg-card shadow-sm'
    >
      <CardHeader className='relative z-10 border-b border-border/60 px-3 py-2.5'>
        <div className='flex items-center justify-between gap-2'>
          <div className='flex min-w-0 flex-col gap-0.5'>
            <CardTitle className='truncate text-xs font-medium text-foreground'>
              {device.brand} {device.model}
            </CardTitle>
            <span className='font-mono text-[10px] text-muted-foreground'>
              {device.serial}
            </span>
          </div>
          <div className='relative z-10 flex shrink-0 items-center gap-1.5'>
            {!isActive ? (
              <Badge
                variant='outline'
                className='border-red-500/30 bg-red-500/10 text-[10px] text-red-700 dark:text-red-300'
              >
                {t('badgeOffline')}
              </Badge>
            ) : isUnresponsive ? (
              <Badge
                variant='outline'
                className='border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-800 dark:text-amber-200'
              >
                {t('badgeUnresponsive')}
              </Badge>
            ) : null}
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
                className='h-7 shrink-0 px-2.5 text-[11px]'
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
                className='h-7 shrink-0 px-2.5 text-[11px]'
                disabled
              >
                {t('controlDevice')}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className='flex flex-1 flex-col gap-2 px-2.5 pb-2.5 pt-2.5'>
        <div className='flex flex-col items-center gap-2'>
          <div
            className='flex w-full shrink-0 justify-center'
            style={{
              height: previewMockupHeightPx,
              minHeight: previewMockupHeightPx
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
                      hasFrame ? 'opacity-100' : 'opacity-0'
                    )}
                    draggable={false}
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
