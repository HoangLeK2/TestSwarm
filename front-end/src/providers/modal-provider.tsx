'use client';

import * as React from 'react';
import { useTranslations } from 'next-intl';
import { DEFAULT_DIALOG_Z_INDEX } from '@/components/ui/dialog';
import { Modal } from '@/components/ui/modal';

interface ConfirmModalOptions {
  title?: string | React.ReactNode;
  description?: string | React.ReactNode;
  confirmText?: string;
  cancelText?: string;
  content?: React.ReactNode;
  confirmVariant?:
    | 'default'
    | 'destructive'
    | 'outline'
    | 'secondary'
    | 'ghost'
    | 'link';
  onConfirm?: () => void | Promise<void>;
  onCancel?: () => void;
  zIndex?: number;
}

interface ModalContextType {
  confirm: (options: ConfirmModalOptions) => Promise<boolean>;
  showModal: (
    content: React.ReactNode,
    options?: Partial<ConfirmModalOptions>
  ) => void;
  closeModal: () => void;
}

const ModalContext = React.createContext<ModalContextType | null>(null);

interface ModalState {
  isOpen: boolean;
  title?: string | React.ReactNode;
  description?: string | React.ReactNode;
  content?: React.ReactNode;
  confirmText?: string;
  cancelText?: string;
  confirmVariant?:
    | 'default'
    | 'destructive'
    | 'outline'
    | 'secondary'
    | 'ghost'
    | 'link';
  onConfirm?: () => void | Promise<void>;
  onCancel?: () => void;
  isLoading: boolean;
  resolve?: (value: boolean) => void;
  zIndex?: number;
}

export function ModalProvider({ children }: { children: React.ReactNode }) {
  const t = useTranslations('components.modal');
  const [state, setState] = React.useState<ModalState>({
    isOpen: false,
    isLoading: false,
    zIndex: DEFAULT_DIALOG_Z_INDEX
  });

  const confirm = React.useCallback(
    (options: ConfirmModalOptions): Promise<boolean> => {
      return new Promise((resolve) => {
        setState({
          isOpen: true,
          title: options.title || t('confirmAction'),
          description: options.description || t('areYouSure'),
          confirmText: options.confirmText || t('confirm'),
          cancelText: options.cancelText || t('cancel'),
          content: options.content,
          confirmVariant: options.confirmVariant || 'default',
          onConfirm: options.onConfirm,
          onCancel: options.onCancel,
          isLoading: false,
          resolve,
          zIndex: options.zIndex ?? DEFAULT_DIALOG_Z_INDEX
        });
      });
    },
    [t]
  );

  const showModal = React.useCallback(
    (content: React.ReactNode, options: Partial<ConfirmModalOptions> = {}) => {
      setState({
        isOpen: true,
        content,
        title: options.title,
        description: options.description,
        confirmText: options.confirmText,
        cancelText: options.cancelText,
        confirmVariant: options.confirmVariant,
        onConfirm: options.onConfirm,
        onCancel: options.onCancel,
        isLoading: false,
        zIndex: options.zIndex ?? DEFAULT_DIALOG_Z_INDEX
      });
    },
    []
  );

  const closeModal = React.useCallback(() => {
    setState((prev) => ({
      ...prev,
      isOpen: false
    }));
  }, []);

  const handleConfirm = React.useCallback(async () => {
    if (state.onConfirm) {
      setState((prev) => ({ ...prev, isLoading: true }));
      try {
        await state.onConfirm();
        setState((prev) => ({ ...prev, isLoading: false, isOpen: false }));
        state.resolve?.(true);
      } catch (error) {
        setState((prev) => ({ ...prev, isLoading: false }));
        console.error('Modal confirm error:', error);
      }
    } else {
      setState((prev) => ({ ...prev, isOpen: false }));
      state.resolve?.(true);
    }
  }, [state.onConfirm, state.resolve]);

  const handleCancel = React.useCallback(() => {
    state.onCancel?.();
    setState((prev) => ({ ...prev, isOpen: false }));
    state.resolve?.(false);
  }, [state.onCancel, state.resolve]);

  const handleOpenChange = React.useCallback(
    (open: boolean) => {
      if (!open) {
        setState((prev) => ({ ...prev, isOpen: false }));
        state.resolve?.(false);
      }
    },
    [state.resolve]
  );

  const contextValue = React.useMemo(
    () => ({
      confirm,
      showModal,
      closeModal
    }),
    [confirm, showModal, closeModal]
  );

  return (
    <ModalContext.Provider value={contextValue}>
      {children}
      <Modal
        isOpen={state.isOpen}
        onOpenChange={handleOpenChange}
        title={state.title || ''}
        description={state.description || ''}
        showFooter={!!(state.onConfirm || state.onCancel || state.resolve)}
        showHeader={!!(state.title || state.description)}
        onConfirm={state.onConfirm || state.resolve ? handleConfirm : undefined}
        onCancel={handleCancel}
        confirmText={state.confirmText}
        cancelText={state.cancelText}
        confirmVariant={state.confirmVariant}
        isLoading={state.isLoading}
        zIndex={state.zIndex ?? DEFAULT_DIALOG_Z_INDEX}
      >
        {state.content}
      </Modal>
    </ModalContext.Provider>
  );
}

export function useModal() {
  const context = React.useContext(ModalContext);
  if (!context) {
    throw new Error('useModal must be used within a ModalProvider');
  }
  return context;
}

// Convenience hook for confirmation dialogs
export function useConfirm() {
  const { confirm } = useModal();
  return confirm;
}
