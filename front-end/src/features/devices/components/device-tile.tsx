'use client';

import { useState, useCallback } from 'react';
import type { Device } from '../types';
import { serialToId } from '../helpers';
import { DeviceScreen } from './device-screen';
import { DeviceControls } from './device-controls';
import { DeviceSTFPanel } from './device-stf-panel';
import { DeviceStepMonitor } from './device-step-monitor';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useTranslations } from 'next-intl';

interface DeviceTileProps {
  device: Device;
  logLines: string[];
  mode: 'tap' | 'swipe';
  wsSend: (obj: object) => void;
  onToggleMode: (serial: string) => void;
  onRestart: (serial: string) => void;
  onTap?: (rx: number, ry: number) => void;
  highlightBounds?: [number, number, number, number] | null;
  /** Thu nhỏ khung màn + nút — dùng trong dialog kịch bản */
  compact?: boolean;
  /** Ẩn nút Steps trong header (khi steps đã hiện panel riêng bên cạnh) */
  hideStepMonitor?: boolean;
}

export function DeviceTile({
  device,
  logLines,
  mode,
  wsSend,
  onToggleMode,
  onRestart,
  onTap,
  highlightBounds,
  compact = false,
  hideStepMonitor = false,
}: DeviceTileProps) {
  const t = useTranslations('devicesFarm');
  const id = serialToId(device.serial);
  const isActive =
    device.state && !['DISCONNECTED', 'DEAD'].includes(device.state.toUpperCase());

  const [gestureMode, setGestureMode] = useState<'tap' | 'swipe' | 'double_tap' | 'drag'>('tap');

  const handlePinch = useCallback((scale: number) => {
    const dw = device.screen_width || 1080;
    const dh = device.screen_height || 1920;
    wsSend({ type: 'pinch', serial: device.serial, cx: Math.round(dw / 2), cy: Math.round(dh / 2), scale, ms: 400 });
  }, [wsSend, device.serial, device.screen_width, device.screen_height]);

  return (
    <Card
      id={`tile-${id}`}
      data-serial={device.serial}
      className='flex h-full flex-col border-border bg-card shadow-sm overflow-hidden'
    >
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
      <CardContent className={compact ? 'flex flex-1 flex-col gap-1.5 px-2 pb-2 pt-2' : 'flex flex-1 flex-col gap-2 px-3 pb-3 pt-3'}>
        <div className='flex flex-col items-center gap-2'>
          <div className={compact ? 'relative w-full max-w-[220px]' : 'relative w-full max-w-[260px]'}>
            <div className='pointer-events-none absolute inset-0 rounded-[1.75rem] border border-border/40 bg-gradient-to-b from-background/40 to-background/80 shadow-[0_18px_40px_rgba(15,23,42,0.55)]' />
            <div className={`relative mx-auto flex aspect-[9/19] w-full items-center justify-center rounded-[1.5rem] border border-border/80 bg-black px-1.5 pb-2 pt-3 ${compact ? 'my-1 max-w-[200px]' : 'my-2 max-w-[240px]'}`}>
              <div className='pointer-events-none absolute left-1/2 top-1.5 flex -translate-x-1/2 items-center gap-1 rounded-full bg-zinc-900 px-4 py-1 shadow-sm'>
                <span className='h-1.5 w-10 rounded-full bg-zinc-700' />
                <span className='h-2 w-2 rounded-full bg-zinc-600' />
              </div>
              <div className='relative h-full w-full overflow-hidden rounded-xl bg-black'>
                {isActive ? (
                  <DeviceScreen
                    device={device}
                    wsSend={wsSend}
                    mode={mode}
                    onTap={onTap}
                    highlightBounds={highlightBounds}
                    gestureMode={gestureMode}
                  />
                ) : (
                  <div className='flex h-full w-full items-center justify-center bg-zinc-900 text-[11px] text-muted-foreground'>
                    {t('deviceInactive')}
                  </div>
                )}
              </div>
            </div>
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
        />
        {isActive && <DeviceSTFPanel serial={device.serial} />}
      </CardContent>
    </Card>
  );
}

