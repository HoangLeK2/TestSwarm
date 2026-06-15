'use client';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Z_FLOATING } from '@/lib/z-index';

/** z-index for nested step editor — must sit above parent scenario/template dialogs. */
export const STEP_EDIT_OVERLAY_Z_INDEX = Z_FLOATING;

/**
 * Step editor layered above a parent Radix Dialog (scenario / template editors).
 * Uses a nested Dialog so focus trap and keyboard input work inside the parent modal.
 * Plain portals at higher z-index still sit outside the parent FocusScope and feel
 * "frozen" (cannot type in inputs).
 */
export function StepEditOverlay({
  onClose,
  children
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        className='max-w-lg gap-0 p-0 sm:max-w-xl'
        zIndex={STEP_EDIT_OVERLAY_Z_INDEX}
        onClose={onClose}
      >
        <DialogHeader className='sr-only'>
          <DialogTitle>Chỉnh sửa bước</DialogTitle>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}
