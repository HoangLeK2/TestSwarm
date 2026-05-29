'use client';

import { useState } from 'react';
import { Plus, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
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
  useReorderScenarios,
  useScenarios
} from '../../hooks/use-campaigns';
import type { CampaignOut, ScenarioOut } from '../../types';
import { ScenarioRow } from './ScenarioRow';

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
  const [open, setOpen] = useState(false);
  const isControlled =
    typeof controlledOpen === 'boolean' && !!controlledOnOpenChange;
  const finalOpen = isControlled ? controlledOpen : open;
  const onOpenChange = isControlled ? controlledOnOpenChange : setOpen;
  const qc = useQueryClient();
  const { data: scenarios = [], refetch } = useScenarios(campaign.id);
  const { mutate: createScenario, isPending: isCreating } = useCreateScenario();
  const { mutateAsync: reorderScenarios, isPending: isReordering } =
    useReorderScenarios();

  const totalSteps = scenarios.reduce((sum, s) => sum + s.steps.length, 0);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const scenariosKey = ['campaigns', campaign.id, 'scenarios'];

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
    if (isReordering) return;
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
          {scenarios.length === 0 ? (
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
                      dragDisabled={isReordering}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          )}

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
        </div>
      </DialogContent>
    </Dialog>
  );
}
