'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { subscribeDeviceFarm } from '../services/ws';
import type { DeviceEvent, WsMessage } from '../types';
import { EventLogPanel } from './event-log-panel';

/**
 * Standalone device event notification bell for the global app header.
 * Self-subscribes to the shared WS — no dependency on useDeviceFarm hook.
 */
export function DeviceEventNotifications() {
  const t = useTranslations('devicesFarm.eventLog');
  const [events, setEvents] = useState<DeviceEvent[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const processedIds = useRef<Set<string>>(new Set());
  const lastToastTime = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    const unsub = subscribeDeviceFarm((msg: WsMessage) => {
      if (msg.type !== 'device_event') return;
      const evt = msg as unknown as DeviceEvent & { type: 'device_event' };
      if (!evt.id || !evt.serial) return;

      setEvents((prev) => [evt, ...prev].slice(0, 200));
      setUnreadCount((c) => c + 1);

      // Toast notification (deduplicate same serial+event within 5s)
      if (processedIds.current.has(evt.id)) return;
      processedIds.current.add(evt.id);
      if (processedIds.current.size > 300) {
        const arr = Array.from(processedIds.current);
        processedIds.current = new Set(arr.slice(-200));
      }

      const dedupKey = `${evt.serial}:${evt.event}`;
      const now = Date.now();
      const lastTime = lastToastTime.current.get(dedupKey) ?? 0;
      if (now - lastTime < 5000) return;
      lastToastTime.current.set(dedupKey, now);

      const nameParts = [evt.device_brand, evt.device_model].filter(Boolean);
      const short =
        evt.serial.length > 12 ? `...${evt.serial.slice(-8)}` : evt.serial;
      const label =
        nameParts.length > 0 ? `${nameParts.join(' ')} (${short})` : evt.serial;

      switch (evt.event) {
        case 'disconnected':
          toast.error(t('toastDisconnected', { label }), {
            description: evt.reason || t('connectionLost'),
            duration: 8000
          });
          break;
        case 'reconnected':
        case 'connected':
          toast.success(t('toastConnected', { label }), { duration: 5000 });
          break;
        case 'error':
          toast.warning(t('toastError', { label }), {
            description: evt.reason,
            duration: 6000
          });
          break;
        case 'dead':
          toast.error(t('toastDead', { label }), {
            description: evt.reason || t('deviceMarkedDead'),
            duration: 10000
          });
          break;
      }
    });

    return unsub;
  }, [t]);

  const clearUnread = useCallback(() => setUnreadCount(0), []);

  return (
    <EventLogPanel
      realtimeEvents={events}
      unreadCount={unreadCount}
      onOpen={clearUnread}
    />
  );
}
