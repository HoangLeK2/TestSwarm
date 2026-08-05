'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useDeviceFarm } from '../hooks/use-device-farm';
import { resolveControlRecordSelectedDevice } from '../lib/control-record-device-state';
import { shouldRunEmbedStream } from '../lib/embed-stream-visibility';
import { fetchConfig } from '../services/api';
import type { ScrcpyAttachOptions } from '../services/scrcpy-stream';
import type { DeviceScreenTransport } from './device-screen';
import { DeviceTile } from './device-tile';

type Props = {
  initialSerial: string;
  compact?: boolean;
  hideStepMonitor?: boolean;
  /** Render as monitor-only preview: no controls, no interactions. */
  readOnlyPreview?: boolean;
  onTap?: (serial: string, rx: number, ry: number) => void;
  onSwipe?: (
    serial: string,
    rx1: number,
    ry1: number,
    rx2: number,
    ry2: number,
    durationMs: number
  ) => void;
  onDragGesture?: (
    serial: string,
    rx1: number,
    ry1: number,
    rx2: number,
    ry2: number,
    durationMs: number
  ) => void;
};

/** Lightweight scrcpy profile for campaign-monitor embeds — avoids fighting control streams. */
const MONITOR_PREVIEW_SCRCPY_OPTIONS: ScrcpyAttachOptions = {
  enableControl: false,
  profile: 'degraded',
  maxFps: 4,
  maxWidth: 360,
  bitrate: 120_000
};

export function DeviceControlEmbed({
  initialSerial,
  compact = true,
  hideStepMonitor = false,
  readOnlyPreview = false,
  onTap,
  onSwipe,
  onDragGesture
}: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [nearViewport, setNearViewport] = useState(!readOnlyPreview);
  const [previewStreamEnabled, setPreviewStreamEnabled] =
    useState(!readOnlyPreview);
  const { data: appConfig } = useQuery({
    queryKey: ['device-farm', 'config'],
    queryFn: fetchConfig,
    staleTime: 60_000
  });

  useLayoutEffect(() => {
    if (!readOnlyPreview) {
      setNearViewport(true);
      return;
    }
    const element = viewportRef.current;
    if (!element) return;
    const margin = 160;
    const sync = () => {
      const rect = element.getBoundingClientRect();
      setNearViewport(
        document.visibilityState !== 'hidden' &&
          rect.bottom > -margin &&
          rect.top < window.innerHeight + margin
      );
    };

    sync();
    window.addEventListener('scroll', sync, { passive: true, capture: true });
    window.addEventListener('resize', sync);
    window.addEventListener('focus', sync);
    window.addEventListener('pageshow', sync);
    document.addEventListener('visibilitychange', sync);
    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(sync, {
            root: null,
            rootMargin: `${margin}px`,
            threshold: 0.04
          });
    observer?.observe(element);

    return () => {
      observer?.disconnect();
      window.removeEventListener('scroll', sync, { capture: true });
      window.removeEventListener('resize', sync);
      window.removeEventListener('focus', sync);
      window.removeEventListener('pageshow', sync);
      document.removeEventListener('visibilitychange', sync);
    };
  }, [readOnlyPreview]);

  useEffect(() => {
    if (!readOnlyPreview || nearViewport) {
      setPreviewStreamEnabled(true);
      return;
    }
    const timer = window.setTimeout(() => setPreviewStreamEnabled(false), 700);
    return () => window.clearTimeout(timer);
  }, [nearViewport, readOnlyPreview]);

  const {
    devices,
    logs,
    modes,
    wsSend,
    handleToggleMode,
    handleRestart,
    error
  } = useDeviceFarm({
    liveRefreshMs: readOnlyPreview ? 15_000 : undefined,
    loadTasks: false,
    refreshRegisteredOnFocus: !readOnlyPreview
  });

  const activeDevices = devices.filter(
    (d) => d.state && !['DISCONNECTED', 'DEAD'].includes(d.state.toUpperCase())
  );

  const selectedDevice = useMemo(
    () => resolveControlRecordSelectedDevice(activeDevices, initialSerial),
    [activeDevices, initialSerial]
  );

  const mode = selectedDevice ? (modes[selectedDevice.serial] ?? 'tap') : 'tap';
  const streamTransport = useMemo<DeviceScreenTransport>(
    () =>
      appConfig?.webrtc_enabled
        ? 'webrtc'
        : readOnlyPreview
          ? 'h264-only'
          : 'auto',
    [appConfig?.webrtc_enabled, readOnlyPreview]
  );

  if (error) {
    return (
      <div className='rounded border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive'>
        {error}
      </div>
    );
  }

  if (activeDevices.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-8 text-center'>
        <p className='text-xs text-muted-foreground'>
          Chưa có thiết bị hoạt động
        </p>
      </div>
    );
  }

  if (!selectedDevice) {
    return (
      <div className='rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-400'>
        Thiết bị đã chọn chưa kết nối. Chọn thiết bị khác trong danh sách
        campaign.
      </div>
    );
  }

  return (
    <div
      ref={viewportRef}
      className={compact ? 'w-full min-w-0 max-w-full' : ''}
    >
      <DeviceTile
        device={selectedDevice}
        logLines={compact ? [] : (logs[selectedDevice.serial] ?? [])}
        mode={mode}
        wsSend={wsSend}
        onToggleMode={handleToggleMode}
        onRestart={handleRestart}
        onTap={
          onTap ? (rx, ry) => onTap(selectedDevice.serial, rx, ry) : undefined
        }
        onSwipe={
          onSwipe
            ? (rx1, ry1, rx2, ry2, ms) =>
                onSwipe(selectedDevice.serial, rx1, ry1, rx2, ry2, ms)
            : undefined
        }
        onDragGesture={
          onDragGesture
            ? (rx1, ry1, rx2, ry2, ms) =>
                onDragGesture(selectedDevice.serial, rx1, ry1, rx2, ry2, ms)
            : undefined
        }
        compact={compact}
        hideStepMonitor={hideStepMonitor}
        hideControls={readOnlyPreview}
        hideDeviceFunctions={readOnlyPreview}
        readOnlyPreview={readOnlyPreview}
        streamFetchPriority={readOnlyPreview ? 'low' : 'auto'}
        streamTransport={streamTransport}
        scrcpyViewerRole={
          readOnlyPreview ? 'campaign-monitor' : 'control-screen'
        }
        scrcpyAttachOptions={
          readOnlyPreview ? MONITOR_PREVIEW_SCRCPY_OPTIONS : undefined
        }
        streamEnabled={shouldRunEmbedStream({
          readOnlyPreview,
          nearViewport: previewStreamEnabled
        })}
      />
    </div>
  );
}
