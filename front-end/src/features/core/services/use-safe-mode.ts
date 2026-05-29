'use client';

import { useEffect, useState } from 'react';
import {
  fetchSafeMode,
  getSafeModeSync,
  subscribeSafeMode,
  type SafeMode
} from './safe-mode';

/** Hook that returns the current safe-mode flags, kicking off a one-time fetch. */
export function useSafeMode(): SafeMode {
  const [mode, setMode] = useState<SafeMode>(() => getSafeModeSync());

  useEffect(() => {
    const unsub = subscribeSafeMode(setMode);
    fetchSafeMode().catch(() => undefined);
    return unsub;
  }, []);

  return mode;
}
