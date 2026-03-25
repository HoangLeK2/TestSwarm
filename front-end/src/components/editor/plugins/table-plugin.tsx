'use client';

/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import * as React from 'react';
import { useLexicalComposerContext } from '@lexical/react/LexicalComposerContext';
import {
  $createTableNodeWithDimensions,
  INSERT_TABLE_COMMAND,
  TableNode
} from '@lexical/table';
import {
  $insertNodes,
  COMMAND_PRIORITY_EDITOR,
  createCommand,
  EditorThemeClasses,
  Klass,
  LexicalCommand,
  LexicalEditor,
  LexicalNode
} from 'lexical';

import { invariant } from '@/components/editor/shared/invariant';
import { Button } from '@/components/ui/button';
import { DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useTranslations } from 'next-intl';

export type InsertTableCommandPayload = Readonly<{
  columns: string;
  rows: string;
  includeHeaders?: boolean;
}>;

export type CellContextShape = {
  cellEditorConfig: null | CellEditorConfig;
  cellEditorPlugins: null | React.ReactNode | Array<React.ReactNode>;
  set: (
    cellEditorConfig: null | CellEditorConfig,
    cellEditorPlugins: null | React.ReactNode | Array<React.ReactNode>
  ) => void;
};

export type CellEditorConfig = Readonly<{
  namespace: string;
  nodes?: ReadonlyArray<Klass<LexicalNode>>;
  onError: (error: Error, editor: LexicalEditor) => void;
  readOnly?: boolean;
  theme?: EditorThemeClasses;
}>;

export const INSERT_NEW_TABLE_COMMAND: LexicalCommand<InsertTableCommandPayload> =
  createCommand('INSERT_NEW_TABLE_COMMAND');

export const CellContext = createContext<CellContextShape>({
  cellEditorConfig: null,
  cellEditorPlugins: null,
  set: () => {
    // Empty
  }
});

export function TableContext({ children }: { children: React.ReactNode }) {
  const [contextValue, setContextValue] = useState<{
    cellEditorConfig: null | CellEditorConfig;
    cellEditorPlugins: null | React.ReactNode | Array<React.ReactNode>;
  }>({
    cellEditorConfig: null,
    cellEditorPlugins: null
  });
  return (
    <CellContext.Provider
      value={useMemo(
        () => ({
          cellEditorConfig: contextValue.cellEditorConfig,
          cellEditorPlugins: contextValue.cellEditorPlugins,
          set: (cellEditorConfig, cellEditorPlugins) => {
            setContextValue({ cellEditorConfig, cellEditorPlugins });
          }
        }),
        [contextValue.cellEditorConfig, contextValue.cellEditorPlugins]
      )}
    >
      {children}
    </CellContext.Provider>
  );
}

export function InsertTableDialog({
  activeEditor,
  onClose
}: {
  activeEditor: LexicalEditor;
  onClose: () => void;
}): React.ReactNode {
  const [rows, setRows] = useState('5');
  const [columns, setColumns] = useState('5');
  const [isDisabled, setIsDisabled] = useState(true);
  const t = useTranslations('components.editor.table');

  useEffect(() => {
    const row = Number(rows);
    const column = Number(columns);
    if (row && row > 0 && row <= 500 && column && column > 0 && column <= 50) {
      setIsDisabled(false);
    } else {
      setIsDisabled(true);
    }
  }, [rows, columns]);

  const onClick = () => {
    activeEditor.dispatchCommand(INSERT_TABLE_COMMAND, {
      columns,
      rows
    });

    onClose();
  };

  return (
    <>
      <div className='grid gap-4'>
        <div className='grid gap-2'>
          <Label htmlFor='rows'>{t('numberOfRows')}</Label>
          <Input
            id='rows'
            placeholder={'# of rows (1-500)'}
            onChange={(e) => setRows(e.target.value)}
            value={rows}
            data-test-id='table-modal-rows'
            type='number'
          />
        </div>
        <div className='grid gap-2'>
          <Label htmlFor='columns'>{t('numberOfColumns')}</Label>
          <Input
            id='columns'
            placeholder={'# of columns (1-50)'}
            onChange={(e) => setColumns(e.target.value)}
            value={columns}
            data-test-id='table-modal-columns'
            type='number'
          />
        </div>
      </div>
      <DialogFooter data-test-id='table-model-confirm-insert'>
        <Button disabled={isDisabled} onClick={onClick}>
          {t('confirm')}
        </Button>
      </DialogFooter>
    </>
  );
}

export function TablePlugin({
  cellEditorConfig,
  children
}: {
  cellEditorConfig: CellEditorConfig;
  children: React.ReactNode | Array<React.ReactNode>;
}): React.ReactNode | null {
  const [editor] = useLexicalComposerContext();
  const cellContext = useContext(CellContext);

  useEffect(() => {
    if (!editor.hasNodes([TableNode])) {
      invariant(false, 'TablePlugin: TableNode is not registered on editor');
    }

    cellContext.set(cellEditorConfig, children);

    return editor.registerCommand<InsertTableCommandPayload>(
      INSERT_NEW_TABLE_COMMAND,
      ({ columns, rows, includeHeaders }) => {
        const tableNode = $createTableNodeWithDimensions(
          Number(rows),
          Number(columns),
          includeHeaders
        );
        $insertNodes([tableNode]);
        return true;
      },
      COMMAND_PRIORITY_EDITOR
    );
  }, [cellContext, cellEditorConfig, children, editor]);

  return null;
}
