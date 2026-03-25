'use client';

import { serialToId } from '../helpers';
import { Button } from '@/components/ui/button';

interface DeviceControlsProps {
  serial: string;
  mode: 'tap' | 'swipe';
  onToggleMode: () => void;
  onKey: (key: string) => void;
  onRestart: () => void;
}

export function DeviceControls({
  serial,
  mode,
  onToggleMode,
  onKey,
  onRestart
}: DeviceControlsProps) {
  const id = serialToId(serial);

  return (
    <div className='mt-2 flex flex-wrap gap-1.5'>
      <Button
        id={`mode-${id}`}
        size='xs'
        variant={mode === 'tap' ? 'secondary' : 'outline'}
        onClick={onToggleMode}
      >
        {mode === 'tap' ? 'Tap mode' : 'Swipe mode'}
      </Button>
      <Button size='xs' variant='ghost' onClick={() => onKey('home')}>
        ⌂ Home
      </Button>
      <Button size='xs' variant='ghost' onClick={() => onKey('back')}>
        ← Back
      </Button>
      <Button size='xs' variant='ghost' onClick={() => onKey('power')}>
        ⏻ Power
      </Button>
      <Button size='xs' variant='destructive' onClick={onRestart}>
        ↺ Restart
      </Button>
    </div>
  );
}

