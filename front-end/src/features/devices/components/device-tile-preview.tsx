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
import type { Device, DeviceFarmStreamingConfig } from '../types';
import { serialToId } from '../helpers';
import { deviceFarmMediaBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';
import { ROUTES } from '@/config/routes';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import {
  DeviceAndroidFrame,
  mockupOuterHeightPx
} from './device-android-frame';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { DeviceStepMonitorButton } from './device-step-monitor';
import { SHOW_RELAY_SCRCPY_UI_TOGGLE } from '../streaming-ui-flags';
import { useH264Video } from '../hooks/use-h264-canvas';
import {
  ensureWatchSerial,
  requestIdr,
  subscribeDeviceFarm
} from '../services/ws';
import { Badge } from '@/components/ui/badge';
import { useTabNetworkActive } from '../hooks/use-tab-network-active';
import {
  attachScrcpyStream,
  createScrcpyViewerId,
  detachScrcpyStream,
  scrcpyAttachErrorMessage
} from '../services/scrcpy-stream';
import { isVisibleDeviceFarmActiveDevice } from '../lib/device-farm-visible-devices';

/** Lazy by default so multiple dashboard tabs do not exhaust browser stream connections. */
const GRID_PREVIEW_EAGER =
  (process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PREVIEW_EAGER ?? '0').trim() !==
  '0';
const SCRCPY_ATTACH_RETRY_MS = 3_000;

const gridH264Slots = new Set<string>();
const gridH264SlotListeners = new Set<() => void>();

let gridH264NotifyRaf = 0;

function notifyGridH264SlotListeners() {
  if (typeof window === 'undefined') return;
  if (gridH264NotifyRaf) return;
  gridH264NotifyRaf = window.requestAnimationFrame(() => {
    gridH264NotifyRaf = 0;
    gridH264SlotListeners.forEach((fn) => {
      try {
        fn();
      } catch {
        // isolate listener errors
      }
    });
  });
}

function claimGridH264Slot(serial: string, limit: number): boolean {
  if (!serial || limit <= 0) return false;
  if (gridH264Slots.has(serial)) return true;
  if (gridH264Slots.size >= limit) return false;
  gridH264Slots.add(serial);
  notifyGridH264SlotListeners();
  return true;
}

function releaseGridH264Slot(serial: string) {
  if (gridH264Slots.delete(serial)) {
    notifyGridH264SlotListeners();
  }
}

interface DeviceTilePreviewProps {
  device: Device;
  /** Server allows MJPEG on grid (/api/config). */
  serverAllowPreviewMjpeg?: boolean;
  /** From GET /api/config — relay scrcpy toggle only in continuous mode. */
  streamingConfig?: DeviceFarmStreamingConfig | null;
  onOpenSteps?: (serial: string) => void;
}

function DeviceTilePreviewInner({
  device,
  serverAllowPreviewMjpeg = true,
  streamingConfig = null,
  onOpenSteps
}: DeviceTilePreviewProps) {
  const t = useTranslations('devicesFarm');
  const id = serialToId(device.serial);
  const isActive = isVisibleDeviceFarmActiveDevice(device);
  const deviceState = String(device.state || '')
    .replace('DeviceState.', '')
    .toUpperCase();
  const automationBusy =
    deviceState === 'BUSY' || (device.scenario_active ?? 0) > 0;

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

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const attachedScrcpySerialRef = useRef<string | null>(null);
  const pendingScrcpyAttachSerialRef = useRef<string | null>(null);
  const scrcpyAttachGenerationRef = useRef(0);
  const scrcpyViewerIdRef = useRef(createScrcpyViewerId('grid-preview'));
  const tabActive = useTabNetworkActive();
  const [hasFrame, setHasFrame] = useState(false);
  const [mjpegFailed, setMjpegFailed] = useState(false);
  const [mjpegAttempt, setMjpegAttempt] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);
  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);
  const [h264Active, setH264Active] = useState(false);
  const [hasH264Slot, setHasH264Slot] = useState(false);
  const [h264Suppressed, setH264Suppressed] = useState(false);
  const [h264RestartKey, setH264RestartKey] = useState(0);
  const [scrcpyAttachReady, setScrcpyAttachReady] = useState(false);
  const [scrcpyAttachRetryTick, setScrcpyAttachRetryTick] = useState(0);
  const h264WarmupRef = useRef<{ startedAt: number; frames: number }>({
    startedAt: 0,
    frames: 0
  });
  const h264BlackStreakRef = useRef(0);
  const h264BusyRecoveryAtRef = useRef(0);
  const scrcpyAttachRetryTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);

  const clearScrcpyAttachRetryTimer = useCallback(() => {
    if (scrcpyAttachRetryTimerRef.current) {
      clearTimeout(scrcpyAttachRetryTimerRef.current);
      scrcpyAttachRetryTimerRef.current = null;
    }
  }, []);

  const scheduleScrcpyAttachRetry = useCallback(
    (generation: number, serial: string) => {
      clearScrcpyAttachRetryTimer();
      scrcpyAttachRetryTimerRef.current = setTimeout(() => {
        scrcpyAttachRetryTimerRef.current = null;
        if (scrcpyAttachGenerationRef.current !== generation) return;
        if (attachedScrcpySerialRef.current !== null) return;
        if (pendingScrcpyAttachSerialRef.current !== null) return;
        if (serial !== device.serial) return;
        setScrcpyAttachRetryTick((tick) => tick + 1);
      }, SCRCPY_ATTACH_RETRY_MS);
    },
    [clearScrcpyAttachRetryTimer, device.serial]
  );

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

  const previewFps = useMemo(() => {
    const raw = Number(process.env.NEXT_PUBLIC_DEVICE_FARM_PREVIEW_FPS ?? 1);
    if (!Number.isFinite(raw)) return 1;
    return Math.max(1, Math.min(8, Math.round(raw)));
  }, []);

  /** Compact grid preview — readable enough for scanning without dominating the dashboard. */
  const previewMockupScreenWidth = 216;
  const previewMockupHeightPx = useMemo(
    () => mockupOuterHeightPx(previewMockupScreenWidth),
    [previewMockupScreenWidth]
  );

  const isContinuous =
    streamingConfig !== null && streamingConfig.mode === 'continuous';
  const [relayStreamOn, setRelayStreamOn] = useState(true);
  const [relayStreamBusy, setRelayStreamBusy] = useState(false);

  const gridH264Limit = useMemo(() => {
    const raw = Number(
      process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_H264_LIMIT ?? 4
    );
    if (!Number.isFinite(raw)) return 4;
    return Math.max(0, Math.min(4, Math.round(raw)));
  }, []);

  const wantsH264 =
    isActive &&
    loadStream &&
    !h264Suppressed &&
    (streamingConfig === null ||
      streamingConfig.mode !== 'continuous' ||
      relayStreamOn);

  useEffect(() => {
    if (!wantsH264) {
      releaseGridH264Slot(device.serial);
      setHasH264Slot(false);
      return undefined;
    }

    const syncSlot = () => {
      const claimed = claimGridH264Slot(device.serial, gridH264Limit);
      setHasH264Slot((prev) => (prev === claimed ? prev : claimed));
    };
    gridH264SlotListeners.add(syncSlot);
    syncSlot();

    return () => {
      gridH264SlotListeners.delete(syncSlot);
      releaseGridH264Slot(device.serial);
    };
  }, [device.serial, gridH264Limit, wantsH264]);

  const allowH264 = wantsH264 && hasH264Slot && !h264Suppressed;
  const viewerGatedContinuous =
    isContinuous && streamingConfig?.autoAttachScrcpy === false;
  // Keep the tile's claimed H264 slot subscribed while viewer-gated scrcpy
  // attach/retry is in flight; otherwise backend can keep producing frames for
  // 0 WS subscribers after a relay/backend reconnect.
  const h264SubscriptionAllowed = allowH264;

  useEffect(() => {
    if (!viewerGatedContinuous || wsConnected) return;
    setScrcpyAttachReady(false);
  }, [viewerGatedContinuous, wsConnected]);

  const mjpegUrl = useMemo(() => {
    if (!tabActive) return null;
    if (!isActive || !serverAllowPreviewMjpeg) return null;
    // Optional low-FPS MJPEG fallback. Default backend config disables this on grid.
    if (allowH264 && h264Active) return null;
    const base = `${deviceFarmMediaBase}/stream/${encodeURIComponent(device.serial)}?fps=${previewFps}`;
    const token = tokenStorage.getAuthToken();
    const withAuth = token
      ? `${base}&token=${encodeURIComponent(token)}`
      : base;
    return mjpegAttempt > 0 ? `${withAuth}&_r=${mjpegAttempt}` : withAuth;
  }, [
    allowH264,
    device.serial,
    h264Active,
    isActive,
    mjpegAttempt,
    previewFps,
    tabActive,
    serverAllowPreviewMjpeg
  ]);

  const showMjpegImg = Boolean(mjpegUrl) && loadStream && !mjpegFailed;

  const isUnresponsive =
    isActive && loadStream && !hasFrame && loadingElapsedSec >= 12;

  useLayoutEffect(() => {
    if (!streamingConfig || streamingConfig.mode !== 'continuous') return;
    // Grid tiles without a relay toggle always try H264 when they have a slot.
    if (!SHOW_RELAY_SCRCPY_UI_TOGGLE) {
      setRelayStreamOn((prev) => (prev ? prev : true));
      return;
    }
    // When server auto-attach is disabled (viewer-gated), default to ON for tiles
    // that are actually decoding H264 (claimed slot). DB override still wins.
    if (
      device.relay_scrcpy_enabled !== undefined &&
      device.relay_scrcpy_enabled !== null
    ) {
      setRelayStreamOn(Boolean(device.relay_scrcpy_enabled));
      return;
    }
    if (streamingConfig.autoAttachScrcpy === false) {
      const next = Boolean(allowH264);
      setRelayStreamOn((prev) => (prev === next ? prev : next));
      return;
    }
    const next = Boolean(streamingConfig.autoAttachScrcpy);
    setRelayStreamOn((prev) => (prev === next ? prev : next));
  }, [
    streamingConfig?.mode,
    streamingConfig?.autoAttachScrcpy,
    streamingConfig,
    device.serial,
    device.relay_scrcpy_enabled,
    allowH264
  ]);

  const detachScrcpyViewer = useCallback((...serials: Array<string | null>) => {
    const viewerId = scrcpyViewerIdRef.current;
    Array.from(new Set(serials.filter(Boolean) as string[])).forEach(
      (serial) => {
        detachScrcpyStream(serial, viewerId).catch(() => {});
      }
    );
  }, []);

  // Viewer-gated streaming: attach when this preview owns an H264 slot.
  useEffect(() => {
    const shouldAttach =
      tabActive &&
      isContinuous &&
      isActive &&
      allowH264 &&
      streamingConfig?.mode === 'continuous' &&
      streamingConfig?.autoAttachScrcpy === false &&
      relayStreamOn;
    if (!shouldAttach) {
      clearScrcpyAttachRetryTimer();
      const attachedSerial = attachedScrcpySerialRef.current;
      const pendingSerial = pendingScrcpyAttachSerialRef.current;
      scrcpyAttachGenerationRef.current += 1;
      attachedScrcpySerialRef.current = null;
      pendingScrcpyAttachSerialRef.current = null;
      setScrcpyAttachReady(false);
      detachScrcpyViewer(attachedSerial, pendingSerial);
      return;
    }

    const serial = device.serial;
    if (attachedScrcpySerialRef.current === serial && scrcpyAttachReady) return;
    clearScrcpyAttachRetryTimer();
    const previousSerial = attachedScrcpySerialRef.current;
    if (previousSerial && previousSerial !== serial) {
      detachScrcpyViewer(previousSerial);
    }
    const generation = scrcpyAttachGenerationRef.current + 1;
    scrcpyAttachGenerationRef.current = generation;
    pendingScrcpyAttachSerialRef.current = serial;
    attachedScrcpySerialRef.current = serial;
    setScrcpyAttachReady(false);

    attachScrcpyStream(serial, scrcpyViewerIdRef.current)
      .then(() => {
        clearScrcpyAttachRetryTimer();
        pendingScrcpyAttachSerialRef.current =
          pendingScrcpyAttachSerialRef.current === serial
            ? null
            : pendingScrcpyAttachSerialRef.current;
        if (
          scrcpyAttachGenerationRef.current !== generation ||
          attachedScrcpySerialRef.current !== serial
        ) {
          detachScrcpyViewer(serial);
          return;
        }
        setScrcpyAttachReady(true);
        ensureWatchSerial(serial);
        requestIdr(serial);
      })
      .catch(() => {
        if (
          scrcpyAttachGenerationRef.current === generation &&
          attachedScrcpySerialRef.current === serial
        ) {
          attachedScrcpySerialRef.current = null;
          pendingScrcpyAttachSerialRef.current = null;
          setScrcpyAttachReady(false);
        } else if (pendingScrcpyAttachSerialRef.current === serial) {
          pendingScrcpyAttachSerialRef.current = null;
        }
        scheduleScrcpyAttachRetry(generation, serial);
      });

    return () => {
      // Avoid detach/re-attach flicker during React effect re-runs. The branch
      // above handles real inactive/offscreen transitions.
    };
  }, [
    allowH264,
    clearScrcpyAttachRetryTimer,
    detachScrcpyViewer,
    device.serial,
    isActive,
    isContinuous,
    relayStreamOn,
    scheduleScrcpyAttachRetry,
    scrcpyAttachReady,
    scrcpyAttachRetryTick,
    streamingConfig?.autoAttachScrcpy,
    streamingConfig?.mode,
    tabActive,
    wsConnected
  ]);

  useEffect(() => {
    const onPageHide = () => {
      const attachedSerial = attachedScrcpySerialRef.current;
      const pendingSerial = pendingScrcpyAttachSerialRef.current;
      if (!attachedSerial && !pendingSerial) return;
      scrcpyAttachGenerationRef.current += 1;
      attachedScrcpySerialRef.current = null;
      pendingScrcpyAttachSerialRef.current = null;
      setScrcpyAttachReady(false);
      clearScrcpyAttachRetryTimer();
      detachScrcpyViewer(attachedSerial, pendingSerial);
    };
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      const attachedSerial = attachedScrcpySerialRef.current;
      const pendingSerial = pendingScrcpyAttachSerialRef.current;
      if (attachedSerial || pendingSerial) {
        scrcpyAttachGenerationRef.current += 1;
        attachedScrcpySerialRef.current = null;
        pendingScrcpyAttachSerialRef.current = null;
        setScrcpyAttachReady(false);
        detachScrcpyViewer(attachedSerial, pendingSerial);
      }
    };
  }, [clearScrcpyAttachRetryTimer, detachScrcpyViewer]);

  const onRelayStreamChange = useCallback(
    async (checked: boolean) => {
      if (!isContinuous || !isActive) return;
      setRelayStreamBusy(true);
      try {
        if (checked) {
          await attachScrcpyStream(device.serial, scrcpyViewerIdRef.current);
          attachedScrcpySerialRef.current = device.serial;
          setScrcpyAttachReady(true);
        } else {
          await detachScrcpyStream(device.serial, scrcpyViewerIdRef.current);
          attachedScrcpySerialRef.current = null;
          pendingScrcpyAttachSerialRef.current = null;
          setScrcpyAttachReady(false);
        }
        setRelayStreamOn(checked);
      } catch (err) {
        const msg = scrcpyAttachErrorMessage(err);
        toast.error(
          checked ? t('screenStreamAttachError') : t('screenStreamDetachError'),
          { description: msg || undefined }
        );
      } finally {
        setRelayStreamBusy(false);
      }
    },
    [device.serial, isActive, isContinuous, t]
  );

  useH264Video(
    tabActive && h264SubscriptionAllowed ? device.serial : '',
    canvasRef,
    {
      restartKey: h264RestartKey,
      notifyStallWithVisibleFrame: automationBusy,
      onFrame: useCallback(
        (frame?: { mostlyBlack: boolean }) => {
          if (frame?.mostlyBlack) {
            // Decoder reset/recovery often emits 1–2 black frames. Dropping H264
            // immediately crossfades to MJPEG and causes visible grid flicker.
            if (!h264Active) return;
            h264BlackStreakRef.current += 1;
            if (h264BlackStreakRef.current < 4) return;
            setH264Active(false);
            h264WarmupRef.current = { startedAt: 0, frames: 0 };
            return;
          }
          h264BlackStreakRef.current = 0;
          setHasFrame(true);
          const now = Date.now();
          const warm = h264WarmupRef.current;
          if (warm.startedAt === 0 || now - warm.startedAt > 1500) {
            warm.startedAt = now;
            warm.frames = 1;
          } else {
            warm.frames += 1;
          }
          if (!h264Active && warm.frames >= 1) {
            setH264Active(true);
          }
          // Keep the last decoded frame on static scenes — timing out to MJPEG
          // makes idle devices look like they are blinking every few seconds.
        },
        [h264Active]
      ),
      onStall: useCallback(
        (reason: 'no_packets' | 'decoder_stalled') => {
          // Soft recovery: keep canvas visible when possible; only nudge MJPEG
          // when we never got a first frame.
          h264WarmupRef.current = { startedAt: 0, frames: 0 };
          h264BlackStreakRef.current = 0;
          if (automationBusy) {
            const now = Date.now();
            if (now - h264BusyRecoveryAtRef.current > 2500) {
              h264BusyRecoveryAtRef.current = now;
              setH264Active(false);
              setHasFrame(false);
              setH264RestartKey((key) => key + 1);
              requestIdr(device.serial, 0);
            }
            if (reason === 'no_packets') {
              setMjpegFailed(false);
              setMjpegAttempt((n) => n + 1);
            }
            return;
          }
          if (!hasFrame) {
            setMjpegFailed(false);
            setMjpegAttempt((n) => n + 1);
          }
        },
        [automationBusy, device.serial, hasFrame]
      )
    }
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d', {
      alpha: false,
      willReadFrequently: true
    });
    if (canvas && ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    setHasFrame(false);
    setMjpegFailed(false);
    setMjpegAttempt(0);
    setH264Active(false);
    setH264Suppressed(false);
    if (!h264SubscriptionAllowed) setScrcpyAttachReady(false);
    h264BusyRecoveryAtRef.current = 0;
    h264WarmupRef.current = { startedAt: 0, frames: 0 };
    h264BlackStreakRef.current = 0;
  }, [device.serial, h264SubscriptionAllowed]);

  useEffect(() => {
    setMjpegFailed(false);
  }, [mjpegUrl]);

  useEffect(() => {
    if (
      !mjpegFailed ||
      !tabActive ||
      !isActive ||
      !loadStream ||
      !serverAllowPreviewMjpeg
    )
      return;
    const retry = window.setTimeout(() => setMjpegAttempt((n) => n + 1), 3000);
    return () => window.clearTimeout(retry);
  }, [mjpegFailed, tabActive, isActive, loadStream, serverAllowPreviewMjpeg]);

  useEffect(() => {
    if (!tabActive) {
      setWsConnected(false);
      return;
    }
    const unsub = subscribeDeviceFarm((msg) => {
      if (msg.type === 'ws_status') setWsConnected(Boolean(msg.connected));
    });
    return () => unsub();
  }, [tabActive]);

  useEffect(() => {
    if (!isActive || !loadStream) return;
    if (h264SubscriptionAllowed) ensureWatchSerial(device.serial);
  }, [device.serial, h264SubscriptionAllowed, isActive, loadStream]);

  useEffect(() => {
    if (!isActive || !wsConnected || hasFrame || !h264SubscriptionAllowed)
      return;
    ensureWatchSerial(device.serial);
    const idr = window.setTimeout(() => requestIdr(device.serial), 100);
    const armMjpeg = window.setTimeout(() => {
      setMjpegFailed(false);
      setMjpegAttempt((n) => n + 1);
    }, 2500);
    return () => {
      window.clearTimeout(idr);
      window.clearTimeout(armMjpeg);
    };
  }, [device.serial, h264SubscriptionAllowed, hasFrame, isActive, wsConnected]);

  useEffect(() => {
    if (!isActive || hasFrame) {
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
                {showMjpegImg && (
                  // eslint-disable-next-line @next/next/no-img-element -- MJPEG stream endpoint
                  <img
                    src={mjpegUrl!}
                    alt=''
                    role='presentation'
                    decoding='async'
                    className={cn(
                      'pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-500',
                      hasFrame && !h264Active ? 'opacity-100' : 'opacity-0'
                    )}
                    onLoad={() => setHasFrame(true)}
                    onError={() => setMjpegFailed(true)}
                    draggable={false}
                  />
                )}
                {allowH264 && (
                  <canvas
                    ref={canvasRef}
                    className={cn(
                      'pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-500',
                      h264Active && hasFrame ? 'opacity-100' : 'opacity-0'
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
                ) : !serverAllowPreviewMjpeg && !allowH264 ? (
                  <div className='absolute inset-0 z-10 flex items-center justify-center bg-zinc-950 px-2 text-center text-[10px] text-muted-foreground'>
                    {t('previewDisabledByServer')}
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
                        : wsConnected
                          ? t('streamWaitingFirstFrame')
                          : t('streamConnecting')}
                    </span>
                    {!isUnresponsive ? (
                      <>
                        <div className='h-5 w-5 animate-spin rounded-full border-2 border-zinc-400/80 border-t-transparent' />
                        <p className='mt-2 text-[10px] text-muted-foreground'>
                          {wsConnected
                            ? t('streamWaitingFirstFrame')
                            : t('streamConnecting')}
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
        {SHOW_RELAY_SCRCPY_UI_TOGGLE &&
          isContinuous &&
          isActive &&
          streamingConfig !== null && (
            <div className='mt-2 flex flex-col gap-1 border-t border-border/60 pt-2'>
              <div className='flex items-start justify-between gap-2'>
                <div className='min-w-0 flex-1'>
                  <div className='text-xs font-medium leading-tight text-foreground'>
                    {t('gridRelayStream')}
                  </div>
                  <p className='mt-0.5 text-[10px] leading-snug text-muted-foreground'>
                    {t('gridRelayStreamHint')}
                  </p>
                </div>
                <Switch
                  className='mt-0.5 shrink-0'
                  checked={relayStreamOn}
                  disabled={relayStreamBusy}
                  onCheckedChange={(v) => void onRelayStreamChange(v)}
                />
              </div>
              {!streamingConfig.autoAttachScrcpyOnRelayOnline ? (
                <p className='text-[10px] leading-snug text-muted-foreground'>
                  {t('gridRelayManualOnlyHint')}
                </p>
              ) : null}
            </div>
          )}
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
  if (prev.serverAllowPreviewMjpeg !== next.serverAllowPreviewMjpeg)
    return false;
  if (prev.streamingConfig?.mode !== next.streamingConfig?.mode) return false;
  if (
    prev.streamingConfig?.autoAttachScrcpy !==
    next.streamingConfig?.autoAttachScrcpy
  )
    return false;
  if (
    prev.streamingConfig?.autoAttachScrcpyOnRelayOnline !==
    next.streamingConfig?.autoAttachScrcpyOnRelayOnline
  ) {
    return false;
  }
  const pd = prev.device;
  const nd = next.device;
  return (
    pd.state === nd.state &&
    pd.brand === nd.brand &&
    pd.model === nd.model &&
    pd.battery === nd.battery &&
    pd.scenario_active === nd.scenario_active &&
    pd.relay_scrcpy_enabled === nd.relay_scrcpy_enabled &&
    pd.screen_width === nd.screen_width &&
    pd.screen_height === nd.screen_height
  );
}

export const DeviceTilePreview = memo(
  DeviceTilePreviewInner,
  tilePreviewPropsEqual
);
