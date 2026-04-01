'use client';

import {
  ArrowLeft,
  Home,
  MousePointerClick,
  MoveHorizontal,
  Power,
  RotateCw,
  ZoomIn,
  ZoomOut,
  Hand,
  MousePointer2,
} from 'lucide-react';
import { serialToId } from '../helpers';
import { Button } from '@/components/ui/button';
import { useTranslations } from 'next-intl';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface DeviceControlsProps {
  serial: string;
  mode: 'tap' | 'swipe';
  onToggleMode: () => void;
  onKey: (key: string) => void;
  onRestart: () => void;
  compact?: boolean;
  gestureMode?: 'tap' | 'swipe' | 'double_tap' | 'drag';
  onGestureMode?: (m: 'tap' | 'swipe' | 'double_tap' | 'drag') => void;
  onPinch?: (scale: number) => void;
}

export function DeviceControls({
  serial,
  mode,
  onToggleMode,
  onKey,
  onRestart,
  compact = false,
  gestureMode,
  onGestureMode,
  onPinch,
}: DeviceControlsProps) {
  const t = useTranslations('devicesControlRecord.controls');
  const id = serialToId(serial);

  const ModeIcon = mode === 'tap' ? MousePointerClick : MoveHorizontal;
  const btn = compact
    ? 'min-h-7 gap-1 px-2 text-[11px] h-7'
    : 'min-h-9 gap-1.5';
  const icon = compact ? 'size-3 shrink-0' : 'size-3.5 shrink-0';

  return (
    <div className={compact ? 'mt-0.5 flex flex-wrap gap-1' : 'mt-1 flex flex-wrap gap-2'}>
      <Button
        id={`mode-${id}`}
        size='sm'
        variant={mode === 'tap' ? 'secondary' : 'outline'}
        className={btn}
        onClick={onToggleMode}
      >
        <ModeIcon className={icon} aria-hidden />
        {mode === 'tap' ? t('tapMode') : t('swipeMode')}
      </Button>

      {/* Double Tap mode toggle */}
      {onGestureMode && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant={gestureMode === 'double_tap' ? 'secondary' : 'outline'}
              className={btn}
              onClick={() => onGestureMode(gestureMode === 'double_tap' ? 'tap' : 'double_tap')}
            >
              <MousePointer2 className={icon} aria-hidden />
              {compact ? '2×' : 'Double tap'}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            Click on screen sends double tap (or always double-click on screen)
          </TooltipContent>
        </Tooltip>
      )}

      {/* Drag mode toggle */}
      {onGestureMode && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant={gestureMode === 'drag' ? 'secondary' : 'outline'}
              className={btn}
              onClick={() => onGestureMode(gestureMode === 'drag' ? 'tap' : 'drag')}
            >
              <Hand className={icon} aria-hidden />
              {compact ? 'Drag' : 'Drag'}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            Swipe sends drag-and-drop (long press + move)
          </TooltipContent>
        </Tooltip>
      )}

      {/* Pinch In / Out */}
      {onPinch && (
        <>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size='sm' variant='outline' className={btn} onClick={() => onPinch(2.0)}>
                <ZoomIn className={icon} aria-hidden />
                {!compact && 'Zoom in'}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='top' className='text-xs'>Pinch out (zoom in) at screen center</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size='sm' variant='outline' className={btn} onClick={() => onPinch(0.5)}>
                <ZoomOut className={icon} aria-hidden />
                {!compact && 'Zoom out'}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='top' className='text-xs'>Pinch in (zoom out) at screen center</TooltipContent>
          </Tooltip>
        </>
      )}

      <Button
        size='sm'
        variant='outline'
        className={btn}
        onClick={() => onKey('home')}
      >
        <Home className={icon} aria-hidden />
        {t('home')}
      </Button>
      <Button
        size='sm'
        variant='outline'
        className={btn}
        onClick={() => onKey('back')}
      >
        <ArrowLeft className={icon} aria-hidden />
        {t('back')}
      </Button>
      <Button
        size='sm'
        variant='outline'
        className={btn}
        onClick={() => onKey('power')}
      >
        <Power className={icon} aria-hidden />
        {t('power')}
      </Button>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            size='sm'
            variant='ghost'
            className={`${btn} text-muted-foreground hover:text-foreground`}
            onClick={onRestart}
          >
            <RotateCw className={icon} aria-hidden />
            {t('restart')}
          </Button>
        </TooltipTrigger>
        <TooltipContent side='top' className='max-w-xs text-xs'>
          {t('restartTitle')}
        </TooltipContent>
      </Tooltip>
    </div>
  );
}
