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
import {
  useCampaign,
  useBindCampaignAccounts,
  usePatchCampaignEntity,
  useUnbindCampaignAccounts
} from '../hooks/use-campaigns';
import type { CampaignOut } from '../types';
import { isCampaignBodyEditable } from '../types';
import { isCampaignEntityOut } from '../services/api';
import {
  CampaignAccountBindingFields,
  campaignBindingFromEntity,
  campaignBindingToPayload,
  type CampaignAccountBindingValue
} from './campaign-account-binding-fields';

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
  const {
    mutate: patchEntity,
    isPending: isPatching,
    error,
    reset
  } = usePatchCampaignEntity();
  const { mutateAsync: bindAccounts, isPending: isBinding } =
    useBindCampaignAccounts();
  const { mutateAsync: unbindAccounts, isPending: isUnbinding } =
    useUnbindCampaignAccounts();

  const entity = detail && isCampaignEntityOut(detail) ? detail : null;
  const bodyLocked = !isCampaignBodyEditable(entity?.status ?? campaign.status);

  const [name, setName] = useState(campaign.name);
  const [description, setDescription] = useState(campaign.description ?? '');
  const [tags, setTags] = useState('');
  const [variables, setVariables] = useState<Record<string, unknown>>({});
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [accountBinding, setAccountBinding] =
    useState<CampaignAccountBindingValue>({
      mode: 'none',
      accountGroupId: '',
      scenarioAccountId: ''
    });

  useEffect(() => {
    if (!entity) return;
    setName(entity.name);
    setDescription(entity.description ?? '');
    setTags((entity.tags ?? []).join(', '));
    setVariables(entity.vars ?? entity.variables ?? {});
    setSelectedIds((entity.scenario_refs ?? []).map((ref) => ref.scenario_id));
    setAccountBinding(campaignBindingFromEntity(entity));
  }, [entity]);

  const isSaving = isPatching || isBinding || isUnbinding;

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
              scenario_refs: selectedIds.map((scenario_id) => ({ scenario_id }))
            }
      },
      {
        onSuccess: async () => {
          try {
            if (!bodyLocked) {
              const payload = campaignBindingToPayload(accountBinding);
              if (accountBinding.mode === 'none') {
                await unbindAccounts(campaign.id);
              } else {
                await bindAccounts({
                  id: campaign.id,
                  data: payload
                });
              }
            }
            toast.success(t('saveSuccess'));
            reset();
            onOpenChange(false);
          } catch (bindErr) {
            toast.error(formatFarmApiError(bindErr, t('bindFailed')));
          }
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
      <DialogContent className='max-h-[90vh] max-w-lg overflow-y-auto'>
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
              selectedIds={selectedIds}
              onSelectedIdsChange={setSelectedIds}
              disabled={bodyLocked}
              messagesNs='entityDialog'
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
              variables={variables}
              onChange={(next) => setVariables(next)}
            />
          </div>
          <div
            className={cn(
              'space-y-2 rounded-md border p-3',
              bodyLocked && 'pointer-events-none opacity-60'
            )}
          >
            <Label>{t('accountBindingLabel')}</Label>
            <p className='text-[11px] text-muted-foreground'>
              {t('accountBindingHint')}
            </p>
            <CampaignAccountBindingFields
              value={accountBinding}
              onChange={setAccountBinding}
            />
          </div>
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
