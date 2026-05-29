'use client';
import {
  DEFAULT_DIALOG_Z_INDEX,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Separator } from './separator';
import { Loader2Icon } from 'lucide-react';

interface ModalProps {
  title: string | React.ReactNode;
  description?: string | React.ReactNode;
  isOpen: boolean;
  onClose?: () => void;
  onOpenChange?: (open: boolean) => void;
  children?: React.ReactNode;
  showHeader?: boolean;
  showFooter?: boolean;
  onConfirm?: () => void | Promise<void>;
  onCancel?: () => void;
  confirmText?: string;
  cancelText?: string;
  confirmVariant?:
    | 'default'
    | 'destructive'
    | 'outline'
    | 'secondary'
    | 'ghost'
    | 'link';
  isLoading?: boolean;
  wrapperClassName?: string;
  contentClassName?: string;
  disabled?: boolean;
  footer?: React.ReactNode;
  zIndex?: number;
}

export const Modal: React.FC<ModalProps> = ({
  title,
  description,
  isOpen,
  onClose,
  onOpenChange,
  children,
  showHeader = true,
  showFooter = false,
  footer,
  onConfirm,
  onCancel,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  confirmVariant = 'default',
  wrapperClassName,
  contentClassName,
  isLoading = false,
  disabled = false,
  zIndex = DEFAULT_DIALOG_Z_INDEX
}) => {
  const handleOpenChange = (open: boolean) => {
    if (onOpenChange) {
      onOpenChange(open);
    } else if (!open && onClose) {
      onClose();
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogContent
        className={cn(
          'z-50 max-w-3xl overflow-hidden p-0',
          !!wrapperClassName && wrapperClassName
        )}
        onClose={onClose}
        zIndex={zIndex}
      >
        {showHeader && (
          <DialogHeader className='bg-muted'>
            <div className='p-4'>
              <DialogTitle>{title}</DialogTitle>
              {description && (
                <DialogDescription>{description}</DialogDescription>
              )}
            </div>
            <Separator />
          </DialogHeader>
        )}
        {children && (
          <div className={cn('p-4', !!contentClassName && contentClassName)}>
            {children}
          </div>
        )}
        {showFooter && (
          <DialogFooter className='p-4'>
            {onCancel && (
              <Button
                variant='outline'
                onClick={onCancel}
                disabled={isLoading || disabled}
              >
                {cancelText}
              </Button>
            )}
            {onConfirm && (
              <Button
                variant={confirmVariant}
                onClick={onConfirm}
                disabled={isLoading || disabled}
              >
                {isLoading && <Loader2Icon className='h-4 w-4 animate-spin' />}
                {confirmText}
              </Button>
            )}
            {footer && footer}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
};
