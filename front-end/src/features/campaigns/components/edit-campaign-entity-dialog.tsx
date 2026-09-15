'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { VariableEditor } from '@/components/variable-editor';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { cn } from '@/lib/utils';
import { CampaignOrgScenarioPicker } from './campaign-org-scenario-picker';
import { RecoveryPolicyEditor } from './recovery-policy-editor';
import {
  useCampaign,
  useCampaignDevices,
  usePatchCampaignEntity
} from '../hooks/use-campaigns';
import type {
  CampaignOut,
  CampaignScenarioRefIn,
  RecoveryPolicy
} from '../types';
import {
  isCampaignBodyEditable,
  normalizeCampaignScenarioRefs,
  scenarioRefRunCount
} from '../types';
import { isCampaignEntityOut } from '../services/api';
import { ContinuousCrawlSettings } from './continuous-crawl-settings';
import { CaptureModeSettings } from './capture-mode-settings';
import {
  campaignVariablesForEditor,
  mergeCampaignEditorVariables
} from '../lib/continuous-crawl-monitor';

export function EditCampaignEntityDialog({
  campaign,
  open,
  onOpenChange
}: {
  campaign: CampaignOut;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations('campaignsFeature.entityDialog');
  const { data: detail } = useCampaign(campaign.id, open);
  const { data: campaignDevices = [] } = useCampaignDevices(campaign.id, open);
  const {
    mutate: patchEntity,
    mutateAsync: patchEntityAsync,
    isPending: isPatching,
    error,
    reset
  } = usePatchCampaignEntity();

  const entity = detail && isCampaignEntityOut(detail) ? detail : null;
  const bodyLocked = !isCampaignBodyEditable(entity?.status ?? campaign.status);

  const [name, setName] = useState(campaign.name);
  const [description, setDescription] = useState(campaign.description ?? '');
  const [tags, setTags] = useState('');
  const [variables, setVariables] = useState<Record<string, unknown>>({});
  const [recoveryPolicy, setRecoveryPolicy] = useState<RecoveryPolicy>({});
  const [selectedRefs, setSelectedRefs] = useState<CampaignScenarioRefIn[]>([]);

  useEffect(() => {
    if (!entity) return;
    setName(entity.name);
    setDescription(entity.description ?? '');
    setTags((entity.tags ?? []).join(', '));
    setVariables(entity.vars ?? entity.variables ?? {});
    setRecoveryPolicy((entity.recovery_policy ?? {}) as RecoveryPolicy);
    setSelectedRefs(normalizeCampaignScenarioRefs(entity.scenario_refs ?? []));
  }, [entity]);

  const isSaving = isPatching;

  const onSubmit = () => {
    patchEntity(
      {
        id: campaign.id,
        data: bodyLocked
          ? {
              name: name.trim(),
              description: description.trim(),
              tags: tags
                .split(',')
                .map((tag) => tag.trim())
                .filter(Boolean)
            }
          : {
              name: name.trim(),
              description: description.trim(),
              tags: tags
                .split(',')
                .map((tag) => tag.trim())
                .filter(Boolean),
              vars: variables,
              scenario_refs: normalizeCampaignScenarioRefs(selectedRefs),
              recovery_policy: recoveryPolicy
            }
      },
      {
        onSuccess: () => {
          toast.success(t('saveSuccess'));
          reset();
          onOpenChange(false);
        },
        onError: (patchErr) => {
          toast.error(formatFarmApiError(patchErr, t('saveFailed')));
        }
      }
    );
  };

  if (!entity && open && detail && !isCampaignEntityOut(detail)) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] max-w-4xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <div className='space-y-4'>
          {bodyLocked && (
            <p className='rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-200'>
              {t('bodyLockedHint')}
            </p>
          )}
          {(entity?.started_at ||
            entity?.completed_at ||
            entity?.cancelled_at) && (
            <div className='space-y-1 rounded-md border bg-muted/30 px-3 py-2 text-xs'>
              <p className='font-medium text-foreground'>
                {t('lifecycleTitle')}
              </p>
              {entity?.started_at ? (
                <p className='text-muted-foreground'>
                  {t('startedAt')}:{' '}
                  {new Date(entity.started_at).toLocaleString()}
                </p>
              ) : null}
              {entity?.completed_at ? (
                <p className='text-muted-foreground'>
                  {t('completedAt')}:{' '}
                  {new Date(entity.completed_at).toLocaleString()}
                </p>
              ) : null}
              {entity?.cancelled_at ? (
                <p className='text-muted-foreground'>
                  {t('cancelledAt')}:{' '}
                  {new Date(entity.cancelled_at).toLocaleString()}
                </p>
              ) : null}
            </div>
          )}
          <div className='space-y-1.5'>
            <Label>{t('nameLabel')}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className='space-y-1.5'>
            <Label>{t('descriptionLabel')}</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className='min-h-[72px] resize-none'
            />
          </div>
          <div className='space-y-1.5'>
            <Label>{t('tagsLabel')}</Label>
            <Input value={tags} onChange={(e) => setTags(e.target.value)} />
          </div>
          <div className='space-y-2'>
            <Label>{t('scenariosLabel')}</Label>
            <CampaignOrgScenarioPicker
              selectedRefs={selectedRefs}
              onSelectedRefsChange={(refs) =>
                setSelectedRefs(normalizeCampaignScenarioRefs(refs))
              }
              disabled={bodyLocked}
              messagesNs='entityDialog'
              showRepeatConfig
            />
            {selectedRefs.length > 0 ? (
              <p className='text-[11px] text-muted-foreground'>
                {t('repeatSummary', {
                  scenarios: selectedRefs.length,
                  runs: scenarioRefRunCount(selectedRefs)
                })}
              </p>
            ) : null}
          </div>
          <div
            className={cn(
              'space-y-1.5',
              bodyLocked && 'pointer-events-none opacity-60'
            )}
          >
            <ContinuousCrawlSettings
              variables={variables}
              onChange={setVariables}
              disabled={bodyLocked}
            />
            <CaptureModeSettings
              variables={variables}
              onChange={setVariables}
              disabled={bodyLocked}
            />
          </div>
          <div
            className={cn(
              'space-y-1.5',
              bodyLocked && 'pointer-events-none opacity-60'
            )}
          >
            <Label>{t('variablesLabel')}</Label>
            <VariableEditor
              variables={campaignVariablesForEditor(variables)}
              onChange={(next) =>
                setVariables(mergeCampaignEditorVariables(variables, next))
              }
            />
          </div>
          <div className='space-y-2 rounded-md border bg-muted/30 p-3'>
            <Label>{t('accountBindingLabel')}</Label>
            <p className='text-xs text-muted-foreground'>
              {t('accountBindingHint')}
            </p>
            <div className='space-y-1.5'>
              {campaignDevices.map((device) => (
                <div
                  key={device.id}
                  className='flex items-center justify-between rounded-md border bg-background px-3 py-2 text-xs'
                >
                  <span className='font-medium'>
                    {device.name || device.serial}
                  </span>
                  <span className='text-muted-foreground'>{device.serial}</span>
                </div>
              ))}
              {!campaignDevices.length && (
                <p className='text-xs text-amber-600'>
                  {t('accountNoDevices')}
                </p>
              )}
            </div>
          </div>
          <RecoveryPolicyEditor
            value={recoveryPolicy}
            onChange={setRecoveryPolicy}
            disabled={bodyLocked}
            recordCampaignId={campaign.id}
            onBeforeRecord={(policy) =>
              patchEntityAsync({
                id: campaign.id,
                data: { recovery_policy: policy as Record<string, any> }
              }).then(() => undefined)
            }
          />
          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('saveFailed'))}
            </p>
          )}
          <div className='flex justify-end gap-2'>
            <Button
              variant='ghost'
              size='sm'
              onClick={() => onOpenChange(false)}
            >
              {t('cancel')}
            </Button>
            <Button
              size='sm'
              onClick={onSubmit}
              disabled={isSaving || !name.trim()}
            >
              {isSaving ? t('saving') : t('submit')}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
