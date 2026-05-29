'use client';

import type { ReactNode } from 'react';
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
  Sun,
  Moon,
  LockOpen,
  ChevronsUp,
  ChevronsDown,
  ChevronsLeft,
  ChevronsRight
} from 'lucide-react';
import { serialToId } from '../helpers';
import { Button } from '@/components/ui/button';
import { useTranslations } from 'next-intl';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

interface DeviceControlsProps {
  serial: string;
  mode: 'tap' | 'swipe';
  onToggleMode: () => void;
  onKey: (key: string) => void;
  onRestart: () => void;
  compact?: boolean;
  /** Full-width wrap below phone (grid tiles). */
  layout?: 'below' | 'rail';
  gestureMode?: 'tap' | 'swipe' | 'double_tap' | 'drag';
  onGestureMode?: (m: 'tap' | 'swipe' | 'double_tap' | 'drag') => void;
  onPinch?: (scale: number) => void;
  onSwipeExt?: (direction: 'up' | 'down' | 'left' | 'right') => void;
  onScreenOn?: () => void;
  onScreenOff?: () => void;
  onUnlock?: () => void;
  className?: string;
  /** Hide pinch zoom in/out on the rail (control-record). */
  hidePinch?: boolean;
  /** Hide ADB/scrcpy session restart on the rail. */
  hideRestart?: boolean;
}

