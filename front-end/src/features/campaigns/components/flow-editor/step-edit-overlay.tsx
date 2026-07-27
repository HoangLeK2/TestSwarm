'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { XIcon } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Z_FLOATING } from '@/lib/z-index';
import { resolveStepEditOverlayHost } from './nested-step-edit';

/** z-index for nested step editor — must sit above parent scenario/template dialogs. */
export const STEP_EDIT_OVERLAY_Z_INDEX = Z_FLOATING;

/**
 * Step editor layered above a parent Radix Dialog (scenario / template editors).
 * The portal stays inside the closest parent modal so its inputs remain in that
 * modal's focus scope. A nested Radix Dialog can leave only its backdrop mounted
 * under React 19, while a body-level custom portal is outside the parent focus trap.
 */
export function StepEditOverlay({
  onClose,
  children
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  const [host, setHost] = useState<HTMLElement | null>(null);
  onCloseRef.current = onClose;

  useLayoutEffect(() => {
    setHost(resolveStepEditOverlayHost(anchorRef.current, document.body));
  }, []);

  useEffect(() => {
    if (!host) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
    };

    window.addEventListener('keydown', onKeyDown);
    panelRef.current?.focus();

    return () => {
      window.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus();
    };
  }, [host]);

  return (
    <>
      <span ref={anchorRef} className='hidden' aria-hidden='true' />
      {host
        ? createPortal(
            <div
              className={cn(
                'inset-0 flex items-center justify-center p-4',
                host === document.body ? 'fixed' : 'absolute'
              )}
              style={{ zIndex: STEP_EDIT_OVERLAY_Z_INDEX }}
              role='dialog'
              aria-modal='true'
              aria-label='Chỉnh sửa bước'
            >
              <button
                type='button'
                className='absolute inset-0 bg-background/60 backdrop-blur-sm'
                aria-label='Đóng'
                onClick={() => onCloseRef.current()}
              />
              <div
                ref={panelRef}
                className='relative z-10 grid w-full max-w-lg overflow-hidden rounded-lg border bg-background shadow-lg outline-none sm:max-w-xl'
                tabIndex={-1}
              >
                {children}
                <button
                  type='button'
                  className='rounded-xs focus:outline-hidden absolute right-4 top-4 z-20 cursor-pointer opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:ring-2 focus:ring-ring focus:ring-offset-2'
                  aria-label='Đóng'
                  onClick={() => onCloseRef.current()}
                >
                  <XIcon className='size-4' />
                </button>
              </div>
            </div>,
            host
          )
        : null}
    </>
  );
}
