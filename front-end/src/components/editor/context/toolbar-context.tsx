'use client';

import { createContext, useContext } from 'react';
import { LexicalEditor } from 'lexical';

const Context = createContext<{
  activeEditor: LexicalEditor;
  $updateToolbar: () => void;
  blockType: string;
  setBlockType: (blockType: string) => void;
  showModal: (
    title: string,
    showModal: (onClose: () => void) => React.ReactNode
  ) => void;
}>({
  activeEditor: {} as LexicalEditor,
  $updateToolbar: () => {},
  blockType: 'paragraph',
  setBlockType: () => {},
  showModal: () => {}
});

export function ToolbarContext({
  activeEditor,
  $updateToolbar,
  blockType,
  setBlockType,
  showModal,
  children
}: {
  activeEditor: LexicalEditor;
  $updateToolbar: () => void;
  blockType: string;
  setBlockType: (blockType: string) => void;
  showModal: (
    title: string,
    showModal: (onClose: () => void) => React.ReactNode
  ) => void;
  children: React.ReactNode;
}) {
  return (
    <Context.Provider
      value={{
        activeEditor,
        $updateToolbar,
        blockType,
        setBlockType,
        showModal
      }}
    >
      {children}
    </Context.Provider>
  );
}

export function useToolbarContext() {
  return useContext(Context);
}
