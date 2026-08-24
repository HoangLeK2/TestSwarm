'use client';

import {
  useState,
  useCallback,
  useEffect,
  useMemo,
  type MutableRefObject,
  type ReactNode
} from 'react';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import {
  DeviceScreen,
  type DeviceScreenTransport,
  type RegionSelect
} from './device-screen';
import type { ScrcpyAttachOptions } from '../services/scrcpy-stream';
import type { ScrcpyViewerRole } from '../services/scrcpy-viewer-session';
import {
  resolveDeviceScreenState,
  shouldMountDeviceScreen
} from '../lib/device-tile-stream-policy';
import { DeviceControls } from './device-controls';
import { isControlRecordConnectedDevice } from '../lib/control-record-device-state';
import {
  DeviceStepMonitorButton,
  DeviceStepsSheet
} from './device-step-monitor';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  DeviceAndroidFrame,
  mockupOuterHeightPx
} from './device-android-frame';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';
import type { DeviceOpsConfig } from './device-ops-rail';
import { DeviceLiveInputBar } from './device-live-input';

interface DeviceTileProps {
  device: Device;
  logLines: string[];
  mode: 'tap' | 'swipe';
  wsSend: (obj: object) => void;
  onToggleMode: (serial: string) => void;
  onRestart: (serial: string) => void;
  onTap?: (rx: number, ry: number) => void;
  onSwipe?: (
    rx1: number,
    ry1: number,
    rx2: number,
    ry2: number,
    durationMs: number
  ) => void;
  onDragGesture?: (
    rx1: number,
    ry1: number,
    rx2: number,
    ry2: number,
    durationMs: number
  ) => void;
  highlightBounds?: [number, number, number, number] | null;
  /** Thu nhỏ khung màn + nút — dùng trong dialog kịch bản */
  compact?: boolean;
  /** Ẩn nút Steps trong header (khi steps đã hiện panel riêng bên cạnh) */
  hideStepMonitor?: boolean;
  /** Ẩn toàn bộ header tên/model/serial ở đầu thẻ */
  hideHeader?: boolean;
  /** Ẩn cụm điều khiển phía dưới màn hình thiết bị. */
  hideControls?: boolean;
  /** Ẩn panel chức năng thiết bị (STF panel). */
  hideDeviceFunctions?: boolean;
  /** Chỉ xem, không gửi thao tác điều khiển vào thiết bị. */
  readOnlyPreview?: boolean;
  /** Mockup screen width (px); default 288 / 232 when compact. */
  mockupScreenWidth?: number;
  /** Rail: ẩn pinch zoom + khởi động lại phiên ADB/scrcpy (trang ghi kịch bản). */
  minimalRailControls?: boolean;
  streamFetchPriority?: 'high' | 'low' | 'auto';
  streamTransport?: DeviceScreenTransport;
  /** Grabber for the on-screen frame (tap_image template cropping). */
  captureFrameRef?: MutableRefObject<(() => string | null) | null>;
  /** Drag-to-select a screen region instead of tapping through (tap_image crop). */
  regionSelect?: RegionSelect;
  streamFit?: 'cover' | 'contain';
  scrcpyAttachOptions?: ScrcpyAttachOptions;
  scrcpyViewerRole?: ScrcpyViewerRole;
  /** Opt-in pause for preview callers; defaults to preserving the live screen. */
  streamEnabled?: boolean;
  /** Hide current-app label under the mockup (filmstrip tiles). */
  hideAppCaption?: boolean;
  /** ADB / APK / file ops on the control rail (control-record). */
  deviceOps?: DeviceOpsConfig;
  /** Absolute overlay rendered over the live screen (e.g. busy-state banner). */
  screenOverlay?: ReactNode;
}

