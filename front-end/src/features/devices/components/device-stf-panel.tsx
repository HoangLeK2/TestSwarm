'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Battery,
  BatteryCharging,
  Bluetooth,
  BluetoothOff,
  ChevronDown,
  ChevronUp,
  Clipboard,
  ClipboardCopy,
  Loader2,
  Lock,
  LockOpen,
  RotateCw,
  Scan,
  Signal,
  SignalZero,
  Volume2,
  VolumeX,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import {
  stfGetClipboard,
  stfIdentify,
  stfSetBluetooth,
  stfSetKeyguard,
  stfSetMute,
  stfSetRinger,
  stfSetWakeLock,
  stfSetWifi,
  stfSetClipboard,
  stfStatus,
  type StfStatus,
} from '../services/api';

interface DeviceSTFPanelProps {
  serial: string;
  refreshInterval?: number;
}

function batterySourceLabel(source: number): string {
  switch (source) {
    case 1: return 'AC';
    case 2: return 'USB';
    case 4: return 'Wireless';
    default: return '?';
  }
}

function batteryHealthLabel(health: number): string {
  switch (health) {
    case 2: return 'Good';
    case 3: return 'Overheat';
    case 4: return 'Dead';
    case 5: return 'Overvoltage';
    case 6: return 'Unknown';
    case 7: return 'Cold';
    default: return '?';
  }
}

function connTypeLabel(type: number): string {
  switch (type) {
    case 0: return 'Mobile';
    case 1: return 'WiFi';
    case 6: return 'WiMAX';
    case 7: return 'Bluetooth';
    case 9: return 'Ethernet';
    default: return type >= 0 ? `Type ${type}` : 'None';
  }
}

function phoneStateLabel(state: number): string {
  switch (state) {
    case 0: return 'Idle';
    case 1: return 'Ringing';
    case 2: return 'Offhook';
    default: return '?';
  }
}

function rotationLabel(rot: number): string {
  switch (rot) {
    case 0: return '0° Portrait';
    case 1: return '90° Landscape';
    case 2: return '180° Portrait Rev.';
    case 3: return '270° Landscape Rev.';
    default: return `${rot}°`;
  }
}

type RingerMode = 'silent' | 'vibrate' | 'normal';

