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
function mockupPortraitScreenHeightPx(screenWidth: number): number {
  return Math.floor((screenWidth / 9) * 19.5);
}

function mockupFrameWidthPx(screenWidth: number): number {
  return Math.max(1, Math.floor((screenWidth * 32) / 1080));
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
  const frameWidth = useMemo(
    () => mockupFrameWidthPx(screenWidth),
    [screenWidth]
  );

  // react-device-mockup uses 9:19.5; most devices are 9:16–9:19.5. Clip the mockup
  // to the device aspect ratio so the stream fills the visible screen without black
  // bars or horizontal object-cover clipping.
  const contentWidth = screenWidth - 2 * inset;
  const streamHeight = useMemo(
    () =>
      deviceWidth && deviceHeight && deviceWidth > 0
        ? Math.round(contentWidth * (deviceHeight / deviceWidth))
        : undefined,
    [contentWidth, deviceWidth, deviceHeight]
  );
  const mockupOuterHeight =
    mockupPortraitScreenHeightPx(screenWidth) + 2 * frameWidth;
  const clippedOuterHeight =
    streamHeight !== undefined
      ? streamHeight + 2 * inset + 2 * frameWidth
      : undefined;
  const shouldClipMockup =
    clippedOuterHeight !== undefined &&
    clippedOuterHeight < mockupOuterHeight;

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

  if (!shouldClipMockup || clippedOuterHeight === undefined) {
    return mockup;
  }

  return (
    <div
      className='overflow-hidden'
      style={{
        width: screenWidth + 2 * frameWidth,
        height: clippedOuterHeight
      }}
    >
      {mockup}
    </div>
  );
}