export function DeviceTile({
  device,
  logLines,
  mode,
  wsSend,
  onToggleMode,
  onRestart,
  onTap,
  onSwipe,
  onDragGesture,
  highlightBounds,
  compact = false,
  hideStepMonitor = false,
  hideHeader = false,
  hideControls = false,
  hideDeviceFunctions = false,
  readOnlyPreview = false,
  mockupScreenWidth: mockupScreenWidthProp,
  minimalRailControls = false,
  streamFetchPriority = 'auto',
  streamTransport = 'auto',
  captureFrameRef,
  regionSelect,
  streamFit,
  scrcpyAttachOptions,
  scrcpyViewerRole,
  streamEnabled,
  hideAppCaption = false,
  deviceOps,
  screenOverlay
}: DeviceTileProps) {
  const t = useTranslations('devicesFarm');
  const id = serialToId(device.serial);
  const title =
    device.display_name?.trim() ||
    device.name?.trim() ||
    `${device.brand} ${device.model}`.trim() ||
    device.serial;
  const subtitle =
    device.serial !== title
      ? device.serial
      : `${device.brand} ${device.model}`.trim();
  const isActive = isControlRecordConnectedDevice(device);
  const deviceScreenState = resolveDeviceScreenState(isActive, streamEnabled);
  const mountDeviceScreen = shouldMountDeviceScreen(isActive, streamEnabled);

  const [gestureMode, setGestureMode] = useState<
    'tap' | 'swipe' | 'double_tap' | 'drag'
  >('tap');
  const [stepsOpen, setStepsOpen] = useState(false);
  const [streamRenderSize, setStreamRenderSize] = useState<{
    width: number;
    height: number;
  } | null>(null);

  useEffect(() => {
    setStreamRenderSize(null);
  }, [device.serial]);

  /** Screen width inside the mockup (lib adds bezel + side button padding when `frameOnly={false}`). */
  const mockupScreenWidth = useMemo(
    () => mockupScreenWidthProp ?? (compact ? 232 : 288),
    [compact, mockupScreenWidthProp]
  );
  const frameDeviceSize = useMemo(() => {
    const deviceWidth = Number(device.screen_width);
    const deviceHeight = Number(device.screen_height);
    const hasDeviceSize =
      Number.isFinite(deviceWidth) &&
      Number.isFinite(deviceHeight) &&
      deviceWidth > 0 &&
      deviceHeight > 0;
    const streamWidth = Number(streamRenderSize?.width);
    const streamHeight = Number(streamRenderSize?.height);
    const hasStreamSize =
      Number.isFinite(streamWidth) &&
      Number.isFinite(streamHeight) &&
      streamWidth > 0 &&
      streamHeight > 0;

    if (hasDeviceSize) {
      const deviceLandscape = deviceWidth > deviceHeight;
      const streamLandscape = streamWidth > streamHeight;
      if (hasStreamSize && deviceLandscape !== streamLandscape) {
        return { width: deviceHeight, height: deviceWidth };
      }
      return { width: deviceWidth, height: deviceHeight };
    }

    if (hasStreamSize) {
      return { width: streamWidth, height: streamHeight };
    }

    return { width: device.screen_width, height: device.screen_height };
  }, [
    device.screen_height,
    device.screen_width,
    streamRenderSize?.height,
    streamRenderSize?.width
  ]);
  const mirrorRowHeightPx = useMemo(
    () =>
      mockupOuterHeightPx(
        mockupScreenWidth,
        frameDeviceSize.width,
        frameDeviceSize.height
      ),
    [frameDeviceSize.height, frameDeviceSize.width, mockupScreenWidth]
  );
  const studioMirror =
    mockupScreenWidthProp != null && mockupScreenWidthProp <= 260;

  const handlePinch = useCallback(
    (scale: number) => {
      const dw = device.screen_width || 1080;
      const dh = device.screen_height || 1920;
      wsSend({
        type: 'pinch',
        serial: device.serial,
        cx: Math.round(dw / 2),
        cy: Math.round(dh / 2),
        scale,
        ms: 400
      });
    },
    [wsSend, device.serial, device.screen_width, device.screen_height]
  );

  const handleStreamSize = useCallback(
    (size: { width: number; height: number }) => {
      setStreamRenderSize((prev) =>
        prev?.width === size.width && prev?.height === size.height ? prev : size
      );
    },
    []
  );

  const handleSwipeExt = useCallback(
    (direction: 'up' | 'down' | 'left' | 'right') => {
      wsSend({
        type: 'swipe_ext',
        serial: device.serial,
        direction,
        scale: 0.4,
        ms: 500
      });
    },
    [wsSend, device.serial]
  );

  const handleScreenOn = useCallback(
    () => wsSend({ type: 'screen_on', serial: device.serial }),
    [wsSend, device.serial]
  );
  const handleScreenOff = useCallback(
    () => wsSend({ type: 'screen_off', serial: device.serial }),
    [wsSend, device.serial]
  );
  const handleUnlock = useCallback(
    () => wsSend({ type: 'unlock', serial: device.serial }),
    [wsSend, device.serial]
  );

  const [liveInputOpen, setLiveInputOpen] = useState(false);
  const liveInputConfig = useMemo(
    () =>
      !compact
        ? {
            wsSend,
            disabled: readOnlyPreview,
            open: liveInputOpen,
            onOpenChange: setLiveInputOpen
          }
        : undefined,
    [compact, wsSend, readOnlyPreview, liveInputOpen]
  );

  return (
    <Card
      id={`tile-${id}`}
      data-serial={device.serial}
      className='flex h-full flex-col overflow-visible border-0 bg-transparent shadow-none'
    >
      {!hideHeader && (
        <CardHeader
          className={
            compact
              ? 'border-b border-border/60 px-2 py-2'
              : 'border-b border-border/60 px-4 py-3'
          }
        >
          <div className='flex flex-col gap-1'>
            <CardTitle className='flex items-center justify-between gap-2 text-xs'>
              <span className='truncate font-medium text-foreground'>
                {title}
              </span>
              {!hideStepMonitor && (
                <DeviceStepMonitorButton
                  serial={device.serial}
                  isBusy={device.state?.toUpperCase() === 'BUSY'}
                  onOpen={() => setStepsOpen(true)}
                />
              )}
            </CardTitle>
            {subtitle && (
              <span className='truncate font-mono text-[10px] text-muted-foreground'>
                {subtitle}
              </span>
            )}
          </div>
        </CardHeader>
      )}
      <CardContent
        className={
          compact
            ? 'flex flex-1 flex-col gap-1.5 px-2 pb-2 pt-2'
            : cn(
                'flex flex-1 flex-col',
                studioMirror
                  ? 'gap-1 px-2 pb-2 pt-1.5'
                  : `gap-2 px-3 pb-3 ${hideHeader ? 'pt-2' : 'pt-3'}`
              )
        }
      >
        <div className='flex flex-col items-center gap-2'>
          <div className='mx-auto flex w-fit max-w-full flex-col items-center gap-1'>
            <div
              className={cn(
                compact
                  ? 'flex flex-col items-center gap-2'
                  : 'inline-flex flex-col items-stretch gap-1'
              )}
            >
              <div
                className={cn(
                  compact
                    ? 'flex flex-col items-center gap-2'
                    : 'inline-flex items-stretch gap-2.5'
                )}
                style={compact ? undefined : { height: mirrorRowHeightPx }}
              >
                <DeviceAndroidFrame
                  screenWidth={mockupScreenWidth}
                  deviceWidth={frameDeviceSize.width}
                  deviceHeight={frameDeviceSize.height}
                  className='shrink-0'
                >
                  <div className='relative flex h-full min-h-0 w-full flex-col'>
                    {mountDeviceScreen ? (
                      <DeviceScreen
                        device={device}
                        wsSend={wsSend}
                        mode={mode}
                        onTap={onTap}
                        onSwipe={onSwipe}
                        onDragGesture={onDragGesture}
                        highlightBounds={highlightBounds}
                        gestureMode={gestureMode}
                        captionBelowFrame
                        interactive={!readOnlyPreview}
                        streamFetchPriority={streamFetchPriority}
                        streamTransport={streamTransport}
                        captureFrameRef={captureFrameRef}
                        regionSelect={regionSelect}
                        streamFit={streamFit}
                        onStreamSize={handleStreamSize}
                        scrcpyAttachOptions={scrcpyAttachOptions}
                        scrcpyViewerRole={scrcpyViewerRole}
                      />
                    ) : (
                      <div className='flex h-full w-full items-center justify-center bg-zinc-900 text-[11px] text-muted-foreground'>
                        {t(
                          deviceScreenState === 'paused'
                            ? 'previewDeferred'
                            : 'deviceInactive'
                        )}
                      </div>
                    )}
                    {mountDeviceScreen ? screenOverlay : null}
                  </div>
                </DeviceAndroidFrame>
                {!hideControls && !compact ? (
                  <DeviceControls
                    serial={device.serial}
                    mode={mode}
                    layout='rail'
                    className='h-full min-h-0 self-stretch'
                    onToggleMode={() => onToggleMode(device.serial)}
                    onKey={(key) =>
                      wsSend({ type: 'key', serial: device.serial, key })
                    }
                    onRestart={() => onRestart(device.serial)}
                    gestureMode={gestureMode}
                    onGestureMode={setGestureMode}
                    onPinch={minimalRailControls ? undefined : handlePinch}
                    onSwipeExt={handleSwipeExt}
                    onScreenOn={handleScreenOn}
                    onScreenOff={handleScreenOff}
                    onUnlock={handleUnlock}
                    hidePinch={minimalRailControls}
                    hideRestart={minimalRailControls}
                    deviceOps={deviceOps}
                    liveInput={liveInputConfig}
                  />
                ) : null}
              </div>
              {liveInputConfig ? (
                <DeviceLiveInputBar
                  serial={device.serial}
                  wsSend={wsSend}
                  disabled={readOnlyPreview}
                  open={liveInputOpen}
                  onOpenChange={setLiveInputOpen}
                />
              ) : null}
            </div>
            {isActive && !hideAppCaption && (
              <p
                className='mx-auto max-w-[min(320px,90vw)] truncate px-1 text-center font-mono text-[10px] text-muted-foreground'
                id={`app-${id}`}
                title={device.current_app ?? ''}
              >
                {(device.current_app ?? '—').split('.').slice(-1)[0] ?? '—'}
              </p>
            )}
          </div>
        </div>
        {!hideControls && compact ? (
          <DeviceControls
            serial={device.serial}
            mode={mode}
            layout='below'
            onToggleMode={() => onToggleMode(device.serial)}
            onKey={(key) => wsSend({ type: 'key', serial: device.serial, key })}
            onRestart={() => onRestart(device.serial)}
            compact={compact}
            gestureMode={gestureMode}
            onGestureMode={setGestureMode}
            onPinch={handlePinch}
            onSwipeExt={handleSwipeExt}
            onScreenOn={handleScreenOn}
            onScreenOff={handleScreenOff}
            onUnlock={handleUnlock}
          />
        ) : null}
        {/* {isActive && !hideDeviceFunctions && <DeviceSTFPanel serial={device.serial} />} */}
      </CardContent>
      {!hideStepMonitor ? (
        <DeviceStepsSheet
          serial={device.serial}
          open={stepsOpen}
          onOpenChange={setStepsOpen}
        />
      ) : null}
    </Card>
  );
}
