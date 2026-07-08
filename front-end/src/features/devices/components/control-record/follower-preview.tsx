'use client';

import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import type { Device } from '../../types';
import { DeviceAndroidFrame } from '../device-android-frame';
import { cn } from '@/lib/utils';
import { deviceFarmMediaBase } from '@/lib/farm-api';
import { tokenStorage } from '@/lib/token-storage';
import { useTabNetworkActive } from '../../hooks/use-tab-network-active';

const FOLLOWER_PREVIEW_REFRESH_MS = (() => {
  const raw = Number(
    process.env.NEXT_PUBLIC_DEVICE_FARM_FOLLOWER_PREVIEW_MS ?? 500
  );
  if (!Number.isFinite(raw)) return 500;
  return Math.max(500, Math.min(5_000, Math.round(raw)));
})();

export function formatFollowerLabel(
  d: Pick<Device, 'brand' | 'model' | 'serial'>
) {
  const name = `${d.brand} ${d.model}`.trim();
  if (name) return name.length > 22 ? `${name.slice(0, 21)}…` : name;
  return d.serial.length > 16 ? `${d.serial.slice(0, 8)}…` : d.serial;
}

/** Stable mockup width — avoids ResizeObserver + aspect-ratio overflow with bezels. */
export function followerMockupWidth(deviceCount: number): number {
  if (deviceCount <= 1) return 172;
  if (deviceCount === 2) return 156;
  if (deviceCount === 3) return 136;
  if (deviceCount <= 6) return 120;
  return 108;
}

type Props = {
  device: Device;
  mockupScreenWidth: number;
  onPromote: (serial: string) => void;
  previewIndex?: number;
  previewCount?: number;
};

export const FollowerPreview = memo(function FollowerPreview({
  device,
  mockupScreenWidth,
  onPromote,
  previewIndex = 0,
  previewCount = 1
}: Props) {
  const t = useTranslations('devicesControlRecord.view');
  const label = formatFollowerLabel(device);
  const previewZoneRef = useRef<HTMLDivElement>(null);
  const tabActive = useTabNetworkActive();
  const [inView, setInView] = useState(false);
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [displayedPreviewUrl, setDisplayedPreviewUrl] = useState<string | null>(
    null
  );
  const [hasFrame, setHasFrame] = useState(false);
  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);
  const [previewCadenceReady, setPreviewCadenceReady] = useState(false);
  const state = String(device.state || '')
    .replace('DeviceState.', '')
    .toUpperCase();
  const isActive = state && !['DISCONNECTED', 'DEAD'].includes(state);
  const shouldSchedulePreview = Boolean(isActive && tabActive && inView);
  const loadPreview = shouldSchedulePreview && previewCadenceReady;
  const refreshOffsetMs = useMemo(() => {
    const count = Math.max(1, Math.round(previewCount));
    const index = Math.max(0, previewIndex) % count;
    return Math.floor((FOLLOWER_PREVIEW_REFRESH_MS / count) * index);
  }, [previewCount, previewIndex]);

  useEffect(() => {
    const el = previewZoneRef.current;
    if (!el) return;
    const margin = 120;
    const sync = () => {
      const rect = el.getBoundingClientRect();
      setInView(
        rect.bottom > -margin && rect.top < window.innerHeight + margin
      );
    };
    sync();
    if (typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(
      (entries) => setInView(Boolean(entries[0]?.isIntersecting)),
      { root: null, rootMargin: `${margin}px`, threshold: 0.05 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const previewUrl = useMemo(() => {
    if (!loadPreview) return null;
    const base = `${deviceFarmMediaBase}/screenshot/${encodeURIComponent(device.serial)}?_r=${previewAttempt}`;
    const token = tokenStorage.getAuthToken();
    return token ? `${base}&token=${encodeURIComponent(token)}` : base;
  }, [device.serial, loadPreview, previewAttempt]);

  useEffect(() => {
    setDisplayedPreviewUrl(null);
    setHasFrame(false);
    setLoadingElapsedSec(0);
    setPreviewCadenceReady(false);
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
    if (!shouldSchedulePreview) {
      setPreviewCadenceReady(false);
      return;
    }
    setPreviewCadenceReady(false);
    let interval: number | undefined;
    const tick = () => {
      setPreviewAttempt((n) => n + 1);
    };
    const timeout = window.setTimeout(() => {
      setPreviewCadenceReady(true);
      interval = window.setInterval(tick, FOLLOWER_PREVIEW_REFRESH_MS);
    }, refreshOffsetMs);
    return () => {
      window.clearTimeout(timeout);
      if (interval !== undefined) window.clearInterval(interval);
    };
  }, [refreshOffsetMs, shouldSchedulePreview]);

  useEffect(() => {
    if (!loadPreview || hasFrame) {
      setLoadingElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setLoadingElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => window.clearInterval(timer);
  }, [device.serial, hasFrame, loadPreview]);

  return (
    <button
      type='button'
      onClick={() => onPromote(device.serial)}
      className={cn(
        'w-fit shrink-0 text-left',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2'
      )}
      title={device.serial}
    >
      <div className='overflow-hidden rounded-xl border border-border/70 bg-card shadow-sm transition hover:border-primary/45 hover:shadow-md'>
        <div
          ref={previewZoneRef}
          className='flex justify-center bg-muted/20 px-1.5 pb-1 pt-2'
        >
          <DeviceAndroidFrame
            screenWidth={mockupScreenWidth}
            deviceWidth={device.screen_width}
            deviceHeight={device.screen_height}
            className='shrink-0'
          >
            {isActive ? (
              displayedPreviewUrl ? (
                // eslint-disable-next-line @next/next/no-img-element -- follower preview intentionally uses lightweight cached screenshots.
                <img
                  src={displayedPreviewUrl}
                  alt=''
                  role='presentation'
                  decoding='async'
                  className='h-full w-full object-contain object-center'
                  draggable={false}
                />
              ) : loadingElapsedSec >= 12 ? (
                <div className='flex h-full w-full items-center justify-center bg-zinc-900 px-2 text-center text-[10px] text-amber-300'>
                  {t('streamUnavailable')}
                </div>
              ) : (
                <div className='flex h-full w-full items-center justify-center bg-zinc-900 text-[10px] text-zinc-500'>
                  {t('streamWaitingFirstFrame')}
                </div>
              )
            ) : (
              <div className='flex h-full w-full items-center justify-center bg-zinc-900 text-[10px] text-zinc-500'>
                {t('followerOffline')}
              </div>
            )}
          </DeviceAndroidFrame>
        </div>
        <p className='truncate border-t border-border/50 bg-muted/30 px-2 py-1.5 text-center text-[10px] font-medium text-foreground'>
          {label}
        </p>
      </div>
    </button>
  );
});

export function followerGridClass(deviceCount: number) {
  if (deviceCount <= 4) {
    return 'flex max-w-full flex-wrap items-start justify-start gap-2';
  }
  return cn(
    'grid w-fit max-w-full gap-2 content-start justify-items-start',
    'grid-cols-2 lg:grid-cols-3 xl:grid-cols-4'
  );
}
