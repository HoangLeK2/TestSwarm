'use client';

import { ImageIcon } from 'lucide-react';

import { useToolbarContext } from '@/components/editor/context/toolbar-context';
import { InsertImageDialog } from '@/components/editor/plugins/images-plugin';
import { SelectItem } from '@/components/ui/select';
import { useTranslations } from 'next-intl';

export function InsertImage() {
  const { activeEditor, showModal } = useToolbarContext();
  const t = useTranslations('components.editor.image');

  return (
    <SelectItem
      value='image'
      onPointerUp={(e) => {
        showModal(t('insertImage'), (onClose) => (
          <InsertImageDialog activeEditor={activeEditor} onClose={onClose} />
        ));
      }}
      className=''
    >
      <div className='flex items-center gap-1'>
        <ImageIcon className='size-4' />
        <span>{t('image')}</span>
      </div>
    </SelectItem>
  );
}
