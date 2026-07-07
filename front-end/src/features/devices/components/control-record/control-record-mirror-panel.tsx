'use client';

import { forwardRef } from 'react';
import { Circle, Play, Plus, Square } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { Device } from '@/features/devices/types';
import type { DeviceOpsConfig } from '../device-ops-rail';

import { ControlRecordMirror } from './control-record-mirror';
import { MirrorPhonePlaceholder } from './mirror-phone-placeholder';
import { MultiDeviceStage } from './multi-device-stage';

type MirrorInputLockState = {
  hideControls: boolean;
  readOnlyPreview: boolean;
};

type ControlRecordMirrorPanelLabels = {
  startRecording: string;
  stopRecording: string;
  tryRun: string;
  openPicker: string;
  selectDevice: string;
};

type ControlRecordMirrorPanelProps = {
  selectedDevice: Device | null | undefined;
  logsBySerial: Record<string, string[] | undefined>;
  wsMode: 'tap' | 'swipe';
  wsSend: (obj: object) => void;
  onToggleMode: (serial: string) => void;
  onRestart: (serial: string) => void;
  onTap: (rx: number, ry: number) => void;
  onSwipe:
    | ((
        rx1: number,
        ry1: number,
        rx2: number,
        ry2: number,
        durationMs: number
      ) => void)
    | undefined;
  highlightBounds: [number, number, number, number] | null;
  mirrorInputLocked: MirrorInputLockState;
  canExecuteDevice: boolean;
  onTakeControl: () => void;
  deviceOps: DeviceOpsConfig | undefined;
  hasMultiFollowers: boolean;
  multiFocusMode: boolean;
  selectedMultiFollowerDevices: Device[];
  onPromoteFollower: (serial: string) => void;
  recording: boolean;
  onToggleRecording: () => void;
  onOpenPlayer: () => void;
  onOpenStepPicker: () => void;
  labels: ControlRecordMirrorPanelLabels;
};

export const ControlRecordMirrorPanel = forwardRef<
  HTMLDivElement,
  ControlRecordMirrorPanelProps
>(function ControlRecordMirrorPanel(
  {
    selectedDevice,
    logsBySerial,
    wsMode,
    wsSend,
    onToggleMode,
    onRestart,
    onTap,
    onSwipe,
    highlightBounds,
    mirrorInputLocked,
    canExecuteDevice,
    onTakeControl,
    deviceOps,
    hasMultiFollowers,
    multiFocusMode,
    selectedMultiFollowerDevices,
    onPromoteFollower,
    recording,
    onToggleRecording,
    onOpenPlayer,
    onOpenStepPicker,
    labels
  },
  ref
) {
  return (
    <div
      ref={ref}
      className={cn(
        'flex min-h-0 flex-col overflow-hidden bg-muted/20',
        multiFocusMode
          ? 'min-w-0 flex-1'
          : 'w-[clamp(300px,30vw,360px)] shrink-0 border-r border-border/60'
      )}
    >
      {selectedDevice ? (
        hasMultiFollowers ? (
          <MultiDeviceStage
            mode={multiFocusMode ? 'focus' : 'edit'}
            toolbar={
              multiFocusMode ? (
                <div className='flex shrink-0 items-center gap-2 border-b border-border/60 bg-background/90 px-3 py-1.5'>
                  <Button
                    size='sm'
                    variant={recording ? 'destructive' : 'default'}
                    className='h-7 gap-1.5 px-2.5 text-xs'
                    onClick={onToggleRecording}
                  >
                    {recording ? (
                      <Square className='size-3.5' />
                    ) : (
                      <Circle className='size-3.5 fill-current' />
                    )}
                    {recording ? labels.stopRecording : labels.startRecording}
                  </Button>
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-7 gap-1.5 px-2.5 text-xs'
                    onClick={onOpenPlayer}
                    disabled={
                      (selectedDevice.state || '').replace(
                        'DeviceState.',
                        ''
                      ) === 'BUSY'
                    }
                  >
                    <Play className='size-3.5' />
                    {labels.tryRun}
                  </Button>
                  <div className='flex-1' />
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-7 gap-1.5 px-2.5 text-xs'
                    onClick={onOpenStepPicker}
                  >
                    <Plus className='size-3.5' />
                    {labels.openPicker}
                  </Button>
                </div>
              ) : undefined
            }
            primaryMirror={
              <ControlRecordMirror
                device={selectedDevice}
                logLines={logsBySerial[selectedDevice.serial] ?? []}
                mode={wsMode}
                wsSend={wsSend}
                onToggleMode={onToggleMode}
                onRestart={onRestart}
                onTap={onTap}
                onSwipe={onSwipe}
                highlightBounds={highlightBounds}
                hideControls={mirrorInputLocked.hideControls}
                hideDeviceFunctions={mirrorInputLocked.hideControls}
                readOnlyPreview={mirrorInputLocked.readOnlyPreview}
                canTakeControl={canExecuteDevice}
                onTakeControl={onTakeControl}
                mirrorSize={multiFocusMode ? 'multiFocus' : 'multiCompact'}
                deviceOps={deviceOps}
              />
            }
            devices={selectedMultiFollowerDevices}
            wsMode={wsMode}
            wsSend={wsSend}
            onPromote={onPromoteFollower}
          />
        ) : (
          <div className='flex min-h-0 flex-1 flex-col items-center justify-center overflow-hidden'>
            <ControlRecordMirror
              device={selectedDevice}
              logLines={logsBySerial[selectedDevice.serial] ?? []}
              mode={wsMode}
              wsSend={wsSend}
              onToggleMode={onToggleMode}
              onRestart={onRestart}
              onTap={onTap}
              onSwipe={onSwipe}
              highlightBounds={highlightBounds}
              hideControls={mirrorInputLocked.hideControls}
              hideDeviceFunctions={mirrorInputLocked.hideControls}
              readOnlyPreview={mirrorInputLocked.readOnlyPreview}
              canTakeControl={canExecuteDevice}
              onTakeControl={onTakeControl}
              deviceOps={deviceOps}
            />
          </div>
        )
      ) : (
        <div className='flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center'>
          <MirrorPhonePlaceholder />
          <p className='text-xs text-muted-foreground'>{labels.selectDevice}</p>
        </div>
      )}
    </div>
  );
});
