'use client';

import { TableIcon } from 'lucide-react';

import { useToolbarContext } from '@/components/editor/context/toolbar-context';
import { InsertTableDialog } from '@/components/editor/plugins/table-plugin';
import { SelectItem } from '@/components/ui/select';
import { useTranslations } from 'next-intl';

export function InsertTable() {
  const { activeEditor, showModal } = useToolbarContext();
  const t = useTranslations('components.editor.table');

  return (
    <SelectItem
      value='table'
      onPointerUp={() =>
        showModal(t('insertTable'), (onClose) => (
          <InsertTableDialog activeEditor={activeEditor} onClose={onClose} />
        ))
      }
      className=''
    >
      <div className='flex items-center gap-1'>
        <TableIcon className='size-4' />
        <span>{t('table')}</span>
      </div>
    </SelectItem>
  );
}
