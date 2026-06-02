'use client';

import { Megaphone } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Can } from '@/features/auth';
import { CreateCampaignDialog } from '@/features/campaigns/components/create-campaign-dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from '@/components/ui/tooltip';

export function CreateCampaignFromScenarioButton({
  scenarioId,
  scenarioName,
  isRunnable = true,
  size = 'sm',
  variant = 'default',
  className
}: {
  scenarioId: string;
  scenarioName?: string;
  isRunnable?: boolean;
  size?: 'sm' | 'default';
  variant?: 'default' | 'outline' | 'secondary';
  className?: string;
}) {
  const t = useTranslations('orgScenariosFeature.detail');

  const trigger = (
    <Button
      type='button'
      size={size}
      variant={variant}
      className={className}
      disabled={!isRunnable}
    >
      <Megaphone className='size-4' />
      {t('createCampaign')}
    </Button>
  );

  return (
    <Can object='campaigns' action='create'>
      {!isRunnable ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className='inline-flex'>{trigger}</span>
            </TooltipTrigger>
            <TooltipContent side='bottom' className='max-w-xs text-xs'>
              {t('createCampaignDisabledHint')}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        <CreateCampaignDialog
          preselectedScenarioIds={[scenarioId]}
          defaultCampaignName={
            scenarioName ? `${scenarioName} — chiến dịch` : undefined
          }
          trigger={trigger}
        />
      )}
    </Can>
  );
}
