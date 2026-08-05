'use client';

import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { formatDistanceToNow } from 'date-fns';
import { enUS, vi } from 'date-fns/locale';
import {
  AlertTriangle,
  ArrowLeft,
  ExternalLink,
  Loader2,
  PlayCircle,
  Radio
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { ROUTES } from '@/config/routes';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Can } from '@/features/auth';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { DeviceAndroidFrame } from '../device-android-frame';
import { DeviceScreen } from '../device-screen';
import { useLiveViewTabLock } from '../../hooks/use-live-view-tab-lock';
import {
  invalidateDeviceFleetQueries,
  useDeviceBySerial,
  useDeviceSessions
} from '../../hooks/use-devices';
import { deviceReservationApi } from '../../services/reservation-api';
import {
  DEVICE_FSM_BADGE_CLASS,
  DEVICE_FSM_BADGE_VARIANT,
  deviceFsmStateOf
} from '../../lib/device-fsm';
import { isDeviceOnlineForList } from '../../lib/device-online';
import type { Device } from '../../types';
import type { DeviceOut, RelayAgentOut } from '../../services/manage-api';
import { fetchConfig } from '../../services/api';
import { ensureWatchSerial } from '../../services/ws';

function deviceOutToStreamDevice(
  row: DeviceOut,
  live?: Partial<Device> | null
): Device {
  return {
    serial: row.serial,
    name: row.name,
    brand: row.brand,
    model: row.model,
    state: live?.state ?? row.state,
    battery: live?.battery ?? 0,
    screen_width: row.screen_width,
    screen_height: row.screen_height,
    current_app: live?.current_app,
    relay_scrcpy_enabled: live?.relay_scrcpy_enabled,
    scenario_active: live?.scenario_active
  };
}

type DeviceDetailViewProps = {
  serial: string;
  liveDevice?: Device | null;
  relayMap?: Record<string, RelayAgentOut>;
};

