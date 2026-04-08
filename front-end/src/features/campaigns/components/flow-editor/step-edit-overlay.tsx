'use client';

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

/**
 * Full-screen overlay for editing a step — use instead of Radix Dialog when FlowEditor
 * is already inside another Dialog. Nested Radix Dialogs + Presence can infinite-loop on React 19.
 */
export function StepEditOverlay({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className='fixed inset-0 z-[10050] flex items-center justify-center p-4'
      role='dialog'
      aria-modal='true'
    >
      <button
        type='button'
        className='absolute inset-0 bg-background/60 backdrop-blur-sm'
        aria-label='Đóng'
        onClick={() => onCloseRef.current()}
      />
      <div
        className='relative z-10 grid w-full max-w-sm gap-0 overflow-hidden rounded-lg border bg-background p-0 shadow-lg'
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
