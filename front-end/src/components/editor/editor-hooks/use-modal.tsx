import { useCallback, useMemo, useState } from 'react';
import * as React from 'react';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';

export function useEditorModal(): [
  React.ReactNode | null,
  (title: string, showModal: (onClose: () => void) => React.ReactNode) => void
] {
  const [modalContent, setModalContent] = useState<null | {
    closeOnClickOutside: boolean;
    content: React.ReactNode;
    title: string;
  }>(null);

  const onClose = useCallback(() => {
    setModalContent(null);
  }, []);

  const modal = useMemo(() => {
    if (modalContent === null) {
      return null;
    }
    const { title, content } = modalContent;
    return (
      <Dialog open={true} onOpenChange={onClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
          </DialogHeader>
          {content}
        </DialogContent>
      </Dialog>
    );
  }, [modalContent, onClose]);

  const showModal = useCallback(
    (
      title: string,
      getContent: (onClose: () => void) => React.ReactNode,
      closeOnClickOutside = false
    ) => {
      setModalContent({
        closeOnClickOutside,
        content: getContent(onClose),
        title
      });
    },
    [onClose]
  );

  return [modal, showModal];
}
