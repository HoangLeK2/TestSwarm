'use client';

import { useState, useCallback, useMemo } from 'react';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { DeviceScreen } from './device-screen';
import { DeviceControls } from './device-controls';
import { DeviceSTFPanel } from './device-stf-panel';
import { DeviceStepMonitor } from './device-step-monitor';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Android } from '@/registry/magicui/android';
import { useTranslations } from 'next-intl';

interface DeviceTileProps {
  device: Device;
  logLines: string[];
  mode: 'tap' | 'swipe';
  wsSend: (obj: object) => void;
  onToggleMode: (serial: string) => void;
  onRestart: (serial: string) => void;
  onTap?: (rx: number, ry: number) => void;
  onSwipe?: (rx1: number, ry1: number, rx2: number, ry2: number, durationMs: number) => void;
  onDragGesture?: (rx1: number, ry1: number, rx2: number, ry2: number, durationMs: number) => void;
  highlightBounds?: [number, number, number, number] | null;
  /** Thu nhỏ khung màn + nút — dùng trong dialog kịch bản */
  compact?: boolean;
  /** Ẩn nút Steps trong header (khi steps đã hiện panel riêng bên cạnh) */
  hideStepMonitor?: boolean;
  /** Ẩn toàn bộ header tên/model/serial ở đầu thẻ */
  hideHeader?: boolean;
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
}: DeviceTileProps) {
  const t = useTranslations('devicesFarm');
  const id = serialToId(device.serial);
  const isActive =
    device.state && !['DISCONNECTED', 'DEAD'].includes(device.state.toUpperCase());

  const [gestureMode, setGestureMode] = useState<'tap' | 'swipe' | 'double_tap' | 'drag'>('tap');

  const screenRatio = useMemo(() => {
    const sw = device.screen_width || 1080;
    const sh = device.screen_height || 1920;
    return sh > 0 ? sw / sh : 9 / 19;
  }, [device.screen_width, device.screen_height]);

  const mockupSize = useMemo(() => {
    const w = compact ? 250 : 310;
    const h = Math.round(w * (830 / 378));
    return { width: w, height: h };
  }, [compact]);

  const handlePinch = useCallback((scale: number) => {
    const dw = device.screen_width || 1080;
    const dh = device.screen_height || 1920;
    wsSend({ type: 'pinch', serial: device.serial, cx: Math.round(dw / 2), cy: Math.round(dh / 2), scale, ms: 400 });
  }, [wsSend, device.serial, device.screen_width, device.screen_height]);

  const handleSwipeExt = useCallback((direction: 'up' | 'down' | 'left' | 'right') => {
    wsSend({ type: 'swipe_ext', serial: device.serial, direction, scale: 0.4, ms: 500 });
  }, [wsSend, device.serial]);

  const handleScreenOn  = useCallback(() => wsSend({ type: 'screen_on',  serial: device.serial }), [wsSend, device.serial]);
  const handleScreenOff = useCallback(() => wsSend({ type: 'screen_off', serial: device.serial }), [wsSend, device.serial]);
  const handleUnlock    = useCallback(() => wsSend({ type: 'unlock',     serial: device.serial }), [wsSend, device.serial]);

  return (
    <Card
      id={`tile-${id}`}
      data-serial={device.serial}
      className='flex h-full flex-col border-0 bg-transparent shadow-none overflow-visible'
    >
      {!hideHeader && (
        <CardHeader className={compact ? 'border-b border-border/60 px-2 py-2' : 'border-b border-border/60 px-4 py-3'}>
          <div className='flex flex-col gap-1'>
            <CardTitle className='flex items-center justify-between gap-2 text-xs'>
              <span className='truncate font-medium text-foreground'>
                {device.brand} {device.model}
              </span>
              {!hideStepMonitor && (
                <DeviceStepMonitor
                  serial={device.serial}
                  isBusy={device.state?.toUpperCase() === 'BUSY'}
                />
              )}
            </CardTitle>
            <span className='font-mono text-[10px] text-muted-foreground'>
              {device.serial}
            </span>
          </div>
        </CardHeader>
      )}
      <CardContent className={compact ? 'flex flex-1 flex-col gap-1.5 px-2 pb-2 pt-2' : `flex flex-1 flex-col gap-2 px-3 pb-3 ${hideHeader ? 'pt-2' : 'pt-3'}`}>
        <div className='flex flex-col items-center gap-2'>
          <div className='mx-auto'>
            <Android
              width={mockupSize.width}
              height={mockupSize.height}
              screenRatio={screenRatio}
            >
              <div className='h-full w-full'>
                {isActive ? (
                  <DeviceScreen
                    device={device}
                    wsSend={wsSend}
                    mode={mode}
                    onTap={onTap}
                    onSwipe={onSwipe}
                    onDragGesture={onDragGesture}
                    highlightBounds={highlightBounds}
                    gestureMode={gestureMode}
                  />
                ) : (
                  <div className='flex h-full w-full items-center justify-center bg-zinc-900 text-[11px] text-muted-foreground'>
                    {t('deviceInactive')}
                  </div>
                )}
              </div>
            </Android>
          </div>
        </div>
        <DeviceControls
          serial={device.serial}
          mode={mode}
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
        {isActive && <DeviceSTFPanel serial={device.serial} />}
      </CardContent>
    </Card>
  );
}

