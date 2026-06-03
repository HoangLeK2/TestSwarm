'use client';

import { memo } from 'react';
import type { Device } from '../../types';
import { DeviceAndroidFrame } from '../device-android-frame';
import { DeviceScreen } from '../device-screen';
import { cn } from '@/lib/utils';

export function formatFollowerLabel(d: Pick<Device, 'brand' | 'model' | 'serial'>) {
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
  mode: 'tap' | 'swipe';
  wsSend: (obj: object) => void;
  onPromote: (serial: string) => void;
};

export const FollowerPreview = memo(function FollowerPreview({
  device,
  mockupScreenWidth,
  mode,
  wsSend,
  onPromote
}: Props) {
  const label = formatFollowerLabel(device);
  const state = String(device.state || '')
    .replace('DeviceState.', '')
    .toUpperCase();
  const isActive = state && !['DISCONNECTED', 'DEAD'].includes(state);

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
        <div className='flex justify-center bg-muted/20 px-1.5 pb-1 pt-2'>
          <DeviceAndroidFrame
            screenWidth={mockupScreenWidth}
            deviceWidth={device.screen_width}
            deviceHeight={device.screen_height}
            className='shrink-0'
          >
            {isActive ? (
              <DeviceScreen
                device={device}
                wsSend={wsSend}
                mode={mode}
                interactive={false}
                streamFetchPriority='low'
              />
            ) : (
              <div className='flex h-full w-full items-center justify-center bg-zinc-900 text-[10px] text-zinc-500'>
                OFF
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
