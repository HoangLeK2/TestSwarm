'use client';

import type { ScenarioStep } from '../../types/scenario';
import { Clock, Key, MousePointer, Move, Type } from 'lucide-react';

export function ControlRecordStepLabel({ step }: { step: ScenarioStep }) {
  switch (step.type) {
    case 'tap_ratio':
      return (
        <span className='flex items-center gap-1.5'>
          <MousePointer className='size-3.5' />
          tap_ratio ({(step.x * 100).toFixed(0)}%, {(step.y * 100).toFixed(0)}%)
        </span>
      );
    case 'swipe_ratio':
      return (
        <span className='flex items-center gap-1.5'>
          <Move className='size-3.5' />
          swipe_ratio {step.duration_ms ?? 300}ms
        </span>
      );
    case 'key':
      return (
        <span className='flex items-center gap-1.5'>
          <Key className='size-3.5' />
          key {step.key}
        </span>
      );
    case 'wait':
      return (
        <span className='flex items-center gap-1.5'>
          <Clock className='size-3.5' />
          wait {step.seconds}s
        </span>
      );
    case 'launch_app':
      return (
        <span className='flex items-center gap-1.5'>
          <Type className='size-3.5' />
          launch {step.package}
        </span>
      );
    case 'tap_selector':
      return (
        <span className='flex items-center gap-1.5'>
          <MousePointer className='size-3.5' />
          tap_selector {step.by}={step.value.slice(0, 20)}
          {step.value.length > 20 ? '…' : ''}
        </span>
      );
    default:
      return <span className='font-mono text-muted-foreground'>{step.type}</span>;
  }
}
