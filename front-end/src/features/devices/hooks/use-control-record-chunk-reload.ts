'use client';

import { useEffect } from 'react';

export function useControlRecordChunkReloadGuard() {
  useEffect(() => {
    const reloadKey = 'control-record-chunk-reload';
    const reloadOnce = (message: string) => {
      if (
        !message.includes('Failed to load chunk') &&
        !message.includes('Loading chunk')
      ) {
        return;
      }
      if (sessionStorage.getItem(reloadKey)) return;
      sessionStorage.setItem(reloadKey, '1');
      window.location.reload();
    };
    const onError = (event: ErrorEvent) => reloadOnce(event.message ?? '');
    const onRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      const message =
        typeof reason === 'string'
          ? reason
          : reason instanceof Error
            ? reason.message
            : String(reason ?? '');
      reloadOnce(message);
    };
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
    };
  }, []);
}
