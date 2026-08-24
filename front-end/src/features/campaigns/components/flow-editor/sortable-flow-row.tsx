'use client';

import type { CSSProperties, ReactNode } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { FLOW_ROW_DRAG_GUTTER_CLASS } from './flow-row-gutter';

export function SortableFlowRow({
  id,
  children
}: {
  id: string;
  children: (
    dragHandle: React.ReactNode,
    isDragging: boolean
  ) => React.ReactNode;
}) {
  const tField = useTranslations('campaignsFeature.stepEditor.stepFields');
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging
  } = useSortable({ id });

  const style: CSSProperties = {
    contain: 'layout style',
    transform: CSS.Transform.toString(transform),
    transition: transition ?? undefined,
    willChange: isDragging ? 'transform' : undefined
  };

  const dragHandle = (
    <button
      {...listeners}
      {...attributes}
      type='button'
      tabIndex={-1}
      title={tField('dragToReorder')}
      className={[
        'flex shrink-0 cursor-grab items-center justify-center self-stretch text-muted-foreground/30',
        FLOW_ROW_DRAG_GUTTER_CLASS,
        'hover:text-muted-foreground/70 active:cursor-grabbing',
        isDragging ? 'cursor-grabbing text-muted-foreground/70' : ''
      ].join(' ')}
    >
      <GripVertical size={11} />
    </button>
  );

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={isDragging ? 'relative z-50 rounded shadow-lg' : ''}
    >
      {children(dragHandle, isDragging)}
    </div>
  );
}

export function StaticFlowRow({
  children
}: {
  children: (dragHandle: ReactNode, isDragging: boolean) => ReactNode;
}) {
  const dragHandle = (
    <div
      className={[
        'flex shrink-0 items-center justify-center self-stretch',
        FLOW_ROW_DRAG_GUTTER_CLASS
      ].join(' ')}
      aria-hidden
    />
  );

  return <div>{children(dragHandle, false)}</div>;
}

export function MaybeSortableFlowRow({
  id,
  enabled,
  children
}: {
  id: string;
  enabled: boolean;
  children: (dragHandle: ReactNode, isDragging: boolean) => ReactNode;
}) {
  return enabled ? (
    <SortableFlowRow id={id}>{children}</SortableFlowRow>
  ) : (
    <StaticFlowRow>{children}</StaticFlowRow>
  );
}
