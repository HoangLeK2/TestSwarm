'use client';

import Link from 'next/link';
import { ChevronRight, FileText, GripVertical, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Button } from '@/components/ui/button';
import { ROUTES } from '@/config/routes';
import type { CampaignOut, ScenarioOut } from '../../types';
import { useDeleteScenario } from '../../hooks/use-campaigns';
import { useConfirm } from '@/providers/modal-provider';

export function ScenarioRow({
  campaign,
  scenario,
  onDeleted,
  dragDisabled = false
}: {
  campaign: CampaignOut;
  scenario: ScenarioOut;
  onDeleted: () => void;
  dragDisabled?: boolean;
}) {
  const t = useTranslations('campaignsFeature.scenarioList');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { mutate: deleteScenario, isPending } = useDeleteScenario();
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging
  } = useSortable({
    id: scenario.id,
    disabled: dragDisabled
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition: transition ?? undefined
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    void (async () => {
      const ok = await confirm({
        title: t('deleteTitle'),
        description: t('deleteConfirm', { name: scenario.name }),
        confirmText: tCommon('confirm'),
        cancelText: tCommon('cancel'),
        confirmVariant: 'destructive',
        zIndex: 10_000
      });
      if (!ok) return;

      deleteScenario(
        { campaignId: campaign.id, scenarioId: scenario.id },
        {
          onSuccess: () => {
            toast.success(t('deleteSuccess'));
            onDeleted();
          },
          onError: () => toast.error(t('deleteFailed'))
        }
      );
    })();
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-2 rounded-md border bg-background px-2 py-2 text-sm hover:bg-muted/40 ${
        isDragging ? 'relative z-50 shadow-lg' : ''
      }`}
    >
      <button
        type='button'
        disabled={dragDisabled}
        {...attributes}
        {...listeners}
        tabIndex={-1}
        title={t('reorderTitle')}
        className={`flex shrink-0 items-center justify-center text-muted-foreground/40 ${
          dragDisabled
            ? 'cursor-not-allowed opacity-40'
            : 'cursor-grab hover:text-muted-foreground active:cursor-grabbing'
        }`}
      >
        <GripVertical size={14} />
      </button>
      <FileText size={14} className='shrink-0 text-muted-foreground' />
      <div className='min-w-0 flex-1'>
        <div
          className='line-clamp-2 break-words font-medium'
          title={scenario.name}
        >
          {scenario.name}
        </div>
        {scenario.instructions && (
          <div className='truncate text-[11px] text-muted-foreground'>
            {scenario.instructions}
          </div>
        )}
        <div className='text-[11px] text-muted-foreground'>
          {t('stepsCount', { count: scenario.steps.length })}
        </div>
      </div>

      <Button
        size='icon'
        variant='ghost'
        className='size-7 shrink-0'
        title={t('editTitle')}
        asChild
      >
        <Link
          href={ROUTES.DEVICES.CONTROL_RECORD_EDIT_SCENARIO(
            campaign.id,
            scenario.id
          )}
        >
          <ChevronRight size={14} />
        </Link>
      </Button>

      <Button
        size='icon'
        variant='ghost'
        className='size-7 shrink-0 text-destructive hover:text-destructive'
        disabled={isPending}
        onClick={handleDelete}
        title={t('deleteTitle')}
      >
        <Trash2 size={12} />
      </Button>
    </div>
  );
}
