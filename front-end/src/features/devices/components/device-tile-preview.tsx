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
import type { DeviceScreenTransport } from './device-screen';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';
import { DeviceStepMonitorButton } from './device-step-monitor';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useTabNetworkActive } from '../hooks/use-tab-network-active';
import { isVisibleDeviceFarmActiveDevice } from '../lib/device-farm-visible-devices';
import { DEVICE_GRID_TILE_WIDTH_PX } from '../lib/device-farm-virtual-grid';
import {
  acquireSnapshotPreviewWarmup,
  type SnapshotPreviewWarmupHandle
} from '../services/snapshot-preview-warmup';
import type { ScrcpyAttachOptions } from '../services/scrcpy-stream';
import { useH264Video } from '../hooks/use-h264-canvas';
import { useWebRtcVideo } from '../hooks/use-webrtc-video';
import { requestIdr } from '../services/ws';
import { deviceFarmMediaBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';
import {
  isDevicePreviewStreamEligible,
  isGridH264Enabled,
  isPreviewFrameStale,
  nextSnapshotRetryDelayMs,
  selectDeviceTilePreviewMode,
  type WebCodecsSupport
} from '../lib/device-tile-preview-policy';
import {
  deviceDisplayName,
  deviceSecondarySerial
} from '../lib/device-display-name';

/** Lazy by default so multiple dashboard tabs do not exhaust browser stream connections. */
const GRID_PREVIEW_EAGER =
  (process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PREVIEW_EAGER ?? '0').trim() !==
  '0';
const GRID_PREVIEW_H264 = isGridH264Enabled(
  process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PREVIEW_H264
);
const GRID_PREVIEW_VIEWPORT_MARGIN_PX = 0;
const DASHBOARD_PREVIEW_REFRESH_MS = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_DASHBOARD_PREVIEW_MS ?? 2_000
  );
  if (!Number.isFinite(raw)) return 2_000;
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

function dashboardWebRtcInt(
  name: string,
  fallback: number,
  min: number,
  max: number
) {
  const raw = Number(process.env[name] ?? fallback);
  if (!Number.isFinite(raw)) return fallback;
  return Math.max(min, Math.min(max, Math.round(raw)));
}

const DASHBOARD_WEBRTC_PREVIEW_OPTIONS: ScrcpyAttachOptions = {
  enableControl: false,
  profile: 'visible',
  maxFps: dashboardWebRtcInt(
    'NEXT_PUBLIC_DEVICE_FARM_DASHBOARD_WEBRTC_FPS',
    3,
    1,
    8
  ),
  maxWidth: dashboardWebRtcInt(
    'NEXT_PUBLIC_DEVICE_FARM_DASHBOARD_WEBRTC_WIDTH',
    360,
    160,
    540
  ),
  bitrate: dashboardWebRtcInt(
    'NEXT_PUBLIC_DEVICE_FARM_DASHBOARD_WEBRTC_BITRATE',
    260_000,
    80_000,
    600_000
  )
};

interface DeviceTilePreviewProps {
  device: Device;
  onOpenSteps?: (serial: string) => void;
  previewEnabled?: boolean;
  streamTransport?: DeviceScreenTransport;
}

function HealthIndicator({
  label,
  value,
  hint,
  ok
}: {
  label: string;
  value: string;
  hint: string;
  ok: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className='inline-flex h-6 min-w-0 items-center gap-1 rounded border px-1.5 text-[10px]'>
          <span
            className={cn(
              'size-1.5 shrink-0 rounded-full',
              ok ? 'bg-emerald-500' : 'bg-amber-500'
            )}
            aria-hidden
          />
          <span className='truncate'>
            {label}: {value}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent side='bottom' className='max-w-64 text-xs'>
        {hint}
      </TooltipContent>
    </Tooltip>
  );
}

type PreviewWarmupState = 'idle' | 'queued' | 'attaching' | 'live' | 'error';

