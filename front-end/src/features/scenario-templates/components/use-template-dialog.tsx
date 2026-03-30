'use client';

import { useState } from 'react';
import { Rocket } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { useCreateCampaign } from '@/features/campaigns/hooks/use-campaigns';
import type { ScenarioTemplateOut } from '../services/api';
import { VariableEditor } from '@/components/variable-editor';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { FlowEditor } from '@/features/campaigns/components/flow-editor';

export function UseTemplateDialog({ template }: { template: ScenarioTemplateOut }) {
  const t = useTranslations('scenarioTemplatesFeature.useDialog');
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [campaignName, setCampaignName] = useState(`${template.name} campaign`);
  const [variables, setVariables] = useState<Record<string, any>>(
    template.variables ?? {}
  );
  const { mutate, isPending } = useCreateCampaign();

  const handleCreate = () => {
    mutate(
      {
        name: campaignName,
        scenario: { steps: template.steps },
        variables
      },
      {
        onSuccess: (campaign) => {
          setOpen(false);
          router.push(ROUTES.CAMPAIGNS.ROOT);
        }
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline' className='text-xs gap-1'>
          <Rocket size={12} />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <p className='text-sm text-muted-foreground'>{template.name}</p>
        </DialogHeader>
        <div className='space-y-4 pt-2'>
          <div className='space-y-1'>
            <Label>{t('campaignNameLabel')}</Label>
            <Input
              value={campaignName}
              onChange={(e) => setCampaignName(e.target.value)}
            />
          </div>
          {Object.keys(template.variables ?? {}).length > 0 && (
            <div className='space-y-1'>
              <Label>{t('variablesLabel')}</Label>
              <p className='text-xs text-muted-foreground'>{t('variablesHint')}</p>
              <VariableEditor variables={variables} onChange={setVariables} />
            </div>
          )}
          <div className='space-y-1'>
            <p className='text-xs font-medium'>
              {t('stepsPreview')} ({template.steps?.length ?? 0} {t('steps')})
            </p>
            {(template.steps?.length ?? 0) > 0 && (
              <FlowEditor
                steps={template.steps}
                onChange={() => {}}
                maxHeight='200px'
                compact
              />
            )}
          </div>
          <Button
            onClick={handleCreate}
            disabled={isPending || !campaignName.trim()}
            className='w-full'
          >
            {isPending ? t('creating') : t('submit')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