export function DeviceDetailView({
  serial,
  liveDevice,
  relayMap = {}
}: DeviceDetailViewProps) {
  const locale = useLocale();
  const dateLocale = locale.startsWith('vi') ? vi : enUS;
  const t = useTranslations('devicesDetail');
  const tList = useTranslations('devicesList');
  const perms = useResourcePermissions('devices');

  const { data: deviceRow, isLoading, error } = useDeviceBySerial(serial);
  const { data: sessions, isLoading: sessionsLoading } = useDeviceSessions(
    deviceRow?.id ?? ''
  );
  const { data: appConfig } = useQuery({
    queryKey: ['device-farm', 'config'],
    queryFn: fetchConfig,
    staleTime: 60_000
  });

  const streamDevice = useMemo(
    () => (deviceRow ? deviceOutToStreamDevice(deviceRow, liveDevice) : null),
    [deviceRow, liveDevice]
  );

  const isActive =
    streamDevice?.state &&
    !['DISCONNECTED', 'DEAD'].includes(streamDevice.state.toUpperCase());

  const [liveViewOpen, setLiveViewOpen] = useState(false);
  const { blockedByOtherTab } = useLiveViewTabLock(
    serial,
    liveViewOpen && Boolean(isActive)
  );

  const qc = useQueryClient();
  const reserveMutation = useMutation({
    mutationFn: () => deviceReservationApi.reserve(serial),
    onSuccess: () => {
      toast.success(t('reserveSuccess'));
      invalidateDeviceFleetQueries(qc);
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? String(
              (err as { response?: { data?: { detail?: string } } }).response
                ?.data?.detail ?? ''
            )
          : '';
      toast.error(t('reserveFailed'), { description: msg || undefined });
    }
  });

  const releaseMutation = useMutation({
    mutationFn: () => deviceReservationApi.release(serial),
    onSuccess: () => {
      toast.success(t('releaseSuccess'));
      invalidateDeviceFleetQueries(qc);
    },
    onError: () => toast.error(t('releaseFailed'))
  });

  const fsm = deviceRow ? deviceFsmStateOf(deviceRow) : 'unknown';
  const transportOnline = deviceRow
    ? isDeviceOnlineForList(deviceRow, relayMap)
    : false;
  const liveStreamTransport = appConfig?.webrtc_enabled ? 'webrtc' : 'auto';

  const noopWsSend = useCallback((_obj: object) => {}, []);

  if (isLoading) {
    return (
      <div className='flex items-center gap-2 py-16 text-sm text-muted-foreground'>
        <Loader2 className='size-4 animate-spin' />
        {t('loading')}
      </div>
    );
  }

  if (error || !deviceRow || !streamDevice) {
    return (
      <div className='space-y-4 py-8'>
        <Button asChild variant='ghost' size='sm'>
          <Link href={ROUTES.DEVICES.MANAGE}>
            <ArrowLeft className='mr-1.5 size-4' />
            {t('backToList')}
          </Link>
        </Button>
        <p className='text-sm text-destructive'>{t('notFound')}</p>
      </div>
    );
  }

  const label =
    deviceRow.name ||
    `${deviceRow.brand} ${deviceRow.model}`.trim() ||
    deviceRow.serial;

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div className='space-y-1'>
          <Button asChild variant='ghost' size='sm' className='-ml-2 h-8 px-2'>
            <Link href={ROUTES.DEVICES.MANAGE}>
              <ArrowLeft className='mr-1.5 size-4' />
              {t('backToList')}
            </Link>
          </Button>
          <h1 className='text-xl font-bold tracking-tight'>{label}</h1>
          <p className='font-mono text-xs text-muted-foreground'>
            {deviceRow.serial}
          </p>
        </div>
        <div className='flex flex-wrap items-center gap-2'>
          <Badge
            variant={DEVICE_FSM_BADGE_VARIANT[fsm]}
            className={DEVICE_FSM_BADGE_CLASS[fsm]}
          >
            {tList(`fsm.${fsm}`)}
          </Badge>
          <Badge variant={transportOnline ? 'default' : 'secondary'}>
            {transportOnline
              ? tList('transportOnline')
              : tList('transportOffline')}
          </Badge>
        </div>
      </div>

      <div className='grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]'>
        <Card className='overflow-hidden'>
          <CardHeader className='flex flex-row items-center justify-between gap-2 border-b py-3'>
            <CardTitle className='text-sm font-medium'>
              {t('liveViewTitle')}
            </CardTitle>
            {isActive ? (
              <Badge
                variant='outline'
                className='gap-1 text-[10px] text-emerald-600'
              >
                <Radio className='size-3' />
                {liveViewOpen ? t('liveBadge') : t('liveIdle')}
              </Badge>
            ) : null}
          </CardHeader>
          <CardContent className='p-4'>
            {blockedByOtherTab ? (
              <Alert variant='destructive' className='mb-4'>
                <AlertTriangle className='size-4' />
                <AlertTitle>{t('crossTabTitle')}</AlertTitle>
                <AlertDescription>
                  {t('crossTabDescription', { serial })}
                </AlertDescription>
              </Alert>
            ) : null}

            {!isActive ? (
              <div className='flex min-h-[360px] flex-col items-center justify-center rounded-lg bg-muted/30 px-4 text-center'>
                <p className='text-sm font-medium text-foreground'>
                  {t('offlineTitle')}
                </p>
                <p className='mt-1 text-xs text-muted-foreground'>
                  {t('offlineHint')}
                </p>
              </div>
            ) : !liveViewOpen ? (
              <div className='flex min-h-[280px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/10 px-4 text-center'>
                <p className='text-sm text-muted-foreground'>
                  {t('liveViewHint')}
                </p>
                <Button
                  size='sm'
                  disabled={blockedByOtherTab}
                  onClick={() => {
                    ensureWatchSerial(serial);
                    setLiveViewOpen(true);
                  }}
                >
                  {t('openLiveView')}
                </Button>
              </div>
            ) : (
              <div className='mx-auto max-w-[320px]'>
                <DeviceAndroidFrame
                  screenWidth={300}
                  deviceWidth={streamDevice.screen_width}
                  deviceHeight={streamDevice.screen_height}
                >
                  <DeviceScreen
                    device={streamDevice}
                    wsSend={noopWsSend}
                    mode='tap'
                    interactive={false}
                    captionBelowFrame
                    streamFetchPriority='high'
                    streamTransport={liveStreamTransport}
                  />
                </DeviceAndroidFrame>
              </div>
            )}
          </CardContent>
        </Card>

        <div className='space-y-4'>
          <Card>
            <CardHeader className='py-3'>
              <CardTitle className='text-sm'>{t('metadataTitle')}</CardTitle>
            </CardHeader>
            <CardContent className='space-y-2 text-xs'>
              <MetaRow
                label={t('metaModel')}
                value={`${deviceRow.brand} ${deviceRow.model}`}
              />
              <MetaRow
                label={t('metaAndroid')}
                value={`${deviceRow.android_version} (SDK ${deviceRow.sdk_version})`}
              />
              <MetaRow
                label={t('metaScreen')}
                value={`${deviceRow.screen_width}×${deviceRow.screen_height}`}
              />
              {deviceRow.adb_serial ? (
                <MetaRow
                  label={t('metaAdb')}
                  value={deviceRow.adb_serial}
                  mono
                />
              ) : null}
              {deviceRow.last_seen ? (
                <MetaRow
                  label={t('metaLastSeen')}
                  value={formatDistanceToNow(new Date(deviceRow.last_seen), {
                    addSuffix: true,
                    locale: dateLocale
                  })}
                />
              ) : null}
              {deviceRow.tags ? (
                <MetaRow label={t('metaTags')} value={deviceRow.tags} />
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className='py-3'>
              <CardTitle className='text-sm'>{t('sessionTitle')}</CardTitle>
            </CardHeader>
            <CardContent className='space-y-3'>
              <div className='flex flex-wrap gap-2'>
                <Can object='devices' action='execute'>
                  <Button
                    size='sm'
                    variant='default'
                    disabled={reserveMutation.isPending || !isActive}
                    onClick={() => reserveMutation.mutate()}
                  >
                    {t('reserve')}
                  </Button>
                  <Button
                    size='sm'
                    variant='outline'
                    disabled={releaseMutation.isPending}
                    onClick={() => releaseMutation.mutate()}
                  >
                    {t('release')}
                  </Button>
                </Can>
                {perms.canExecute && isActive ? (
                  <Button asChild size='sm' variant='secondary'>
                    <Link
                      href={ROUTES.DEVICES.CONTROL_RECORD_WITH_SERIAL(serial)}
                    >
                      <PlayCircle className='mr-1.5 size-4' />
                      {t('runScenario')}
                    </Link>
                  </Button>
                ) : null}
              </div>

              {sessionsLoading ? (
                <p className='text-xs text-muted-foreground'>
                  {t('sessionsLoading')}
                </p>
              ) : !sessions?.length ? (
                <p className='text-xs text-muted-foreground'>
                  {t('sessionsEmpty')}
                </p>
              ) : (
                <ul className='max-h-48 space-y-2 overflow-y-auto text-xs'>
                  {sessions.slice(0, 8).map((s) => (
                    <li
                      key={s.id}
                      className='rounded-md border border-border/60 px-2 py-1.5'
                    >
                      <div className='font-mono text-[10px] text-muted-foreground'>
                        {s.client_ip || '—'}
                      </div>
                      <div className='mt-0.5'>
                        {formatDistanceToNow(new Date(s.connected_at), {
                          addSuffix: true,
                          locale: dateLocale
                        })}
                        {s.disconnected_at
                          ? ` · ${t('sessionEnded')}`
                          : ` · ${t('sessionActive')}`}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Button asChild variant='outline' size='sm' className='w-full'>
            <Link href={ROUTES.DEVICES.ROOT}>
              <ExternalLink className='mr-1.5 size-4' />
              {t('openFleetView')}
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}

function MetaRow({
  label,
  value,
  mono
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className='flex justify-between gap-3'>
      <span className='shrink-0 text-muted-foreground'>{label}</span>
      <span className={mono ? 'truncate text-right font-mono' : 'text-right'}>
        {value}
      </span>
    </div>
  );
}
