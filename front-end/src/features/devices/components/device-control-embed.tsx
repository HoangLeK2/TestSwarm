'use client';

import { useMemo } from 'react';
import { useDeviceFarm } from '../hooks/use-device-farm';
import { DeviceTile } from './device-tile';

type Props = {
  initialSerial: string;
  compact?: boolean;
  hideStepMonitor?: boolean;
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

export function DeviceControlEmbed({
  initialSerial,
  compact = true,
  hideStepMonitor = false,
  onTap,
  onSwipe,
  onDragGesture,
}: Props) {
  const {
    devices,
    logs,
    modes,
    wsSend,
    handleToggleMode,
    handleRestart,
    error
  } = useDeviceFarm();

  const activeDevices = devices.filter(
    (d) => d.state && !['DISCONNECTED', 'DEAD'].includes(d.state.toUpperCase())
  );

  const selectedDevice = useMemo(
    () =>
      activeDevices.find((d) => d.serial === initialSerial) ??
      activeDevices[0] ??
      null,
    [activeDevices, initialSerial]
  );

  const mode = selectedDevice ? (modes[selectedDevice.serial] ?? 'tap') : 'tap';

  if (error) {
    return (
      <div className="rounded border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
        {error}
      </div>
    );
  }

  if (activeDevices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-8 text-center">
        <p className="text-xs text-muted-foreground">Chưa có thiết bị hoạt động</p>
      </div>
    );
  }

  if (!selectedDevice) {
    return (
      <div className="rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
        Thiết bị đã chọn chưa kết nối. Chọn thiết bị khác trong danh sách campaign.
      </div>
    );
  }

  return (
    <div className={compact ? 'w-full min-w-0 max-w-full' : ''}>
      {selectedDevice.serial !== initialSerial && (
        <p className="mb-1 text-[10px] text-muted-foreground">
          Thiết bị {initialSerial} chưa online — đang hiển thị: {selectedDevice.serial}
        </p>
      )}
      <DeviceTile
        device={selectedDevice}
        logLines={compact ? [] : logs[selectedDevice.serial] ?? []}
        mode={mode}
        wsSend={wsSend}
        onToggleMode={handleToggleMode}
        onRestart={handleRestart}
        onTap={onTap ? (rx, ry) => onTap(selectedDevice.serial, rx, ry) : undefined}
        onSwipe={
          onSwipe
            ? (rx1, ry1, rx2, ry2, ms) => onSwipe(selectedDevice.serial, rx1, ry1, rx2, ry2, ms)
            : undefined
        }
        onDragGesture={
          onDragGesture
            ? (rx1, ry1, rx2, ry2, ms) => onDragGesture(selectedDevice.serial, rx1, ry1, rx2, ry2, ms)
            : undefined
        }
        compact={compact}
        hideStepMonitor={hideStepMonitor}
      />
    </div>
  );
}
