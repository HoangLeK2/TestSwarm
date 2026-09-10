'use client';

import { Badge } from '@/components/ui/badge';

/** Read-only. Tags are edited in the row's Update dialog, next to the name. */
export function TagsCell({ tags }: { tags?: string }) {
  const tagList = (tags ?? '').split(',').filter(Boolean);

  if (tagList.length === 0) {
    return <span className='text-[11px] text-muted-foreground'>—</span>;
  }

  return (
    <div className='flex flex-wrap gap-1'>
      {tagList.map((tag) => (
        <Badge key={tag} variant='secondary' className='text-[10px]'>
          {tag.trim()}
        </Badge>
      ))}
    </div>
  );
}
