'use client';

import { useEffect, useState } from 'react';
import {
  fetchServerStatus,
  getServerStatusSync,
  startServerStatusPolling,
  subscribeServerStatus,
  type ServerStatus
} from './server-status';

export function useServerStatus(options: { poll?: boolean } = {}): ServerStatus {
  const poll = options.poll ?? true;
  const [status, setStatus] = useState<ServerStatus>(() =>
    getServerStatusSync()
  );

  useEffect(() => {
    const unsub = subscribeServerStatus(setStatus);
    const stopPoll = poll
      ? startServerStatusPolling(30_000)
      : () => undefined;
    fetchServerStatus().catch(() => undefined);
    return () => {
      unsub();
      stopPoll();
    };
  }, [poll]);

  return status;
}
