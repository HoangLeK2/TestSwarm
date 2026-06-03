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
import { deviceFarmBackendBase, farmApi } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';
import { ROUTES } from '@/config/routes';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { DeviceAndroidFrame } from './device-android-frame';
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

/** When true (default), grid tiles load MJPEG/H264 immediately for active devices (no scroll-to-load). Set NEXT_PUBLIC_DEVICE_FARM_GRID_PREVIEW_EAGER=0 to restore lazy viewport loading. */
const GRID_PREVIEW_EAGER =
  (process.env.NEXT_PUBLIC_DEVICE_FARM_GRID_PREVIEW_EAGER ?? '1').trim() !==
  '0';

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
  const isActive =
    device.state &&
    !['DISCONNECTED', 'DEAD'].includes(device.state.toUpperCase());

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
  const [hasFrame, setHasFrame] = useState(false);
  const [mjpegFailed, setMjpegFailed] = useState(false);
  const [mjpegAttempt, setMjpegAttempt] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);
  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);
  const [h264Active, setH264Active] = useState(false);
  const [hasH264Slot, setHasH264Slot] = useState(false);
  const h264TimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const h264WarmupRef = useRef<{ startedAt: number; frames: number }>({
    startedAt: 0,
    frames: 0
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

  const loadStream = GRID_PREVIEW_EAGER ? isActive : lazyLoadStream;

  const previewFps = useMemo(() => {
    const raw = Number(process.env.NEXT_PUBLIC_DEVICE_FARM_PREVIEW_FPS ?? 8);
    if (!Number.isFinite(raw)) return 8;
    return Math.max(1, Math.min(8, Math.round(raw)));
  }, []);

  /** Grid preview — target ~282px outer after lib bezel + side padding. */
  const previewMockupScreenWidth = 262;

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

  const allowH264 = wantsH264 && hasH264Slot;

  const mjpegUrl = useMemo(() => {
    if (!isActive || !serverAllowPreviewMjpeg) return null;
    // Keep MJPEG as fallback until H264 is actually rendering (same as control mirror).
    if (allowH264 && h264Active) return null;
    const base = `${deviceFarmBackendBase}/stream/${encodeURIComponent(device.serial)}?fps=${previewFps}`;
    const token = tokenStorage.getAuthToken();
    const withAuth = token ? `${base}&token=${encodeURIComponent(token)}` : base;
    return mjpegAttempt > 0 ? `${withAuth}&_r=${mjpegAttempt}` : withAuth;
  }, [
    allowH264,
    device.serial,
    h264Active,
    isActive,
    mjpegAttempt,
    previewFps,
    serverAllowPreviewMjpeg
  ]);

  const showMjpegImg =
    Boolean(mjpegUrl) && loadStream && !mjpegFailed;

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
    device.serial,
    device.relay_scrcpy_enabled,
    allowH264
  ]);

  // Viewer-gated streaming: attach on mount (when we have an H264 slot), detach on cleanup.
  useEffect(() => {
    if (!isContinuous || !isActive) return;
    if (!allowH264) return;
    if (!streamingConfig || streamingConfig.mode !== 'continuous') return;
    if (streamingConfig.autoAttachScrcpy !== false) return;
    if (!relayStreamOn) return;

    let detachScheduled = false;
    const serial = device.serial;

    farmApi
      .post(`/devices/${encodeURIComponent(serial)}/scrcpy/attach`, {})
      .catch(() => {});

    return () => {
      if (detachScheduled) return;
      detachScheduled = true;
      farmApi
        .post(`/devices/${encodeURIComponent(serial)}/scrcpy/detach`, {})
        .catch(() => {});
    };
  }, [
    allowH264,
    device.serial,
    isActive,
    isContinuous,
    relayStreamOn,
    streamingConfig?.autoAttachScrcpy,
    streamingConfig?.mode
  ]);

  const onRelayStreamChange = useCallback(
    async (checked: boolean) => {
      if (!isContinuous || !isActive) return;
      setRelayStreamBusy(true);
      try {
        if (checked) {
          await farmApi.post(
            `/devices/${encodeURIComponent(device.serial)}/scrcpy/attach`,
            {}
          );
        } else {
          await farmApi.post(
            `/devices/${encodeURIComponent(device.serial)}/scrcpy/detach`,
            {}
          );
        }
        setRelayStreamOn(checked);
      } catch (err) {
        const msg =
          err && typeof err === 'object' && 'response' in err
            ? String(
                (err as { response?: { data?: { error?: string } } }).response
                  ?.data?.error ?? ''
              )
            : '';
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

  useH264Video(allowH264 ? device.serial : '', canvasRef, {
    onFrame: useCallback(
      (frame?: { mostlyBlack: boolean }) => {
        if (frame?.mostlyBlack) {
          setH264Active(false);
          h264WarmupRef.current = { startedAt: 0, frames: 0 };
          return;
        }
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
        if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
        h264TimeoutRef.current = setTimeout(() => setH264Active(false), 8000);
      },
      [h264Active]
    )
  });

  useEffect(() => {
    setHasFrame(false);
    setMjpegFailed(false);
    setMjpegAttempt(0);
    setH264Active(false);
    h264WarmupRef.current = { startedAt: 0, frames: 0 };
    if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
    return () => {
      if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
    };
  }, [device.serial, allowH264]);

  useEffect(() => {
    setMjpegFailed(false);
  }, [mjpegUrl]);

  useEffect(() => {
    if (!mjpegFailed || !isActive || !loadStream || !serverAllowPreviewMjpeg)
      return;
    const retry = window.setTimeout(
      () => setMjpegAttempt((n) => n + 1),
      3000
    );
    return () => window.clearTimeout(retry);
  }, [mjpegFailed, isActive, loadStream, serverAllowPreviewMjpeg]);

  useEffect(() => {
    const unsub = subscribeDeviceFarm((msg) => {
      if (msg.type === 'ws_status') setWsConnected(Boolean(msg.connected));
    });
    return () => unsub();
  }, []);

  useEffect(() => {
    if (!isActive || !loadStream) return;
    if (allowH264) ensureWatchSerial(device.serial);
  }, [allowH264, device.serial, isActive, loadStream]);

  useEffect(() => {
    if (!isActive || !wsConnected || hasFrame) return;
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
  }, [device.serial, hasFrame, isActive, wsConnected]);

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
      <CardHeader className='relative z-10 border-b border-border/60 px-4 py-3'>
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
      <CardContent className='flex flex-1 flex-col gap-2 px-3 pb-3 pt-3'>
        <div className='flex flex-col items-center gap-2'>
          <div className='flex w-full justify-center'>
            <DeviceAndroidFrame
              screenWidth={previewMockupScreenWidth}
              deviceWidth={device.screen_width}
              deviceHeight={device.screen_height}
            >
              <div
                ref={previewZoneRef}
                className='relative h-full w-full overflow-hidden bg-zinc-900'
              >
                {isActive && loadStream && !hasFrame && (
                  <div
                    className='absolute inset-0 bg-gradient-to-b from-zinc-700 to-zinc-900'
                    aria-hidden
                  />
                )}
                {showMjpegImg && (
                  // eslint-disable-next-line @next/next/no-img-element -- MJPEG stream endpoint
                  <img
                    src={mjpegUrl!}
                    alt=''
                    role='presentation'
                    decoding='async'
                    className={`pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-300 ${h264Active ? 'opacity-0' : 'opacity-100'}`}
                    onLoad={() => setHasFrame(true)}
                    onError={() => setMjpegFailed(true)}
                    draggable={false}
                  />
                )}
                {allowH264 && (
                  <canvas
                    ref={canvasRef}
                    className={`pointer-events-none absolute inset-0 h-full w-full object-contain object-center transition-opacity duration-300 ${h264Active ? 'opacity-100' : 'opacity-0'}`}
                  />
                )}
                {!isActive ? (
                  <div className='absolute inset-0 flex items-center justify-center px-2 text-center text-[11px] text-muted-foreground'>
                    {t('deviceInactive')}
                  </div>
                ) : !loadStream ? (
                  <div className='absolute inset-0 flex items-center justify-center px-2 text-center text-[10px] text-muted-foreground'>
                    {t('previewScrollToLoad')}
                  </div>
                ) : !serverAllowPreviewMjpeg && !allowH264 ? (
                  <div className='absolute inset-0 flex items-center justify-center px-2 text-center text-[10px] text-muted-foreground'>
                    {t('previewDisabledByServer')}
                  </div>
                ) : !hasFrame ? (
                  <div
                    className='absolute inset-0 flex items-center justify-center'
                    aria-live='polite'
                  >
                    <span className='sr-only'>
                      {isUnresponsive
                        ? t('streamUnresponsive')
                        : wsConnected
                          ? t('streamWaitingFirstFrame')
                          : t('streamConnecting')}
                    </span>
                    {!isUnresponsive && (
                      <div className='h-5 w-5 animate-spin rounded-full border-2 border-zinc-400/80 border-t-transparent' />
                    )}
                  </div>
                ) : null}
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
    pd.relay_scrcpy_enabled === nd.relay_scrcpy_enabled &&
    pd.screen_width === nd.screen_width &&
    pd.screen_height === nd.screen_height
  );
}

export const DeviceTilePreview = memo(
  DeviceTilePreviewInner,
  tilePreviewPropsEqual
);
