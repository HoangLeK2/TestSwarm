'use client';

import { PlusIcon } from 'lucide-react';

import { useEditorModal } from '@/components/editor/editor-hooks/use-modal';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectTrigger
} from '@/components/ui/select';
import { useTranslations } from 'next-intl';

export function BlockInsertPlugin({ children }: { children: React.ReactNode }) {
  const [modal] = useEditorModal();
  const t = useTranslations('components.editor.common');

  return (
    <>
      {modal}
      <Select value={''}>
        <SelectTrigger className='!h-8 w-min gap-1'>
          <PlusIcon className='size-4' />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>{children}</SelectGroup>
        </SelectContent>
      </Select>
    </>
  );
}
