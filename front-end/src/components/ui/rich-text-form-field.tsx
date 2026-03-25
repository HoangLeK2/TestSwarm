'use client';

import { useCallback, useEffect, useState } from 'react';
import { LexicalComposer } from '@lexical/react/LexicalComposer';
import { OnChangePlugin } from '@lexical/react/LexicalOnChangePlugin';
import { useLexicalComposerContext } from '@lexical/react/LexicalComposerContext';
import { $generateHtmlFromNodes, $generateNodesFromDOM } from '@lexical/html';
import { $getRoot, $insertNodes, EditorState } from 'lexical';
import { cn } from '@/lib/utils';
import { FloatingLinkContext } from '@/components/editor/context/floating-link-context';
import { SharedAutocompleteContext } from '@/components/editor/context/shared-autocomplete-context';
import { editorTheme } from '@/components/editor/themes/editor-theme';
import { TooltipProvider } from '@/components/ui/tooltip';
import { nodes } from '@/components/blocks/editor-x/nodes';
import { Plugins } from '@/components/blocks/editor-x/plugins';
import type { InitialConfigType } from '@lexical/react/LexicalComposer';

interface RichTextFormFieldProps {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  editorClassName?: string;
}

const editorConfig: InitialConfigType = {
  namespace: 'RichTextFormField',
  theme: editorTheme,
  nodes,
  onError: () => {
    // console.error(error);
  }
};

function RichTextFormFieldInner({
  value,
  onChange,
  disabled
}: Pick<RichTextFormFieldProps, 'value' | 'onChange' | 'disabled'>) {
  const [editor] = useLexicalComposerContext();
  const [isInitialized, setIsInitialized] = useState(false);

  // Initialize editor with HTML value
  useEffect(() => {
    if (!isInitialized && value && value.trim() !== '') {
      editor.update(() => {
        const parser = new DOMParser();
        const dom = parser.parseFromString(value, 'text/html');
        const nodes = $generateNodesFromDOM(editor, dom);
        const root = $getRoot();
        root.clear();
        $insertNodes(nodes);
      });
      setIsInitialized(true);
    }
  }, [editor, value, isInitialized]);

  // Handle editor changes
  const handleEditorChange = useCallback(
    (editorState: EditorState) => {
      if (!onChange || disabled) return;

      const html = editorState.read(() => {
        return $generateHtmlFromNodes(editor, null);
      });

      onChange(html);
    },
    [editor, onChange, disabled]
  );

  return (
    <OnChangePlugin
      ignoreSelectionChange={true}
      onChange={handleEditorChange}
    />
  );
}

export function RichTextFormField({
  value,
  onChange,
  disabled,
  className,
  editorClassName = ''
}: RichTextFormFieldProps) {
  return (
    <div className={cn('relative w-full space-y-2 overflow-auto', className)}>
      <div
        className={cn(
          'rounded-lg border bg-background shadow',
          disabled && 'pointer-events-none opacity-50'
        )}
      >
        <LexicalComposer initialConfig={editorConfig}>
          <TooltipProvider>
            <SharedAutocompleteContext>
              <FloatingLinkContext>
                <Plugins className={editorClassName} />
                <RichTextFormFieldInner
                  value={value}
                  onChange={onChange}
                  disabled={disabled}
                />
              </FloatingLinkContext>
            </SharedAutocompleteContext>
          </TooltipProvider>
        </LexicalComposer>
      </div>
    </div>
  );
}
