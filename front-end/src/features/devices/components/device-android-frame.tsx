'use client';

import { useMemo } from 'react';
import { AndroidMockup } from 'react-device-mockup';
import { cn } from '@/lib/utils';

type Props = {
  screenWidth: number;
  /** Actual device stream dimensions — used to constrain content height to the real
   * device aspect ratio so object-cover never clips the horizontal axis. */
  deviceWidth?: number;
  deviceHeight?: number;
  children: React.ReactNode;
  className?: string;
};

/** Match lib's getSizeWithRatio(140) outer radius minus FRAME_WIDTH (~getSizeWithRatio(32)) for inner clip. */
function mockupInnerCornerRadiusPx(screenWidth: number): number {
  const outer = Math.floor((screenWidth * 140) / 1080);
  const frame = Math.floor((screenWidth * 32) / 1080);
  return Math.max(4, outer - frame);
}

/** Inset between stream and inner bezel — scales ~2% screen width (min 5px). */
function screenContentInsetPx(screenWidth: number): number {
  return Math.max(5, Math.round(screenWidth * 0.02));
}

/** Android phone frame for farm tiles — stream fills the mock screen (status/nav hidden). */
export function DeviceAndroidFrame({ screenWidth, deviceWidth, deviceHeight, className, children }: Props) {
  const clipRadius = useMemo(() => mockupInnerCornerRadiusPx(screenWidth), [screenWidth]);
  const inset = useMemo(() => screenContentInsetPx(screenWidth), [screenWidth]);
  const innerRadius = useMemo(() => Math.max(2, clipRadius - inset), [clipRadius, inset]);

  // Constrain content height to device's real aspect ratio so object-cover never
  // over-scales and clips the horizontal axis. The mockup lib uses ~9:20 internally;
  // devices are typically 9:16–9:19.5 — the mismatch causes left/right clipping.
  const contentWidth = screenWidth - 2 * inset;
  const streamHeight = useMemo(
    () =>
      deviceWidth && deviceHeight && deviceWidth > 0
        ? Math.round(contentWidth * (deviceHeight / deviceWidth))
        : undefined,
    [contentWidth, deviceWidth, deviceHeight],
  );

  return (
    <AndroidMockup
      screenWidth={screenWidth}
      frameOnly
      hideStatusBar
      hideNavBar
      frameColor='#1a1b22'
      className={cn(
        'drop-shadow-[0_12px_28px_rgba(2,6,23,0.24)]',
        // Lib always paints a fake punch-hole when hideStatusBar — no prop to disable it.
        '[&>div>div>div>:last-child]:hidden',
        className,
      )}
    >
      <div
        className='relative isolate box-border flex h-full min-h-0 w-full flex-col items-start overflow-hidden bg-black'
        style={{ borderRadius: clipRadius, padding: inset }}
      >
        <div
          className='w-full min-w-0 flex-shrink-0 overflow-hidden bg-black'
          style={{
            borderRadius: innerRadius,
            height: streamHeight !== undefined ? `${streamHeight}px` : '100%',
          }}
        >
          {children}
        </div>
      </div>
    </AndroidMockup>
  );
}