function RailIconButton({
  label,
  hint,
  onClick,
  active,
  compact,
  dpad,
  children
}: {
  label: string;
  hint?: string;
  onClick: () => void;
  active?: boolean;
  compact?: boolean;
  /** Narrow rail D-pad — fits two buttons per row inside `w-11`. */
  dpad?: boolean;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type='button'
          aria-label={label}
          aria-pressed={active}
          onClick={onClick}
          className={cn(
            'flex shrink-0 items-center justify-center rounded-full transition-colors',
            !dpad && 'mx-auto',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900',
            dpad ? 'size-7' : compact ? 'size-8' : 'size-9',
            active
              ? 'bg-primary text-primary-foreground shadow-md'
              : 'text-zinc-300 hover:bg-white/15 hover:text-white'
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side='left' className='text-xs'>
        {hint ?? label}
      </TooltipContent>
    </Tooltip>
  );
}

const DPAD_ICON = 'size-3.5 stroke-[2.25]' as const;

/** Single-column D-pad — fits `w-11` rail without horizontal overflow. */
function DeviceControlsSwipePad({
  onSwipe,
  t
}: {
  onSwipe: (direction: 'up' | 'down' | 'left' | 'right') => void;
  t: ReturnType<typeof useTranslations<'devicesControlRecord.controls'>>;
}) {
  const dirs = [
    ['up', ChevronsUp, t('swipeUp'), t('swipeUpHint')],
    ['left', ChevronsLeft, t('swipeLeft'), t('swipeLeftHint')],
    ['right', ChevronsRight, t('swipeRight'), t('swipeRightHint')],
    ['down', ChevronsDown, t('swipeDown'), t('swipeDownHint')]
  ] as const;

  return (
    <div
      className='relative z-10 flex w-full shrink-0 flex-col items-center gap-0.5'
      role='group'
      aria-label={t('swipePad')}
    >
      {dirs.map(([dir, Icon, label, hint]) => (
        <RailIconButton
          key={dir}
          dpad
          label={label}
          hint={hint}
          onClick={() => onSwipe(dir)}
        >
          <Icon className={DPAD_ICON} aria-hidden />
        </RailIconButton>
      ))}
    </div>
  );
}

function DeviceControlsRail({
  serial,
  mode,
  onToggleMode,
  onKey,
  onRestart,
  gestureMode,
  onGestureMode,
  onPinch,
  onSwipeExt,
  onScreenOn,
  onScreenOff,
  onUnlock,
  hidePinch,
  hideRestart,
  className
}: DeviceControlsProps) {
  const t = useTranslations('devicesControlRecord.controls');
  const id = serialToId(serial);
  const ModeIcon = mode === 'tap' ? MousePointerClick : MoveHorizontal;
  const iconClass = 'size-[18px] shrink-0 stroke-[2.25]';
  const gestureActive =
    gestureMode === 'double_tap' || gestureMode === 'drag';

  return (
    <div
      className={cn(
        'flex h-full min-h-full w-11 shrink-0 flex-col justify-between rounded-[1.35rem] bg-zinc-900 py-3.5 shadow-lg ring-1 ring-black/20',
        className
      )}
      data-device-controls-rail={id}
    >
      <div className='flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-1.5'>
        <RailIconButton
          label={mode === 'tap' ? t('tapMode') : t('swipeMode')}
          hint={t('tapModeToggleHint')}
          active={!gestureActive}
          onClick={onToggleMode}
        >
          <ModeIcon className={iconClass} aria-hidden />
        </RailIconButton>

        {onGestureMode ? (
          <>
            <RailIconButton
              label={t('doubleTap')}
              hint={t('doubleTapHint')}
              active={gestureMode === 'double_tap'}
              onClick={() =>
                onGestureMode(
                  gestureMode === 'double_tap' ? 'tap' : 'double_tap'
                )
              }
            >
              <MousePointer2 className={iconClass} aria-hidden />
            </RailIconButton>
            <RailIconButton
              label={t('drag')}
              hint={t('dragHint')}
              active={gestureMode === 'drag'}
              onClick={() =>
                onGestureMode(gestureMode === 'drag' ? 'tap' : 'drag')
              }
            >
              <Hand className={iconClass} aria-hidden />
            </RailIconButton>
          </>
        ) : null}

        {onPinch && !hidePinch ? (
          <>
            <RailIconButton
              label={t('zoomIn')}
              hint={t('zoomInHint')}
              onClick={() => onPinch(2.0)}
            >
              <ZoomIn className={iconClass} aria-hidden />
            </RailIconButton>
            <RailIconButton
              label={t('zoomOut')}
              hint={t('zoomOutHint')}
              onClick={() => onPinch(0.5)}
            >
              <ZoomOut className={iconClass} aria-hidden />
            </RailIconButton>
          </>
        ) : null}

        <div className='my-0.5 h-px bg-white/10' aria-hidden />

        <RailIconButton label={t('home')} onClick={() => onKey('home')}>
          <Home className={iconClass} aria-hidden />
        </RailIconButton>
        <RailIconButton label={t('back')} onClick={() => onKey('back')}>
          <ArrowLeft className={iconClass} aria-hidden />
        </RailIconButton>
        {onScreenOn ? (
          <RailIconButton
            label={t('screenOn')}
            hint={t('screenOnHint')}
            onClick={onScreenOn}
          >
            <Sun className={iconClass} aria-hidden />
          </RailIconButton>
        ) : null}
        {onScreenOff ? (
          <RailIconButton
            label={t('screenOff')}
            hint={t('screenOffHint')}
            onClick={onScreenOff}
          >
            <Moon className={iconClass} aria-hidden />
          </RailIconButton>
        ) : null}
        {onUnlock ? (
          <RailIconButton
            label={t('unlock')}
            hint={t('unlockHint')}
            onClick={onUnlock}
          >
            <LockOpen className={iconClass} aria-hidden />
          </RailIconButton>
        ) : null}
        <RailIconButton label={t('power')} onClick={() => onKey('power')}>
          <Power className={iconClass} aria-hidden />
        </RailIconButton>
        {!hideRestart ? (
          <RailIconButton
            label={t('restart')}
            hint={t('restartTitle')}
            onClick={onRestart}
          >
            <RotateCw className={iconClass} aria-hidden />
          </RailIconButton>
        ) : null}
      </div>

      {onSwipeExt ? (
        <div className='relative z-10 flex w-full shrink-0 flex-col items-center px-1.5 pb-2 pt-2'>
          <div className='mb-2 h-px w-7 shrink-0 bg-white/10' aria-hidden />
          <DeviceControlsSwipePad onSwipe={onSwipeExt} t={t} />
        </div>
      ) : null}
    </div>
  );
}

function DeviceControlsBelow(props: DeviceControlsProps) {
  const {
    serial,
    mode,
    onToggleMode,
    onKey,
    onRestart,
    compact = false,
    gestureMode,
    onGestureMode,
    onPinch,
    onSwipeExt,
    onScreenOn,
    onScreenOff,
    onUnlock,
    hidePinch,
    hideRestart,
    className
  } = props;
  const t = useTranslations('devicesControlRecord.controls');
  const id = serialToId(serial);

  const ModeIcon = mode === 'tap' ? MousePointerClick : MoveHorizontal;
  const btn = compact
    ? 'min-h-7 gap-1 px-2 text-[11px] h-7'
    : 'min-h-9 gap-1.5';
  const icon = compact ? 'size-3 shrink-0' : 'size-3.5 shrink-0';

  return (
    <div
      className={cn(
        compact ? 'mt-0.5 flex flex-wrap gap-1' : 'mt-1 flex flex-wrap gap-2',
        className
      )}
    >
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

      {onGestureMode && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant={gestureMode === 'double_tap' ? 'secondary' : 'outline'}
              className={btn}
              onClick={() =>
                onGestureMode(
                  gestureMode === 'double_tap' ? 'tap' : 'double_tap'
                )
              }
            >
              <MousePointer2 className={icon} aria-hidden />
              {compact ? '2×' : t('doubleTap')}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            {t('doubleTapHint')}
          </TooltipContent>
        </Tooltip>
      )}

      {onGestureMode && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant={gestureMode === 'drag' ? 'secondary' : 'outline'}
              className={btn}
              onClick={() =>
                onGestureMode(gestureMode === 'drag' ? 'tap' : 'drag')
              }
            >
              <Hand className={icon} aria-hidden />
              {t('drag')}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            {t('dragHint')}
          </TooltipContent>
        </Tooltip>
      )}

      {onPinch && !hidePinch ? (
        <>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size='sm'
                variant='outline'
                className={btn}
                onClick={() => onPinch(2.0)}
              >
                <ZoomIn className={icon} aria-hidden />
                {!compact && t('zoomIn')}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='top' className='text-xs'>
              {t('zoomInHint')}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size='sm'
                variant='outline'
                className={btn}
                onClick={() => onPinch(0.5)}
              >
                <ZoomOut className={icon} aria-hidden />
                {!compact && t('zoomOut')}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='top' className='text-xs'>
              {t('zoomOutHint')}
            </TooltipContent>
          </Tooltip>
        </>
      ) : null}

      <Button size='sm' variant='outline' className={btn} onClick={() => onKey('home')}>
        <Home className={icon} aria-hidden />
        {t('home')}
      </Button>
      <Button size='sm' variant='outline' className={btn} onClick={() => onKey('back')}>
        <ArrowLeft className={icon} aria-hidden />
        {t('back')}
      </Button>
      <Button size='sm' variant='outline' className={btn} onClick={() => onKey('power')}>
        <Power className={icon} aria-hidden />
        {t('power')}
      </Button>
      {!hideRestart ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size='sm'
              variant='ghost'
              className={cn(btn, 'text-muted-foreground hover:text-foreground')}
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
      ) : null}

      {onScreenOn && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size='sm' variant='outline' className={btn} onClick={onScreenOn}>
              <Sun className={icon} aria-hidden />
              {!compact && t('screenOn')}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            {t('screenOnHint')}
          </TooltipContent>
        </Tooltip>
      )}
      {onScreenOff && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size='sm' variant='outline' className={btn} onClick={onScreenOff}>
              <Moon className={icon} aria-hidden />
              {!compact && t('screenOff')}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            {t('screenOffHint')}
          </TooltipContent>
        </Tooltip>
      )}
      {onUnlock && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size='sm' variant='outline' className={btn} onClick={onUnlock}>
              <LockOpen className={icon} aria-hidden />
              {!compact && t('unlock')}
            </Button>
          </TooltipTrigger>
          <TooltipContent side='top' className='text-xs'>
            {t('unlockHint')}
          </TooltipContent>
        </Tooltip>
      )}

      {onSwipeExt && (
        <>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size='sm'
                variant='outline'
                className={btn}
                onClick={() => onSwipeExt('up')}
              >
                <ChevronsUp className={icon} aria-hidden />
                {!compact && t('swipeUp')}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='top' className='text-xs'>
              {t('swipeUpHint')}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size='sm'
                variant='outline'
                className={btn}
                onClick={() => onSwipeExt('down')}
              >
                <ChevronsDown className={icon} aria-hidden />
                {!compact && t('swipeDown')}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='top' className='text-xs'>
              {t('swipeDownHint')}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size='sm'
                variant='outline'
                className={btn}
                onClick={() => onSwipeExt('left')}
              >
                <ChevronsLeft className={icon} aria-hidden />
                {!compact && t('swipeLeft')}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='top' className='text-xs'>
              {t('swipeLeftHint')}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size='sm'
                variant='outline'
                className={btn}
                onClick={() => onSwipeExt('right')}
              >
                <ChevronsRight className={icon} aria-hidden />
                {!compact && t('swipeRight')}
              </Button>
            </TooltipTrigger>
            <TooltipContent side='top' className='text-xs'>
              {t('swipeRightHint')}
            </TooltipContent>
          </Tooltip>
        </>
      )}
    </div>
  );
}

export function DeviceControls(props: DeviceControlsProps) {
  const { layout, compact } = props;
  const useRail = layout === 'rail' || (!layout && !compact);

  if (useRail) {
    return <DeviceControlsRail {...props} />;
  }
  return <DeviceControlsBelow {...props} />;
}
