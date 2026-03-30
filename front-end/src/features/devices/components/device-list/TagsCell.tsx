'use client';

import { useState } from 'react';
import { Check, Pencil } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { farmApi } from '@/lib/farm-api';
import { useQueryClient } from '@tanstack/react-query';

export function TagsCell({ deviceId, tags }: { deviceId: string; tags?: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(tags ?? '');
  const [saving, setSaving] = useState(false);
  const qc = useQueryClient();

  const save = async () => {
    setSaving(true);
    try {
      await farmApi.patch(`/devices/${deviceId}/tags`, { tags: value });
      qc.invalidateQueries({ queryKey: ['devices'] });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <div className='flex items-center gap-1'>
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className='h-7 w-32 text-xs'
          placeholder='tag1, tag2'
          onKeyDown={(e) => e.key === 'Enter' && save()}
          autoFocus
        />
        <Button
          size='icon'
          variant='ghost'
          className='size-6'
          disabled={saving}
          onClick={save}
        >
          <Check size={12} />
        </Button>
      </div>
    );
  }

  const tagList = (tags ?? '').split(',').filter(Boolean);

  return (
    <div className='flex items-center gap-1'>
      {tagList.length > 0 ? (
        <div className='flex flex-wrap gap-1'>
          {tagList.map((tag) => (
            <Badge key={tag} variant='secondary' className='text-[10px]'>
              {tag.trim()}
            </Badge>
          ))}
        </div>
      ) : (
        <span className='text-[11px] text-muted-foreground'>—</span>
      )}
      <Button
        size='icon'
        variant='ghost'
        className='size-5 shrink-0 opacity-0 group-hover/row:opacity-100'
        onClick={() => { setValue(tags ?? ''); setEditing(true); }}
      >
        <Pencil size={10} />
      </Button>
    </div>
  );
}