function PreviewLoadingSurface({
  label,
  showSpinner = true,
  failed = false,
  onRetry,
  retryLabel
}: {
  label: string;
  showSpinner?: boolean;
  failed?: boolean;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div className='absolute inset-0 z-10 overflow-hidden bg-zinc-950'>
      <div className='absolute inset-x-0 top-0 h-10 bg-zinc-900/80' />
      <div className='absolute left-3 right-3 top-14 space-y-3 opacity-70'>
        <div className='h-3 w-1/2 rounded-full bg-zinc-700/80' />
        <div className='h-24 rounded-md bg-zinc-800/80' />
        <div className='grid grid-cols-3 gap-2'>
          <div className='h-7 rounded bg-zinc-800/70' />
          <div className='h-7 rounded bg-zinc-800/70' />
          <div className='h-7 rounded bg-zinc-800/70' />
        </div>
        <div className='h-20 rounded-md bg-zinc-900/90' />
      </div>
      <div className='absolute inset-x-0 bottom-0 h-9 bg-zinc-900/85' />
      <div className='absolute inset-0 flex items-center justify-center px-3 text-center'>
        <div
          className={cn(
            'flex max-w-[82%] items-center gap-2 rounded-full border px-3 py-2 text-[10px] shadow-sm backdrop-blur',
            failed
              ? 'border-amber-400/25 bg-amber-950/45 text-amber-100'
              : 'border-white/10 bg-black/35 text-zinc-200'
          )}
        >
          {showSpinner ? (
            <span
              className='size-3 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent opacity-80'
              aria-hidden
            />
          ) : null}
          <span className='min-w-0 truncate'>{label}</span>
        </div>
      </div>
      {onRetry ? (
        <Button
          type='button'
          variant='secondary'
          size='sm'
          className='absolute bottom-12 left-1/2 h-7 -translate-x-1/2 text-xs'
          onClick={onRetry}
        >
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

function DashboardWebRtcPreview({
  device,
  active,
  frameStale
}: {
  device: Device;
  active: boolean;
  frameStale: boolean;
}) {
  const t = useTranslations('devicesFarm');
  const videoRef = useRef<HTMLVideoElement>(null);
  const retryTimerRef = useRef<number | undefined>(undefined);
  const [hasFrame, setHasFrame] = useState(false);
  const [restartKey, setRestartKey] = useState(0);

  const clearRetryTimer = useCallback(() => {
    if (retryTimerRef.current === undefined) return;
    window.clearTimeout(retryTimerRef.current);
    retryTimerRef.current = undefined;
  }, []);

  const handleFrame = useCallback(() => {
    clearRetryTimer();
    setHasFrame(true);
  }, [clearRetryTimer]);

  const handleError = useCallback(() => {
    setHasFrame(false);
    if (!active || retryTimerRef.current !== undefined) return;
    retryTimerRef.current = window.setTimeout(() => {
      retryTimerRef.current = undefined;
      setRestartKey((value) => value + 1);
    }, 1200);
  }, [active]);

  const retryNow = useCallback(() => {
    clearRetryTimer();
    setHasFrame(false);
    setRestartKey((value) => value + 1);
  }, [clearRetryTimer]);

  const webrtc = useWebRtcVideo(device.serial, videoRef, {
    enabled: active,
    restartKey,
    control: DASHBOARD_WEBRTC_PREVIEW_OPTIONS.enableControl,
    profile: DASHBOARD_WEBRTC_PREVIEW_OPTIONS.profile,
    maxFps: DASHBOARD_WEBRTC_PREVIEW_OPTIONS.maxFps,
    maxWidth: DASHBOARD_WEBRTC_PREVIEW_OPTIONS.maxWidth,
    bitrate: DASHBOARD_WEBRTC_PREVIEW_OPTIONS.bitrate,
    onFrame: handleFrame,
    onError: handleError
  });

  useEffect(() => {
    setHasFrame(false);
    setRestartKey(0);
    clearRetryTimer();
    return clearRetryTimer;
  }, [clearRetryTimer, device.serial]);

  // A frozen <video> keeps its last decoded frame forever — hide it once the
  // server reports the media plane stopped moving.
  const frameVisible = hasFrame && !frameStale;

  return (
    <>
      <video
        ref={videoRef}
        muted
        playsInline
        autoPlay
        className={cn(
          'pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-300',
          frameVisible ? 'opacity-100' : 'opacity-0'
        )}
      />
      <div
        className={cn(
          'absolute inset-0 z-10 transition-opacity duration-300',
          frameVisible ? 'pointer-events-none opacity-0' : 'opacity-100'
        )}
        aria-live='polite'
        aria-hidden={frameVisible}
      >
        {!frameStale && (!webrtc.failed || webrtc.connecting) ? (
          <PreviewLoadingSurface label={t('streamWaitingFirstFrame')} />
        ) : (
          <PreviewLoadingSurface
            label={t('streamUnresponsive')}
            showSpinner={false}
            failed
            onRetry={retryNow}
            retryLabel={t('retry')}
          />
        )}
      </div>
    </>
  );
}

function DeviceTilePreviewInner({
  device,
  onOpenSteps,
  previewEnabled = true,
  streamTransport = 'auto'
}: DeviceTilePreviewProps) {
  const t = useTranslations('devicesFarm');
  const id = serialToId(device.serial);
  const secondarySerial = deviceSecondarySerial(device);
  const isActive = isVisibleDeviceFarmActiveDevice(device);
  const health = device.health;
  const commandReady = health ? health.command.status === 'ready' : isActive;
  // The runtime snapshot can still read READY after the agent dies; health is
  // the server's own verdict, so the offline badge follows it when present.
  const agentOffline = health ? health.agent.status === 'offline' : !isActive;
  const previewStreamEligible = isDevicePreviewStreamEligible(device, isActive);

  const previewZoneRef = useRef<HTMLDivElement>(null);
  const previewCanvasRef = useRef<HTMLCanvasElement>(null);
  const previewWarmupRef = useRef<SnapshotPreviewWarmupHandle | null>(null);
  const snapshotFailureCountRef = useRef(0);
  const [inView, setInView] = useState(false);
  const [lazyLoadStream, setLazyLoadStream] = useState(false);
  const [webCodecsSupport, setWebCodecsSupport] =
    useState<WebCodecsSupport>('unknown');
  const [h264Stalled, setH264Stalled] = useState(false);

  useLayoutEffect(() => {
    if (GRID_PREVIEW_EAGER) return;
    const el = previewZoneRef.current;
    if (!el) return;
    const sync = () => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight;
      setInView(
        r.bottom > -GRID_PREVIEW_VIEWPORT_MARGIN_PX &&
          r.top < vh + GRID_PREVIEW_VIEWPORT_MARGIN_PX
      );
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
            rootMargin: `${GRID_PREVIEW_VIEWPORT_MARGIN_PX}px`,
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
  const [snapshotFailures, setSnapshotFailures] = useState(0);
  const [previewWarmupState, setPreviewWarmupState] =
    useState<PreviewWarmupState>('idle');

  /** The painted frame outlives its source: drop it when the source dies. */
  const frameStale = isPreviewFrameStale({
    streamStatus: health?.stream.status,
    consecutiveSnapshotFailures: snapshotFailures
  });

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
    previewEnabled &&
    tabActive &&
    (GRID_PREVIEW_EAGER ? previewStreamEligible : lazyLoadStream);
  const previewMode = selectDeviceTilePreviewMode({
    h264Enabled: GRID_PREVIEW_H264,
    webCodecsSupport,
    h264Stalled
  });
  const shouldUseWebRtcPreview =
    streamTransport === 'webrtc' && previewStreamEligible && loadStream;
  const shouldUseH264Preview =
    !shouldUseWebRtcPreview &&
    previewMode.useH264 &&
    previewStreamEligible &&
    loadStream;
  const shouldUseSnapshotPreview =
    !shouldUseWebRtcPreview &&
    previewMode.useSnapshot &&
    previewStreamEligible &&
    loadStream;
  const shouldWarmupPreview =
    !shouldUseWebRtcPreview && previewStreamEligible && loadStream;
  const h264PreviewActive =
    shouldUseH264Preview &&
    (previewWarmupState === 'attaching' || previewWarmupState === 'live');

  const previewUrl = useMemo(() => {
    if (!shouldUseSnapshotPreview) return null;
    if (!tabActive) return null;
    const base = `${deviceFarmMediaBase}/screenshot/${encodeURIComponent(device.serial)}?_r=${previewAttempt}&max_age_ms=${DASHBOARD_PREVIEW_MAX_AGE_MS}&max_width=360`;
    const token = tokenStorage.getAuthToken();
    return token ? `${base}&token=${encodeURIComponent(token)}` : base;
  }, [device.serial, previewAttempt, tabActive, shouldUseSnapshotPreview]);

  const showPreviewImg =
    shouldUseSnapshotPreview && Boolean(displayedPreviewUrl) && !frameStale;
  const frameVisible = hasFrame && !frameStale;

  /** Compact grid preview — readable enough for scanning without dominating the dashboard. */
  const previewMockupScreenWidth = 198;
  const previewMockupHeightPx = useMemo(
    () => mockupOuterHeightPx(previewMockupScreenWidth),
    [previewMockupScreenWidth]
  );
  const tileWidthPx = DEVICE_GRID_TILE_WIDTH_PX;

  const isPreviewQueued =
    shouldUseH264Preview && previewWarmupState === 'queued';
  const isUnresponsive =
    previewStreamEligible &&
    loadStream &&
    !shouldUseWebRtcPreview &&
    (frameStale || (!isPreviewQueued && !hasFrame && loadingElapsedSec >= 12));

  useEffect(() => {
    if (!GRID_PREVIEW_H264) {
      setWebCodecsSupport('unsupported');
      return;
    }
    setWebCodecsSupport(
      typeof window !== 'undefined' && 'VideoDecoder' in window
        ? 'supported'
        : 'unsupported'
    );
  }, []);

  useEffect(() => {
    setHasFrame(false);
    setH264Stalled(false);
    setDisplayedPreviewUrl(null);
    setPreviewAttempt(0);
    snapshotFailureCountRef.current = 0;
    setSnapshotFailures(0);
    setPreviewWarmupState('idle');
  }, [device.serial]);

  useH264Video(h264PreviewActive ? device.serial : '', previewCanvasRef, {
    inspectFramesForBlack: false,
    renderInWorker: true,
    onFrame: useCallback(() => {
      setHasFrame(true);
      setH264Stalled(false);
      setDisplayedPreviewUrl(null);
    }, []),
    onStall: useCallback(() => {
      setH264Stalled(true);
    }, [])
  });

  useEffect(() => {
    if (!shouldWarmupPreview) {
      previewWarmupRef.current?.release();
      previewWarmupRef.current = null;
      setPreviewWarmupState('idle');
      return;
    }

    let cancelled = false;
    let retryTimer: number | undefined;

    const clearRetry = () => {
      if (retryTimer === undefined) return;
      window.clearTimeout(retryTimer);
      retryTimer = undefined;
    };

    const scheduleRetry = (delayMs: number) => {
      clearRetry();
      retryTimer = window.setTimeout(tryAcquire, delayMs);
    };

    const tryAcquire = () => {
      if (cancelled || previewWarmupRef.current) return;
      const handle = acquireSnapshotPreviewWarmup(device.serial);
      if (!handle) {
        setPreviewWarmupState('error');
        scheduleRetry(1500);
        return;
      }

      previewWarmupRef.current = handle;
      setPreviewWarmupState('queued');
      handle.started.then((started) => {
        if (!started || cancelled || previewWarmupRef.current !== handle)
          return;
        setPreviewWarmupState('attaching');
      });
      handle.attached.then((attached) => {
        if (cancelled || previewWarmupRef.current !== handle) return;
        if (attached) {
          setPreviewWarmupState('live');
          requestIdr(device.serial, 0);
          return;
        }
        handle.release();
        if (previewWarmupRef.current === handle) {
          previewWarmupRef.current = null;
        }
        setPreviewWarmupState('error');
        scheduleRetry(1500);
      });
    };

    tryAcquire();
    return () => {
      cancelled = true;
      clearRetry();
      previewWarmupRef.current?.release();
      previewWarmupRef.current = null;
    };
  }, [device.serial, shouldWarmupPreview]);

  useEffect(() => {
    if (!previewUrl) return;
    let cancelled = false;
    let refreshTimer: number | undefined;
    const image = new Image();
    const scheduleRefresh = (delayMs: number) => {
      refreshTimer = window.setTimeout(() => {
        setPreviewAttempt((n) => n + 1);
      }, delayMs);
    };
    image.onload = () => {
      if (cancelled) return;
      snapshotFailureCountRef.current = 0;
      setSnapshotFailures(0);
      setDisplayedPreviewUrl(previewUrl);
      setHasFrame(true);
      scheduleRefresh(DASHBOARD_PREVIEW_REFRESH_MS);
    };
    image.onerror = () => {
      if (cancelled) return;
      snapshotFailureCountRef.current += 1;
      setSnapshotFailures(snapshotFailureCountRef.current);
      scheduleRefresh(
        nextSnapshotRetryDelayMs({
          consecutiveFailureCount: snapshotFailureCountRef.current,
          refreshMs: DASHBOARD_PREVIEW_REFRESH_MS
        })
      );
    };
    image.src = previewUrl;
    return () => {
      cancelled = true;
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
      }
      image.onload = null;
      image.onerror = null;
    };
  }, [previewUrl]);

  useEffect(() => {
    return () => {
      previewWarmupRef.current?.release();
      previewWarmupRef.current = null;
    };
  }, [device.serial]);

  useEffect(() => {
    if (!previewStreamEligible || !loadStream || hasFrame) {
      setLoadingElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setLoadingElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => window.clearInterval(timer);
  }, [device.serial, hasFrame, previewStreamEligible, loadStream]);

  return (
    <Card
      id={`tile-${id}`}
      data-serial={device.serial}
      className='group/tile flex h-full max-w-full flex-col overflow-hidden rounded-xl border border-border/70 bg-card/70 shadow-sm backdrop-blur-sm transition-colors hover:border-primary/35'
      style={{ width: tileWidthPx }}
    >
      <CardContent className='flex flex-1 flex-col p-0'>
        <div className='border-b border-border/60 px-3 py-3'>
          <div className='flex min-w-0 items-start justify-between gap-2'>
            <div className='min-w-0'>
              <div className='flex min-w-0 items-center gap-1.5'>
                <span className='truncate text-sm font-semibold leading-5 text-foreground'>
                  {deviceDisplayName(device)}
                </span>
                {!isActive || agentOffline ? (
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
              {secondarySerial ? (
                <p
                  className='mt-0.5 truncate font-mono text-[11px] leading-4 text-muted-foreground'
                  title={secondarySerial}
                >
                  {secondarySerial}
                </p>
              ) : null}
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
            {commandReady ? (
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
                variant='secondary'
                className='h-8 min-w-0 flex-1 px-3 text-xs font-semibold'
                disabled
                aria-disabled='true'
              >
                {t('controlDevice')}
              </Button>
            )}
          </div>
          <div className='mt-2 grid grid-cols-3 gap-1'>
            <HealthIndicator
              label={t('health.agentLabel')}
              value={t(
                `health.agent.${health?.agent.status ?? (isActive ? 'online' : 'offline')}`
              )}
              hint={t('health.agentHint')}
              ok={
                (health?.agent.status ?? (isActive ? 'online' : 'offline')) ===
                'online'
              }
            />
            <HealthIndicator
              label={t('health.streamLabel')}
              value={t(
                `health.stream.${health?.stream.status ?? 'unavailable'}`
              )}
              hint={t('health.streamHint')}
              ok={health?.stream.status === 'ready'}
            />
            <HealthIndicator
              label={t('health.commandLabel')}
              value={t(
                `health.command.${health?.command.status ?? (commandReady ? 'ready' : 'unavailable')}`
              )}
              hint={t('health.commandHint')}
              ok={commandReady}
            />
          </div>
          <p className='mt-1 truncate text-[10px] text-muted-foreground'>
            {t('health.heartbeat')}:{' '}
            {(health?.last_signal_at ?? health?.agent.observed_at)
              ? new Intl.DateTimeFormat(undefined, {
                  dateStyle: 'short',
                  timeStyle: 'short'
                }).format(
                  new Date(
                    health?.last_signal_at ?? health?.agent.observed_at ?? ''
                  )
                )
              : t('health.unknownTime')}
          </p>
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
                {shouldUseWebRtcPreview && (
                  <DashboardWebRtcPreview
                    device={device}
                    active={shouldUseWebRtcPreview}
                    frameStale={frameStale}
                  />
                )}
                {showPreviewImg && (
                  // eslint-disable-next-line @next/next/no-img-element -- dashboard preview uses cached screenshot polling.
                  <img
                    src={displayedPreviewUrl!}
                    alt=''
                    role='presentation'
                    decoding='async'
                    className={cn(
                      'pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-500',
                      showPreviewImg ? 'opacity-100' : 'opacity-0'
                    )}
                    draggable={false}
                  />
                )}
                {h264PreviewActive && (
                  <canvas
                    ref={previewCanvasRef}
                    aria-hidden='true'
                    className={cn(
                      'pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-500',
                      frameVisible && !showPreviewImg
                        ? 'opacity-100'
                        : 'opacity-0'
                    )}
                  />
                )}
                {!isActive && !previewStreamEligible ? (
                  <div className='absolute inset-0 z-10 flex items-center justify-center bg-zinc-950 px-2 text-center text-[11px] text-muted-foreground'>
                    {t('deviceInactive')}
                  </div>
                ) : !loadStream ? (
                  <PreviewLoadingSurface
                    label={
                      previewEnabled
                        ? t('previewScrollToLoad')
                        : t('previewDeferred')
                    }
                    showSpinner={previewEnabled}
                  />
                ) : shouldUseWebRtcPreview ? null : (
                  <div
                    className={cn(
                      'absolute inset-0 z-10 transition-opacity duration-500',
                      frameVisible
                        ? 'pointer-events-none opacity-0'
                        : 'opacity-100'
                    )}
                    aria-live='polite'
                    aria-hidden={frameVisible}
                  >
                    {!isUnresponsive ? (
                      <PreviewLoadingSurface
                        label={t('streamWaitingFirstFrame')}
                      />
                    ) : (
                      <PreviewLoadingSurface
                        label={t('streamUnresponsive')}
                        showSpinner={false}
                        failed
                      />
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
  if (prev.previewEnabled !== next.previewEnabled) return false;
  if (prev.streamTransport !== next.streamTransport) return false;
  const pd = prev.device;
  const nd = next.device;
  return (
    pd.id === nd.id &&
    pd.name === nd.name &&
    pd.display_name === nd.display_name &&
    pd.registered_serial === nd.registered_serial &&
    pd.state === nd.state &&
    pd.brand === nd.brand &&
    pd.model === nd.model &&
    pd.battery === nd.battery &&
    pd.scenario_active === nd.scenario_active &&
    pd.media_adapter_connected === nd.media_adapter_connected &&
    pd.media_stream_active === nd.media_stream_active &&
    pd.media_stream_connected === nd.media_stream_connected &&
    pd.health?.evaluated_at === nd.health?.evaluated_at &&
    pd.screen_width === nd.screen_width &&
    pd.screen_height === nd.screen_height
  );
}

export const DeviceTilePreview = memo(
  DeviceTilePreviewInner,
  tilePreviewPropsEqual
);
