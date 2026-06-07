'use client';

import { useEffect, useState } from 'react';
import { isCurrentTabNetworkActive } from '../lib/tab-network-activity';

export function useTabNetworkActive(): boolean {
  const [active, setActive] = useState(isCurrentTabNetworkActive);

  useEffect(() => {
    const update = () => setActive(isCurrentTabNetworkActive());
    document.addEventListener('visibilitychange', update);
    window.addEventListener('focus', update);
    window.addEventListener('pageshow', update);
    window.addEventListener('pagehide', update);
    update();
    return () => {
      document.removeEventListener('visibilitychange', update);
      window.removeEventListener('focus', update);
      window.removeEventListener('pageshow', update);
      window.removeEventListener('pagehide', update);
    };
  }, []);

  return active;
}
