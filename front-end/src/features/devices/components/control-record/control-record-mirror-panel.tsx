'use client';

import { forwardRef, type MutableRefObject } from 'react';
import { Circle, Play, Plus, Square } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { Device } from '@/features/devices/types';
import type { DeviceOpsConfig } from '../device-ops-rail';

import { ControlRecordMirror } from './control-record-mirror';
import type { RegionSelect } from '../device-screen';
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
  /** Grabber for the on-screen frame — used when cropping a tap_image template. */
  captureFrameRef?: MutableRefObject<(() => string | null) | null>;
  /** Drag-to-select a region on the mirror (tap_image crop). */
  regionSelect?: RegionSelect;
  hasMultiFollowers: boolean;
  multiFocusMode: boolean;
  selectedMultiFollowerDevices: Device[];
  onPromoteFollower: (serial: string) => void;
  recording: boolean;
  onToggleRecording: () => void;
  onOpenPlayer: () => void;
  onOpenStepPicker: () => void;
  fillWidth?: boolean;
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
    captureFrameRef,
    regionSelect,
    hasMultiFollowers,
    multiFocusMode,
    selectedMultiFollowerDevices,
    onPromoteFollower,
    recording,
    onToggleRecording,
    onOpenPlayer,
    onOpenStepPicker,
    fillWidth = false,
    labels
  },
  ref
) {
  return (
    <div
      ref={ref}
      className={cn(
        'flex min-h-0 flex-col overflow-hidden bg-muted/20',
        multiFocusMode || fillWidth
          ? 'min-w-0 flex-1'
          : 'w-[clamp(360px,34vw,470px)] shrink-0 border-r border-border/60',
        fillWidth && !multiFocusMode && 'h-full border-r-0'
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
                captureFrameRef={captureFrameRef}
                regionSelect={regionSelect}
              />
            }
            devices={selectedMultiFollowerDevices}
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
              captureFrameRef={captureFrameRef}
              regionSelect={regionSelect}
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
