'use client';

import { useEffect, useState } from 'react';
import { FileText, Pencil, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy
} from '@dnd-kit/sortable';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import {
  useCreateScenario,
  usePatchCampaignEntity,
  useReorderScenarios,
  useCampaign,
  useScenarios
} from '../../hooks/use-campaigns';
import type { CampaignOut, ScenarioOut } from '../../types';
import { isCampaignBodyEditable } from '../../types';
import {
  isCampaignEntityOut,
  type CampaignEntityOut
} from '../../services/api';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { isGraphOrgScenario } from '@/features/org-scenarios/lib/campaign-scenario-eligibility';
import { CampaignOrgScenarioPicker } from '../campaign-org-scenario-picker';
import { ScenarioRow } from './ScenarioRow';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { useConfirm } from '@/providers/modal-provider';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

export function ScenarioListDialog({
  campaign,
  children,
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange
}: {
  campaign: CampaignOut;
  children?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations('campaignsFeature.scenarioList');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const isControlled =
    typeof controlledOpen === 'boolean' && !!controlledOnOpenChange;
  const finalOpen = isControlled ? controlledOpen : open;
  const onOpenChange = isControlled ? controlledOnOpenChange : setOpen;
  const qc = useQueryClient();
  const { canUpdate } = useResourcePermissions('campaigns');
  const { data: scenarios = [], refetch } = useScenarios(campaign.id);
  const { data: campaignDetail } = useCampaign(campaign.id, finalOpen);
  const entityDetail: CampaignEntityOut | null = (() => {
    const row = campaignDetail ?? campaign;
    return isCampaignEntityOut(row) ? row : null;
  })();
  const entityRefs =
    entityDetail?.scenario_refs ?? campaign.scenario_refs ?? [];
  const isEntityCampaign =
    entityDetail != null ||
    entityRefs.length > 0 ||
    Boolean(campaign.organization_id);
  const campaignStatus = entityDetail?.status ?? campaign.status;
  const bodyEditable = isCampaignBodyEditable(campaignStatus);
  const { data: orgScenarios = [] } = useOrgScenarios();
  const [selectedRefIds, setSelectedRefIds] = useState<string[]>([]);
  const { mutate: createScenario, isPending: isCreating } = useCreateScenario();
  const { mutate: patchEntity, isPending: isSavingRefs } =
    usePatchCampaignEntity();
  const { mutateAsync: reorderScenarios, isPending: isReordering } =
    useReorderScenarios();

  const entityRefIdsKey = entityRefs.map((ref) => ref.scenario_id).join(',');

  useEffect(() => {
    if (!finalOpen) return;
    setSelectedRefIds(
      entityRefIdsKey ? entityRefIdsKey.split(',').filter(Boolean) : []
    );
  }, [finalOpen, entityRefIdsKey]);

  const totalSteps = scenarios.reduce((sum, s) => sum + s.steps.length, 0);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const scenariosKey = ['campaigns', campaign.id, 'scenarios'];

  const editOrgScenario = (scenarioId: string) => {
    onOpenChange(false);
    const returnTo = ROUTES.CAMPAIGNS.DETAIL(campaign.id);
    router.push(
      ROUTES.DEVICES.CONTROL_RECORD_EDIT_ORG_SCENARIO(scenarioId, {
        returnTo,
        campaignId: campaign.id
      })
    );
  };

  const handleRemoveEntityRef = async (
    scenarioId: string,
    displayName: string
  ) => {
    const ok = await confirm({
      title: t('entityRemoveTitle'),
      description: t('entityRemoveConfirm', { name: displayName }),
      confirmText: tCommon('confirm'),
      cancelText: tCommon('cancel'),
      confirmVariant: 'destructive',
      zIndex: 10_000
    });
    if (!ok) return;

    const nextIds = entityRefs
      .map((ref) => ref.scenario_id)
      .filter((id) => id !== scenarioId);
    const sequenceIds = nextIds.filter((id) => {
      const row = orgScenarios.find((s) => s.id === id);
      return row && !isGraphOrgScenario(row);
    });

    patchEntity(
      {
        id: campaign.id,
        data: {
          scenario_refs: sequenceIds.map((scenario_id) => ({ scenario_id }))
        }
      },
      {
        onSuccess: () => {
          setSelectedRefIds(sequenceIds);
          toast.success(t('entityRemoveSuccess'));
        },
        onError: (err) =>
          toast.error(formatFarmApiError(err, t('entityRemoveFailed')))
      }
    );
  };

  const handleSaveEntityRefs = () => {
    const sequenceIds = selectedRefIds.filter((id) => {
      const row = orgScenarios.find((s) => s.id === id);
      return row && !isGraphOrgScenario(row);
    });
    if (selectedRefIds.length > sequenceIds.length) {
      toast.warning(t('entityGraphSkipped'));
    }
    if (!sequenceIds.length) {
      toast.error(t('entityRefsRequired'));
      return;
    }
    patchEntity(
      {
        id: campaign.id,
        data: {
          scenario_refs: sequenceIds.map((scenario_id) => ({ scenario_id }))
        }
      },
      {
        onSuccess: () => toast.success(t('entitySaveSuccess')),
        onError: (err) =>
          toast.error(formatFarmApiError(err, t('entitySaveFailed')))
      }
    );
  };

  const handleAdd = () => {
    createScenario(
      {
        campaignId: campaign.id,
        data: {
          name: `Scenario ${scenarios.length + 1}`,
          order: scenarios.length
        }
      },
      {
        onSuccess: () => toast.success(t('createSuccess')),
        onError: () => toast.error(t('createFailed'))
      }
    );
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    if (isReordering || !canUpdate) return;
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = scenarios.findIndex((s) => s.id === active.id);
    const newIndex = scenarios.findIndex((s) => s.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;

    const reordered = arrayMove(scenarios, oldIndex, newIndex).map(
      (s, idx) => ({ ...s, order: idx })
    );
    await qc.cancelQueries({ queryKey: scenariosKey });
    qc.setQueryData<ScenarioOut[]>(scenariosKey, reordered);

    try {
      await reorderScenarios({
        campaignId: campaign.id,
        orderedIds: reordered.map((s) => s.id)
      });
    } catch {
      toast.error(t('reorderFailed'));
      refetch();
    }
  };

  return (
    <Dialog open={finalOpen} onOpenChange={onOpenChange}>
      {children !== null && (
        <DialogTrigger asChild>
          {children ?? (
            <Button
              variant='outline'
              size='sm'
              className='w-full justify-start gap-1.5 text-xs'
            >
              <FileText size={12} />
              {t('trigger', { scenarios: scenarios.length, steps: totalSteps })}
            </Button>
          )}
        </DialogTrigger>
      )}

      <DialogContent className='max-h-[80vh] overflow-y-auto sm:max-w-lg'>
        <DialogHeader className='pr-10 text-left sm:pr-12'>
          <DialogTitle className='break-words text-base font-semibold leading-snug sm:text-lg'>
            {t('title', { campaign: campaign.name })}
          </DialogTitle>
        </DialogHeader>

        <div className='flex flex-col gap-2'>
          {isEntityCampaign ? (
            <div className='flex flex-col gap-3'>
              {entityRefs.length > 0 ? (
                <div className='flex flex-col gap-2'>
                  <p className='text-xs text-muted-foreground'>
                    {t('entityOpenHint')}
                  </p>
                  {entityRefs.map((ref) => {
                    const orgRow = orgScenarios.find(
                      (s) => s.id === ref.scenario_id
                    );
                    const name = orgRow?.name ?? ref.scenario_id;
                    const isGraph = isGraphOrgScenario(orgRow);
                    return (
                      <div
                        key={`${ref.scenario_id}-${ref.scenario_version}`}
                        className='flex items-start justify-between gap-2 rounded-md border bg-muted/20 px-3 py-2'
                      >
                        <div className='min-w-0'>
                          <div className='text-sm font-medium'>{name}</div>
                          <div className='text-[11px] text-muted-foreground'>
                            {ref.scenario_id} · v{ref.scenario_version}
                            {isGraph ? ` · ${t('entityGraphKind')}` : ''}
                            {orgRow && !orgRow.is_runnable
                              ? ` · ${t('entityNotRunnable')}`
                              : ''}
                          </div>
                        </div>
                        <div className='flex shrink-0 items-center gap-1'>
                          <Button
                            type='button'
                            size='sm'
                            variant='outline'
                            className='h-7 gap-1 px-2 text-xs'
                            disabled={isGraph}
                            onClick={() => {
                              if (isGraph) {
                                toast.warning(t('entityGraphSkipped'));
                                return;
                              }
                              editOrgScenario(ref.scenario_id);
                            }}
                          >
                            <Pencil className='size-3.5' />
                            {t('entityOpen')}
                          </Button>
                          {canUpdate && bodyEditable ? (
                            <Button
                              type='button'
                              size='sm'
                              variant='outline'
                              className='h-7 gap-1 px-2 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive'
                              disabled={isSavingRefs}
                              title={t('entityRemoveTitle')}
                              onClick={() =>
                                void handleRemoveEntityRef(
                                  ref.scenario_id,
                                  name
                                )
                              }
                            >
                              <Trash2 className='size-3.5' />
                              <span className='sr-only'>
                                {t('entityRemove')}
                              </span>
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className='text-center text-sm text-muted-foreground'>
                  {t('empty')}
                </p>
              )}
              {canUpdate && bodyEditable ? (
                <div className='space-y-2 border-t pt-3'>
                  <p className='text-xs text-muted-foreground'>
                    {t('entityManageHint')}
                  </p>
                  <CampaignOrgScenarioPicker
                    selectedIds={selectedRefIds}
                    onSelectedIdsChange={setSelectedRefIds}
                    messagesNs='entityDialog'
                  />
                  <Button
                    type='button'
                    size='sm'
                    className='w-full gap-1.5'
                    disabled={isSavingRefs}
                    onClick={handleSaveEntityRefs}
                  >
                    {t('entitySaveScenarios')}
                  </Button>
                </div>
              ) : canUpdate ? (
                <p className='text-xs text-muted-foreground'>
                  {t('entityBodyLockedHint')}
                </p>
              ) : null}
            </div>
          ) : scenarios.length === 0 ? (
            <p className='py-4 text-center text-sm text-muted-foreground'>
              {t('empty')}
            </p>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              modifiers={[restrictToVerticalAxis]}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={scenarios.map((s) => s.id)}
                strategy={verticalListSortingStrategy}
              >
                <div className='flex flex-col gap-2'>
                  {scenarios.map((s) => (
                    <ScenarioRow
                      key={s.id}
                      campaign={campaign}
                      scenario={s}
                      onDeleted={() => refetch()}
                      dragDisabled={isReordering || !canUpdate}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          )}

          {!isEntityCampaign && canUpdate ? (
            <Button
              variant='outline'
              size='sm'
              className='mt-1 gap-1.5'
              disabled={isCreating}
              onClick={handleAdd}
            >
              <Plus size={13} />
              {t('addButton')}
            </Button>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
