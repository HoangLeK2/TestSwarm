'use client';

import {
  ArrowLeft,
  Home,
  MousePointerClick,
  MoveHorizontal,
  Power,
  RotateCw,
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
}

export function DeviceControls({
  serial,
  mode,
  onToggleMode,
  onKey,
  onRestart,
  compact = false,
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
