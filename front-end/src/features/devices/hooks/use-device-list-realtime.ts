'use client';

import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { useUser } from '@/features/auth/hooks/use-auth';
import type { DeviceOut } from '../services/manage-api';
import type { DeviceLifecycleEventPayload } from '../lib/lifecycle-events';
import { applyLifecycleMessage } from '../lib/lifecycle-message-handler';
import { setLifecycleWsConnected } from '../lib/lifecycle-ws-store';
import { connectLifecycleWs } from '../services/lifecycle-ws';

const DEAD_TOAST_DEDUP_MS = 5000;

function deviceDisplayLabel(
  device: DeviceOut | undefined,
  deviceId: string
): string {
  if (!device) return deviceId.slice(0, 8);
  const name = device.name || `${device.brand} ${device.model}`.trim();
  if (name) {
    const short =
      device.serial.length > 12
        ? `...${device.serial.slice(-8)}`
        : device.serial;
    return `${name} (${short})`;
  }
  return device.serial;
}

function maybeNotifyDeviceDead(
  event: DeviceLifecycleEventPayload,
  devices: DeviceOut[],
  lastToast: Map<string, number>,
  t: (key: string, values?: Record<string, string>) => string
) {
  if (event.to_state !== 'dead') return;
  const fromState = (event.from_state || '').toLowerCase();
  if (fromState !== 'reconnecting' && fromState !== 'busy') return;

  const now = Date.now();
  const last = lastToast.get(event.device_id) ?? 0;
  if (now - last < DEAD_TOAST_DEDUP_MS) return;
  lastToast.set(event.device_id, now);

  const row = devices.find((d) => d.id === event.device_id);
  const label = deviceDisplayLabel(row, event.device_id);
  const reason =
    typeof event.payload?.reason === 'string'
      ? event.payload.reason
      : undefined;
  const description =
    reason && reason !== 'reconnect_timeout'
      ? t('deadReason', { reason })
      : t('deadDescription');
  toast.error(t('deadTitle', { label }), {
    description,
    duration: 10_000
  });
}

/**
 * Patch device list + fleet stats from /ws/lifecycle (DF-T-02-015).
 * Falls back to slower HTTP polling when the stream is disconnected.
 */
export function useDeviceListRealtime(enabled = true) {
  const queryClient = useQueryClient();
  const { isLoading: authLoading, isSignedIn } = useUser();
  const t = useTranslations('devicesList.lifecycleToast');
  const lastDeadToastRef = useRef(new Map<string, number>());
  const streamEnabled = enabled && !authLoading && isSignedIn;

  useEffect(() => {
    if (!streamEnabled) {
      setLifecycleWsConnected(false);
      return;
    }

    const handle = connectLifecycleWs(
      (msg) =>
        applyLifecycleMessage(queryClient, msg, {
          onDeviceDead: (event, devices) =>
            maybeNotifyDeviceDead(event, devices, lastDeadToastRef.current, t)
        }),
      (connected) => setLifecycleWsConnected(connected)
    );

    return () => {
      handle.close();
      setLifecycleWsConnected(false);
    };
  }, [streamEnabled, queryClient, t]);
}
