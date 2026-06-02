'use client';

import { useEffect, useId, useState } from 'react';

const CHANNEL_NAME = 'device-farm-live-view';

type LiveViewMessage = {
  type: 'open' | 'close';
  serial: string;
  tabId: string;
};

/** Warn when the same device live view is open in another browser tab (DF-T-11-004 AC-4). */
export function useLiveViewTabLock(serial: string, enabled: boolean) {
  const tabId = useId();
  const [blockedByOtherTab, setBlockedByOtherTab] = useState(false);

  useEffect(() => {
    if (!enabled || !serial || typeof BroadcastChannel === 'undefined') {
      return undefined;
    }

    const channel = new BroadcastChannel(CHANNEL_NAME);
    let otherTabOpen = false;

    const onMessage = (event: MessageEvent<LiveViewMessage>) => {
      const msg = event.data;
      if (!msg || msg.serial !== serial || msg.tabId === tabId) return;
      if (msg.type === 'open') {
        otherTabOpen = true;
        setBlockedByOtherTab(true);
      }
      if (msg.type === 'close') {
        otherTabOpen = false;
        setBlockedByOtherTab(false);
      }
    };

    channel.addEventListener('message', onMessage);
    channel.postMessage({ type: 'open', serial, tabId } satisfies LiveViewMessage);

    return () => {
      channel.postMessage({ type: 'close', serial, tabId } satisfies LiveViewMessage);
      channel.removeEventListener('message', onMessage);
      channel.close();
      if (otherTabOpen) setBlockedByOtherTab(false);
    };
  }, [enabled, serial, tabId]);

  return { blockedByOtherTab };
}
