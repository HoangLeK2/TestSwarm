'use client';

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
import { DeviceStepMonitor } from './device-step-monitor';
import { SHOW_RELAY_SCRCPY_UI_TOGGLE } from '../streaming-ui-flags';
import { useH264Video } from '../hooks/use-h264-canvas';

interface DeviceTilePreviewProps {
  device: Device;
  /** Server allows MJPEG on grid (/api/config). */
  serverAllowPreviewMjpeg?: boolean;
  /** From GET /api/config — relay scrcpy toggle only in continuous mode. */
  streamingConfig?: DeviceFarmStreamingConfig | null;
}

export function DeviceTilePreview({
  device,
  serverAllowPreviewMjpeg = true,
  streamingConfig = null,
}: DeviceTilePreviewProps) {
  const t = useTranslations('devicesFarm');
  const id = serialToId(device.serial);
  const isActive =
    device.state && !['DISCONNECTED', 'DEAD'].includes(device.state.toUpperCase());

  const previewZoneRef = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);

  useLayoutEffect(() => {
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

  const [loadStream, setLoadStream] = useState(false);
  useEffect(() => {
    if (!inView) {
      const t = window.setTimeout(() => setLoadStream(false), 700);
      return () => window.clearTimeout(t);
    }
    setLoadStream(true);
    return undefined;
  }, [inView]);

  const previewFps = useMemo(() => {
    const raw = Number(process.env.NEXT_PUBLIC_DEVICE_FARM_PREVIEW_FPS ?? 8);
    if (!Number.isFinite(raw)) return 8;
    return Math.max(1, Math.min(15, Math.round(raw)));
  }, []);

  const mjpegUrl = useMemo(() => {
    if (!isActive) return null;
    const base = `${deviceFarmBackendBase}/stream/${encodeURIComponent(device.serial)}?fps=${previewFps}`;
    const token = tokenStorage.getAuthToken();
    return token ? `${base}&token=${encodeURIComponent(token)}` : base;
  }, [device.serial, isActive, previewFps]);

  const showMjpeg =
    Boolean(mjpegUrl) &&
    serverAllowPreviewMjpeg &&
    loadStream;

  /** Grid preview — target ~282px outer after lib bezel + side padding. */
  const previewMockupScreenWidth = 262;

  const isContinuous =
    streamingConfig !== null && streamingConfig.mode === 'continuous';
  const [relayStreamOn, setRelayStreamOn] = useState(true);
  const [relayStreamBusy, setRelayStreamBusy] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [h264Active, setH264Active] = useState(false);
  const h264TimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const h264WarmupRef = useRef<{ startedAt: number; frames: number }>({ startedAt: 0, frames: 0 });

  const allowH264 =
    isActive &&
    loadStream &&
    (streamingConfig === null || streamingConfig.mode !== 'continuous' || relayStreamOn);

  useLayoutEffect(() => {
    if (!streamingConfig || streamingConfig.mode !== 'continuous') return;
    const serverWants =
      device.relay_scrcpy_enabled !== undefined && device.relay_scrcpy_enabled !== null
        ? Boolean(device.relay_scrcpy_enabled)
        : Boolean(streamingConfig.autoAttachScrcpy);
    setRelayStreamOn(serverWants);
  }, [
    streamingConfig?.mode,
    streamingConfig?.autoAttachScrcpy,
    device.serial,
    device.relay_scrcpy_enabled,
  ]);

  const onRelayStreamChange = useCallback(
    async (checked: boolean) => {
      if (!isContinuous || !isActive) return;
      setRelayStreamBusy(true);
      try {
        if (checked) {
          await farmApi.post(`/devices/${encodeURIComponent(device.serial)}/scrcpy/attach`, {});
        } else {
          await farmApi.post(`/devices/${encodeURIComponent(device.serial)}/scrcpy/detach`, {});
        }
        setRelayStreamOn(checked);
      } catch (err) {
        const msg =
          err && typeof err === 'object' && 'response' in err
            ? String(
                (err as { response?: { data?: { error?: string } } }).response?.data?.error ?? ''
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

  useH264Video(
    allowH264 ? device.serial : '',
    canvasRef,
    {
      onFrame: useCallback(() => {
        const now = Date.now();
        const warm = h264WarmupRef.current;
        if (warm.startedAt === 0 || (now - warm.startedAt) > 1500) {
          warm.startedAt = now;
          warm.frames = 1;
        } else {
          warm.frames += 1;
        }
        if (!h264Active && warm.frames >= 4) {
          setH264Active(true);
        }
        if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
        h264TimeoutRef.current = setTimeout(() => setH264Active(false), 8000);
      }, [h264Active]),
    }
  );

  useEffect(() => {
    setH264Active(false);
    h264WarmupRef.current = { startedAt: 0, frames: 0 };
    if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
    return () => {
      if (h264TimeoutRef.current) clearTimeout(h264TimeoutRef.current);
    };
  }, [device.serial, allowH264]);

  return (
    <Card
      id={`tile-${id}`}
      data-serial={device.serial}
      className='flex h-full flex-col border-border bg-card shadow-sm'
    >
      <CardHeader className='border-b border-border/60 px-4 py-3'>
        <div className='flex items-center justify-between gap-2'>
          <div className='flex min-w-0 flex-col gap-0.5'>
            <CardTitle className='truncate text-xs font-medium text-foreground'>
              {device.brand} {device.model}
            </CardTitle>
            <span className='font-mono text-[10px] text-muted-foreground'>
              {device.serial}
            </span>
          </div>
          <div className='flex shrink-0 items-center gap-1.5'>
            <DeviceStepMonitor
              serial={device.serial}
              isBusy={device.state?.toUpperCase() === 'BUSY'}
            />
            {isActive ? (
              <Button asChild size='sm' className='shrink-0'>
                <Link href={ROUTES.DEVICES.CONTROL_RECORD_WITH_SERIAL(device.serial)}>
                  {t('controlDevice')}
                </Link>
              </Button>
            ) : (
              <Button size='sm' className='shrink-0' disabled>
                {t('controlDevice')}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className='flex flex-1 flex-col gap-2 px-3 pb-3 pt-3'>
        <div className='flex flex-col items-center gap-2'>
          <div className='mx-auto'>
            <DeviceAndroidFrame
              screenWidth={previewMockupScreenWidth}
              deviceWidth={device.screen_width}
              deviceHeight={device.screen_height}
            >
              <div
                ref={previewZoneRef}
                className='relative h-full w-full overflow-hidden bg-black'
              >
                {isActive && showMjpeg ? (
                  <img
                    src={mjpegUrl!}
                    alt={`${device.brand} ${device.model} preview`}
                    className={`absolute inset-0 h-full w-full object-cover object-bottom transition-opacity duration-300 ${h264Active ? 'opacity-0' : 'opacity-100'}`}
                  />
                ) : isActive && !serverAllowPreviewMjpeg ? (
                  <div className='flex h-full w-full items-center justify-center bg-zinc-900 px-2 text-center text-[10px] text-muted-foreground'>
                    {t('previewDisabledByServer')}
                  </div>
                ) : isActive && !loadStream ? (
                  <div className='flex h-full w-full items-center justify-center bg-zinc-900 px-2 text-center text-[10px] text-muted-foreground'>
                    {t('previewScrollToLoad')}
                  </div>
                ) : (
                  <div className='flex h-full w-full items-center justify-center bg-zinc-900 text-[11px] text-muted-foreground'>
                    {t('deviceInactive')}
                  </div>
                )}
                {allowH264 && (
                  <canvas
                    ref={canvasRef}
                    className={`pointer-events-none absolute inset-0 h-full w-full object-cover object-bottom transition-opacity duration-300 ${h264Active ? 'opacity-100' : 'opacity-0'}`}
                  />
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