export function DeviceSTFPanel({ serial, refreshInterval = 5000 }: DeviceSTFPanelProps) {
  const t = useTranslations('deviceStf');
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState<StfStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [clipboardText, setClipboardText] = useState('');
  const [clipboardInput, setClipboardInput] = useState('');
  const [ringerMode, setRingerMode] = useState<RingerMode>('normal');
  const [busy, setBusy] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    if (!expanded) return;
    setLoading(true);
    const s = await stfStatus(serial);
    setLoading(false);
    if (s) setStatus(s);
  }, [serial, expanded]);

  useEffect(() => {
    if (!expanded) return;
    fetchStatus();
    if (refreshInterval > 0) {
      timerRef.current = setInterval(fetchStatus, refreshInterval);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [expanded, fetchStatus, refreshInterval]);

  // ── helpers ──────────────────────────────────────────────────────────────
  async function withBusy(key: string, fn: () => Promise<boolean>) {
    setBusy(key);
    const ok = await fn();
    setBusy(null);
    if (!ok) toast.error(t('actionFailed'));
    return ok;
  }

  const handleGetClipboard = async () => {
    setBusy('clipboard_get');
    const text = await stfGetClipboard(serial);
    setBusy(null);
    if (text !== null) {
      setClipboardText(text);
      setClipboardInput(text);
      toast.success(t('clipboardFetched'));
    } else {
      toast.error(t('actionFailed'));
    }
  };

  const handleSetClipboard = async () => {
    await withBusy('clipboard_set', () => stfSetClipboard(serial, clipboardInput));
    toast.success(t('clipboardWritten'));
  };

  const handleCopyToHost = () => {
    if (!clipboardText) return;
    navigator.clipboard.writeText(clipboardText).then(
      () => toast.success(t('copiedToHost')),
      () => toast.error(t('actionFailed')),
    );
  };

  const handleRinger = async (mode: RingerMode) => {
    const ok = await withBusy(`ringer_${mode}`, () => stfSetRinger(serial, mode));
    if (ok) setRingerMode(mode);
  };

  if (!expanded) {
    return (
      <button
        type='button'
        onClick={() => setExpanded(true)}
        className='mt-1.5 flex w-full items-center justify-center gap-1 rounded-md border border-dashed border-border/60 py-1.5 text-[10px] text-muted-foreground hover:border-border hover:bg-muted/30'
      >
        {/* <Signal className='size-3' />
        {t('showPanel')}
        <ChevronDown className='size-3' /> */}
      </button>
    );
  }

  const bat = status?.battery;
  const conn = status?.connectivity;

  return (
    <div className='mt-1.5 rounded-md border border-border/60 bg-muted/10 text-[11px]'>
      {/* Header */}
      <button
        type='button'
        onClick={() => setExpanded(false)}
        className='flex w-full items-center justify-between px-3 py-2 font-semibold text-muted-foreground hover:text-foreground'
      >
        <span className='flex items-center gap-1.5'>
          <Signal className='size-3' />
          {t('panelTitle')}
          {loading && <Loader2 className='size-3 animate-spin' />}
          {status && !status.connected && (
            <span className='rounded bg-yellow-500/20 px-1 py-px text-[9px] font-medium text-yellow-700 dark:text-yellow-400'>
              {t('stfNotConnected')}
            </span>
          )}
        </span>
        <ChevronUp className='size-3' />
      </button>

      {status?.connected === false ? (
        <div className='px-3 pb-3 text-xs text-muted-foreground'>
          {t('stfNotAvailable')}
        </div>
      ) : (
        <div className='space-y-3 px-3 pb-3'>
          {/* ── Battery ───────────────────────────────────────────── */}
          {bat && (
            <section>
              <p className='mb-1 flex items-center gap-1 font-semibold text-foreground/80'>
                {bat.status === 2 ? (
                  <BatteryCharging className='size-3 text-green-500' />
                ) : (
                  <Battery className='size-3' />
                )}
                {t('battery')}
              </p>
              <div className='grid grid-cols-2 gap-x-3 gap-y-0.5 text-muted-foreground'>
                <span>{t('batteryLevel')}: <strong className='text-foreground'>{bat.level}%</strong></span>
                <span>{t('batterySource')}: <strong className='text-foreground'>{batterySourceLabel(bat.source)}</strong></span>
                <span>{t('batteryHealth')}: <strong className='text-foreground'>{batteryHealthLabel(bat.health)}</strong></span>
                <span>{t('batteryTemp')}: <strong className='text-foreground'>{(bat.temp / 10).toFixed(1)}°C</strong></span>
                <span>{t('batteryVoltage')}: <strong className='text-foreground'>{(bat.voltage / 1000).toFixed(2)}V</strong></span>
              </div>
            </section>
          )}

          {/* ── Rotation & connectivity ────────────────────────── */}
          {status && (
            <section className='grid grid-cols-2 gap-x-3 gap-y-0.5 text-muted-foreground'>
              <span className='flex items-center gap-1'>
                <RotateCw className='size-3' />
                {t('rotation')}: <strong className='text-foreground ml-0.5'>{rotationLabel(status.rotation)}</strong>
              </span>
              <span className='flex items-center gap-1'>
                {status.airplane_mode ? (
                  <SignalZero className='size-3 text-orange-500' />
                ) : (
                  <Signal className='size-3 text-green-500' />
                )}
                {status.airplane_mode ? t('airplaneOn') : t('airplaneOff')}
              </span>
              {conn && (
                <>
                  <span className='flex items-center gap-1'>
                    <Signal className='size-3' />
                    {t('network')}: <strong className='text-foreground ml-0.5'>
                      {conn.connected ? connTypeLabel(conn.type) : t('noNetwork')}
                    </strong>
                    {conn.roaming && <span className='ml-1 text-orange-500'>(R)</span>}
                  </span>
                  <span>
                    {t('phone')}: <strong className='text-foreground'>
                      {phoneStateLabel(status.phone_state.state)}
                    </strong>
                    {status.phone_state.operator ? ` · ${status.phone_state.operator}` : ''}
                  </span>
                </>
              )}
            </section>
          )}

          {/* ── Clipboard ─────────────────────────────────────── */}
          <section>
            <p className='mb-1 flex items-center gap-1 font-semibold text-foreground/80'>
              <Clipboard className='size-3' />
              {t('clipboard')}
            </p>
            <div className='flex gap-1'>
              <Input
                className='h-7 flex-1 text-[11px] font-mono'
                placeholder={t('clipboardPlaceholder')}
                value={clipboardInput}
                onChange={(e) => setClipboardInput(e.target.value)}
              />
              <Button
                size='sm'
                variant='outline'
                className='h-7 px-2 text-[10px]'
                onClick={handleGetClipboard}
                disabled={busy === 'clipboard_get'}
                title={t('clipboardGet')}
              >
                {busy === 'clipboard_get' ? <Loader2 className='size-3 animate-spin' /> : <Clipboard className='size-3' />}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 px-2 text-[10px]'
                onClick={handleSetClipboard}
                disabled={busy === 'clipboard_set' || !clipboardInput}
                title={t('clipboardSet')}
              >
                {busy === 'clipboard_set' ? <Loader2 className='size-3 animate-spin' /> : <ClipboardCopy className='size-3' />}
              </Button>
              {clipboardText && (
                <Button
                  size='sm'
                  variant='ghost'
                  className='h-7 px-2 text-[10px]'
                  onClick={handleCopyToHost}
                  title={t('copyToHost')}
                >
                  <ClipboardCopy className='size-3' />
                </Button>
              )}
            </div>
          </section>

          {/* ── Toggle controls ──────────────────────────────────── */}
          <section>
            <p className='mb-1 font-semibold text-foreground/80'>{t('controls')}</p>
            <div className='flex flex-wrap gap-1.5'>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('wifi_on', () => stfSetWifi(serial, true))}
                disabled={!!busy}
              >
                {busy === 'wifi_on' ? <Loader2 className='size-3 animate-spin' /> : <Wifi className='size-3' />}
                {t('wifiOn')}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('wifi_off', () => stfSetWifi(serial, false))}
                disabled={!!busy}
              >
                {busy === 'wifi_off' ? <Loader2 className='size-3 animate-spin' /> : <WifiOff className='size-3' />}
                {t('wifiOff')}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('bt_on', () => stfSetBluetooth(serial, true))}
                disabled={!!busy}
              >
                {busy === 'bt_on' ? <Loader2 className='size-3 animate-spin' /> : <Bluetooth className='size-3' />}
                {t('btOn')}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('bt_off', () => stfSetBluetooth(serial, false))}
                disabled={!!busy}
              >
                {busy === 'bt_off' ? <Loader2 className='size-3 animate-spin' /> : <BluetoothOff className='size-3' />}
                {t('btOff')}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('keyguard_on', () => stfSetKeyguard(serial, true))}
                disabled={!!busy}
              >
                {busy === 'keyguard_on' ? <Loader2 className='size-3 animate-spin' /> : <Lock className='size-3' />}
                {t('lock')}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('keyguard_off', () => stfSetKeyguard(serial, false))}
                disabled={!!busy}
              >
                {busy === 'keyguard_off' ? <Loader2 className='size-3 animate-spin' /> : <LockOpen className='size-3' />}
                {t('unlock')}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('mute_on', () => stfSetMute(serial, true))}
                disabled={!!busy}
              >
                {busy === 'mute_on' ? <Loader2 className='size-3 animate-spin' /> : <VolumeX className='size-3' />}
                {t('mute')}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('mute_off', () => stfSetMute(serial, false))}
                disabled={!!busy}
              >
                {busy === 'mute_off' ? <Loader2 className='size-3 animate-spin' /> : <Volume2 className='size-3' />}
                {t('unmute')}
              </Button>
              <Button
                size='sm'
                variant='outline'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('wakelock_on', () => stfSetWakeLock(serial, true))}
                disabled={!!busy}
              >
                {busy === 'wakelock_on' ? <Loader2 className='size-3 animate-spin' /> : null}
                {t('wakelockOn')}
              </Button>
              <Button
                size='sm'
                variant='secondary'
                className='h-7 gap-1 px-2 text-[10px]'
                onClick={() => withBusy('identify', () => stfIdentify(serial))}
                disabled={!!busy}
              >
                {busy === 'identify' ? <Loader2 className='size-3 animate-spin' /> : <Scan className='size-3' />}
                {t('identify')}
              </Button>
            </div>
          </section>

          {/* ── Ringer mode ──────────────────────────────────────── */}
          <section>
            <p className='mb-1 font-semibold text-foreground/80'>{t('ringerMode')}</p>
            <div className='flex gap-1.5'>
              {(['silent', 'vibrate', 'normal'] as RingerMode[]).map((m) => (
                <Button
                  key={m}
                  size='sm'
                  variant={ringerMode === m ? 'default' : 'outline'}
                  className='h-7 flex-1 px-2 text-[10px]'
                  onClick={() => handleRinger(m)}
                  disabled={!!busy}
                >
                  {busy === `ringer_${m}` ? (
                    <Loader2 className='size-3 animate-spin' />
                  ) : (
                    t(`ringer_${m}` as 'ringer_silent' | 'ringer_vibrate' | 'ringer_normal')
                  )}
                </Button>
              ))}
            </div>
          </section>

          {/* ── Refresh button ───────────────────────────────────── */}
          <Button
            size='sm'
            variant='ghost'
            className='h-7 w-full gap-1.5 text-[10px] text-muted-foreground'
            onClick={fetchStatus}
            disabled={loading}
          >
            {loading ? <Loader2 className='size-3 animate-spin' /> : <RotateCw className='size-3' />}
            {t('refreshStatus')}
          </Button>
        </div>
      )}
    </div>
  );
}
