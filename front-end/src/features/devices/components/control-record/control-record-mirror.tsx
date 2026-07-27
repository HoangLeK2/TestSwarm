'use client';

import { memo, useMemo } from 'react';
import type { Device } from '../../types';
import { DeviceTile } from '../device-tile';
import type { DeviceOpsConfig } from '../device-ops-rail';
import { ManualControlBlockedBanner } from './manual-control-blocked-banner';
import { isManualControlBlockedByAutomation } from '../../lib/control-record-device-state';
import type { ScrcpyAttachOptions } from '../../services/scrcpy-stream';

type Props = {
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
  highlightBounds?: [number, number, number, number] | null;
  hideControls?: boolean;
  hideDeviceFunctions?: boolean;
  readOnlyPreview?: boolean;
  canTakeControl?: boolean;
  onTakeControl?: () => void;
  /** Mirror scale in multi-phone layouts. */
  mirrorSize?: 'default' | 'multiCompact' | 'multiFocus';
  deviceOps?: DeviceOpsConfig;
};

function controlScrcpyInt(
  name: string,
  fallback: number,
  min: number,
  max: number
) {
  const raw = Number(process.env[name] ?? fallback);
  if (!Number.isFinite(raw)) return fallback;
  return Math.max(min, Math.min(max, Math.round(raw)));
}

const CONTROL_RECORD_SCRCPY_OPTIONS: ScrcpyAttachOptions = {
  enableControl: true,
  maxFps: controlScrcpyInt(
    'NEXT_PUBLIC_DEVICE_FARM_CONTROL_SCRCPY_FPS',
    10,
    4,
    15
  ),
  maxWidth: controlScrcpyInt(
    'NEXT_PUBLIC_DEVICE_FARM_CONTROL_SCRCPY_WIDTH',
    480,
    360,
    720
  ),
  bitrate: controlScrcpyInt(
    'NEXT_PUBLIC_DEVICE_FARM_CONTROL_SCRCPY_BITRATE',
    800_000,
    300_000,
    2_000_000
  )
};

function isManualControlBlocked(device: Device): boolean {
  return isManualControlBlockedByAutomation(device);
}

function deviceMirrorPropsEqual(prev: Props, next: Props) {
  if (prev.mode !== next.mode) return false;
  if (prev.onTap !== next.onTap) return false;
  if (prev.onSwipe !== next.onSwipe) return false;
  if (prev.wsSend !== next.wsSend) return false;
  if (prev.onToggleMode !== next.onToggleMode) return false;
  if (prev.onRestart !== next.onRestart) return false;
  if (prev.hideControls !== next.hideControls) return false;
  if (prev.hideDeviceFunctions !== next.hideDeviceFunctions) return false;
  if (prev.readOnlyPreview !== next.readOnlyPreview) return false;
  if (prev.canTakeControl !== next.canTakeControl) return false;
  if (prev.onTakeControl !== next.onTakeControl) return false;
  if (prev.mirrorSize !== next.mirrorSize) return false;
  if (prev.deviceOps !== next.deviceOps) return false;
  if (prev.highlightBounds !== next.highlightBounds) {
    const pb = prev.highlightBounds;
    const nb = next.highlightBounds;
    if (pb == null || nb == null) return pb === nb;
    if (
      pb[0] !== nb[0] ||
      pb[1] !== nb[1] ||
      pb[2] !== nb[2] ||
      pb[3] !== nb[3]
    ) {
      return false;
    }
  }
  const pd = prev.device;
  const nd = next.device;
  return (
    pd.serial === nd.serial &&
    pd.state === nd.state &&
    pd.brand === nd.brand &&
    pd.model === nd.model &&
    pd.battery === nd.battery &&
    pd.current_app === nd.current_app &&
    pd.screen_width === nd.screen_width &&
    pd.screen_height === nd.screen_height &&
    pd.scenario_active === nd.scenario_active &&
    pd.manual_takeover_active === nd.manual_takeover_active &&
    pd.relay_scrcpy_enabled === nd.relay_scrcpy_enabled
  );
}

/** Isolated device mirror — step editor updates must not re-render this column. */
export const ControlRecordMirror = memo(function ControlRecordMirror({
  device,
  logLines,
  mode,
  wsSend,
  onToggleMode,
  onRestart,
  onTap,
  onSwipe,
  highlightBounds,
  hideControls,
  hideDeviceFunctions,
  readOnlyPreview,
  canTakeControl = false,
  onTakeControl,
  mirrorSize = 'default',
  deviceOps
}: Props) {
  const mockupScreenWidth =
    mirrorSize === 'multiFocus'
      ? 236
      : mirrorSize === 'multiCompact'
        ? 252
        : 262;
  const compactPadding = mirrorSize !== 'default';
  const compactOverlay = mirrorSize !== 'default';

  const manualControlBlocked = isManualControlBlocked(device);
  const screenOverlay = useMemo(() => {
    if (!manualControlBlocked) {
      return undefined;
    }
    return (
      <ManualControlBlockedBanner
        compact={compactOverlay}
        canTakeControl={canTakeControl}
        onTakeControl={onTakeControl ?? (() => {})}
      />
    );
  }, [canTakeControl, compactOverlay, manualControlBlocked, onTakeControl]);

  return (
    <div className='flex min-h-0 w-full flex-1 flex-col'>
      <div
        className={
          compactPadding
            ? 'flex w-full min-w-0 flex-1 justify-center px-2 pt-2'
            : 'flex w-full flex-1 justify-center px-3 pt-3'
        }
      >
        <div className='mx-auto flex w-fit max-w-full flex-col items-stretch'>
          <DeviceTile
            device={device}
            logLines={logLines}
            mode={mode}
            wsSend={wsSend}
            onToggleMode={onToggleMode}
            onRestart={onRestart}
            onTap={onTap}
            onSwipe={onSwipe}
            highlightBounds={highlightBounds}
            hideHeader
            hideStepMonitor
            minimalRailControls
            hideControls={hideControls}
            hideDeviceFunctions={hideDeviceFunctions}
            readOnlyPreview={readOnlyPreview}
            mockupScreenWidth={mockupScreenWidth}
            streamFetchPriority='high'
            streamTransport='h264-only'
            scrcpyAttachOptions={CONTROL_RECORD_SCRCPY_OPTIONS}
            hideAppCaption={compactPadding}
            deviceOps={deviceOps}
            screenOverlay={screenOverlay}
          />
        </div>
      </div>
    </div>
  );
}, deviceMirrorPropsEqual);
