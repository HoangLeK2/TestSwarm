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

/** Portrait screen height inside react-device-mockup bezel (matches lib formula). */
export function mockupPortraitScreenHeightPx(screenWidth: number): number {
  return Math.floor((screenWidth / 9) * 19.5);
}

export function mockupFrameWidthPx(screenWidth: number): number {
  return Math.max(1, Math.floor((screenWidth * 32) / 1080));
}

/** Approximate outer height of frameOnly AndroidMockup — pairs with control rail stretch. */
export function mockupOuterHeightPx(screenWidth: number): number {
  const screenH = mockupPortraitScreenHeightPx(screenWidth);
  const frame = mockupFrameWidthPx(screenWidth);
  const inset = screenContentInsetPx(screenWidth);
  return screenH + frame * 2 + inset * 2;
}

/** Android phone frame for farm tiles — stream fills the mock screen (status/nav hidden). */
export function DeviceAndroidFrame({
  screenWidth,
  deviceWidth,
  deviceHeight,
  className,
  children
}: Props) {
  const clipRadius = useMemo(
    () => mockupInnerCornerRadiusPx(screenWidth),
    [screenWidth]
  );
  const inset = useMemo(() => screenContentInsetPx(screenWidth), [screenWidth]);
  const innerRadius = useMemo(
    () => Math.max(2, clipRadius - inset),
    [clipRadius, inset]
  );

  const mockup = (
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
        className
      )}
    >
      <div
        className='relative isolate box-border flex h-full min-h-0 w-full flex-col overflow-hidden bg-black'
        style={{ borderRadius: clipRadius, padding: inset }}
      >
        <div
          className='h-full min-h-0 w-full min-w-0 flex-1 overflow-hidden bg-black'
          style={{ borderRadius: innerRadius }}
        >
          {children}
        </div>
      </div>
    </AndroidMockup>
  );

  // Note: We intentionally do NOT clip the mockup height to match device aspect ratio.
  // Shorter devices (e.g. 16:9) should appear with consistent bezel; stream should
  // use `object-contain` to avoid cropping instead.
  void deviceWidth;
  void deviceHeight;
  return mockup;
}
