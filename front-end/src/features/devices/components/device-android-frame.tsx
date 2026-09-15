'use client';

import { useMemo, type CSSProperties, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import {
  mockupFrameWidthPx,
  mockupInnerCornerRadiusPx,
  screenContentInsetPx,
  screenHeightForDevicePx
} from './device-android-frame-geometry';

export {
  mockupFrameWidthPx,
  mockupOuterHeightPx,
  mockupPortraitScreenHeightPx,
  mockupScreenWidthForHeightPx
} from './device-android-frame-geometry';

type Props = {
  screenWidth: number;
  /** Actual device stream dimensions — used to constrain content height to the real
   * device aspect ratio so object-cover never clips the horizontal axis. */
  deviceWidth?: number;
  deviceHeight?: number;
  children: ReactNode;
  className?: string;
};

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
  const frameWidth = useMemo(
    () => mockupFrameWidthPx(screenWidth),
    [screenWidth]
  );
  const screenHeight = useMemo(
    () => screenHeightForDevicePx(screenWidth, deviceWidth, deviceHeight),
    [deviceHeight, deviceWidth, screenWidth]
  );
  const innerRadius = useMemo(
    () => Math.max(2, clipRadius - inset),
    [clipRadius, inset]
  );
  const screenBoxStyle = useMemo<CSSProperties>(() => {
    return {
      width: screenWidth,
      height: screenHeight
    };
  }, [screenHeight, screenWidth]);

  return (
    <div
      data-screen-width={screenWidth}
      data-screen-height={screenHeight}
      data-device-width={deviceWidth ?? 0}
      data-device-height={deviceHeight ?? 0}
      className={cn(
        'relative box-content shrink-0 bg-[#17181f] shadow-[0_12px_28px_rgba(2,6,23,0.24)]',
        className
      )}
      style={{
        width: screenWidth + inset * 2,
        height: screenHeight + inset * 2,
        borderRadius: clipRadius + frameWidth,
        padding: frameWidth
      }}
    >
      <div
        className='relative isolate box-border flex h-full min-h-0 w-full flex-col overflow-hidden bg-black'
        style={{ borderRadius: clipRadius, padding: inset }}
      >
        <div
          className='h-full min-h-0 w-full min-w-0 overflow-hidden bg-black'
          style={{ borderRadius: innerRadius }}
        >
          <div
            className='relative overflow-hidden bg-black'
            style={screenBoxStyle}
          >
            {children}
          </div>
        </div>
      </div>
      <div
        className='absolute right-[-5px] top-[18%] w-[5px] rounded-r-full bg-[#22242c]'
        style={{ height: Math.max(56, Math.round(screenHeight * 0.2)) }}
        aria-hidden
      />
      <div
        className='absolute right-[-5px] top-[42%] w-[5px] rounded-r-full bg-[#22242c]'
        style={{ height: Math.max(34, Math.round(screenHeight * 0.12)) }}
        aria-hidden
      />
    </div>
  );
}
