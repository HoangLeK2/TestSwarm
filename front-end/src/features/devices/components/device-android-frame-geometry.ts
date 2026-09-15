/** Pure mockup geometry — split from the component so node --test can import it. */

/** Match lib's getSizeWithRatio(140) outer radius minus FRAME_WIDTH (~getSizeWithRatio(32)) for inner clip. */
export function mockupInnerCornerRadiusPx(screenWidth: number): number {
  const outer = Math.floor((screenWidth * 140) / 1080);
  const frame = Math.floor((screenWidth * 32) / 1080);
  return Math.max(4, outer - frame);
}

/** Inset between stream and inner bezel — scales ~2% screen width (min 5px). */
export function screenContentInsetPx(screenWidth: number): number {
  return Math.max(5, Math.round(screenWidth * 0.02));
}

/** Portrait screen height inside react-device-mockup bezel (matches lib formula). */
export function mockupPortraitScreenHeightPx(screenWidth: number): number {
  return Math.floor((screenWidth / 9) * 19.5);
}

export function screenHeightForDevicePx(
  screenWidth: number,
  deviceWidth?: number,
  deviceHeight?: number
): number {
  const safeDeviceWidth = Number(deviceWidth);
  const safeDeviceHeight = Number(deviceHeight);
  if (
    Number.isFinite(safeDeviceWidth) &&
    Number.isFinite(safeDeviceHeight) &&
    safeDeviceWidth > 0 &&
    safeDeviceHeight > 0
  ) {
    return Math.round((screenWidth * safeDeviceHeight) / safeDeviceWidth);
  }
  return mockupPortraitScreenHeightPx(screenWidth);
}

export function mockupFrameWidthPx(screenWidth: number): number {
  return Math.max(8, Math.floor((screenWidth * 32) / 1080));
}

/** Approximate outer height of frameOnly AndroidMockup — pairs with control rail stretch. */
export function mockupOuterHeightPx(
  screenWidth: number,
  deviceWidth?: number,
  deviceHeight?: number
): number {
  const screenH = screenHeightForDevicePx(
    screenWidth,
    deviceWidth,
    deviceHeight
  );
  const frame = mockupFrameWidthPx(screenWidth);
  const inset = screenContentInsetPx(screenWidth);
  return screenH + frame * 2 + inset * 2;
}

/** Largest screen width whose mockup still fits `maxOuterHeight` — inverse of `mockupOuterHeightPx`. */
export function mockupScreenWidthForHeightPx(
  maxOuterHeight: number,
  deviceWidth?: number,
  deviceHeight?: number
): number {
  const probe = 1080;
  const heightPerWidth =
    mockupOuterHeightPx(probe, deviceWidth, deviceHeight) / probe;
  let width = Math.floor(maxOuterHeight / heightPerWidth);
  // The bezel/inset minimums make the height super-linear at small widths, so the
  // linear estimate can overshoot by a few px — walk it back down.
  while (
    width > 1 &&
    mockupOuterHeightPx(width, deviceWidth, deviceHeight) > maxOuterHeight
  ) {
    width -= 1;
  }
  return Math.max(1, width);
}
