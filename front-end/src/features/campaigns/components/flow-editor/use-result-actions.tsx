'use client';

import { ChevronDown } from 'lucide-react';
import { useTranslations } from 'next-intl';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { createDefaultStep, type FlowStep } from '../scenario-steps/types';

type Props = {
  /** Variable the step just filled. */
  variable: string;
  onInsert: (step: FlowStep) => void;
};

/**
 * Chain a step's output into the next step.
 *
 * Seeing the value is only half the job — without this the author still has to
 * know which step type consumes it and type the variable name by hand.
 */
export function UseResultActions({ variable, onInsert }: Props) {
  const t = useTranslations('campaignsFeature.stepEditor.runResult');
  const token = `\${${variable}}`;

  const insert = (type: string, patch: Record<string, unknown>) => {
    onInsert({ ...createDefaultStep(type as never), ...patch } as FlowStep);
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type='button'
          variant='outline'
          size='sm'
          className='h-6 gap-1 bg-background px-2 text-[11px] font-medium'
        >
          {t('useResult')}
          <ChevronDown className='size-3' />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align='start' className='text-xs'>
        <DropdownMenuItem
          onClick={() => insert('if_variable', { name: variable })}
        >
          {t('useBranch')}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => insert('input_text', { text: token })}>
          {t('useInput')}
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() =>
            insert('set_variable', { name: `${variable}_saved`, value: token })
          }
        >
          {t('useSave')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
