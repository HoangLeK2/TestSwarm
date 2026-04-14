'use client';

import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';

export function SortableFlowRow({
  id,
  children,
}: {
  id: string;
  children: (dragHandle: React.ReactNode, isDragging: boolean) => React.ReactNode;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition: transition ?? undefined,
  };

  const dragHandle = (
    <button
      {...listeners}
      {...attributes}
      type='button'
      tabIndex={-1}
      title='Kéo để thay đổi thứ tự hoặc thả vào khối repeat/if'
      className={[
        'flex shrink-0 cursor-grab items-center self-stretch px-1 text-muted-foreground/30',
        'hover:text-muted-foreground/70 active:cursor-grabbing',
        isDragging ? 'cursor-grabbing text-muted-foreground/70' : '',
      ].join(' ')}
    >
      <GripVertical size={11} />
    </button>
  );

  return (
    <div ref={setNodeRef} style={style} className={isDragging ? 'relative z-50 rounded shadow-lg' : ''}>
      {children(dragHandle, isDragging)}
    </div>
  );
}
