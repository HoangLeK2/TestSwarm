'use client';

import { useEffect, useState } from 'react';
import {
  fetchServerStatus,
  getServerStatusSync,
  startServerStatusPolling,
  subscribeServerStatus,
  type ServerStatus
} from './server-status';

export function useServerStatus(): ServerStatus {
  const [status, setStatus] = useState<ServerStatus>(() =>
    getServerStatusSync()
  );

  useEffect(() => {
    const unsub = subscribeServerStatus(setStatus);
    const stopPoll = startServerStatusPolling(30_000);
    fetchServerStatus().catch(() => undefined);
    return () => {
      unsub();
      stopPoll();
    };
  }, []);

  return status;
}
