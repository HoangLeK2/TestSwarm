'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Loader2, Play, Smartphone } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { accountsApi } from '@/features/accounts/services/api';
import {
  devicesApi,
  type DeviceOut
} from '@/features/devices/services/manage-api';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useStartOrgScenarioPreview } from '../hooks/use-org-scenarios';
import type { PreviewStartResponse } from '../services/api';

const BACKEND_SIDE_EFFECT_WARNING =
  'Step social-effect detected; consider test account';

const PREVIEW_ERROR_CODES = [
  'PREVIEW_HAS_SIDE_EFFECT_REQUIRES_FORCE',
  'ACCOUNT_REQUIRED_FOR_PREVIEW',
  'DEVICE_BUSY',
  'DEVICE_OFFLINE',
  'DEVICE_NOT_FOUND',
  'PREVIEW_RUNTIME_START_FAILED'
] as const;

type PreviewErrorCode = (typeof PREVIEW_ERROR_CODES)[number];

function isPreviewErrorCode(code: string): code is PreviewErrorCode {
  return (PREVIEW_ERROR_CODES as readonly string[]).includes(code);
}

function deviceLabel(device: DeviceOut) {
  const name = device.name?.trim() || device.serial;
  return `${name} · ${device.state}`;
}

function isOnlineDevice(device: DeviceOut) {
  return String(device.state ?? '').toLowerCase() === 'online';
}

export function RunPreviewDialog({
  open,
  onOpenChange,
  scenarioId,
  scenarioName,
  disabled
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scenarioId: string;
  scenarioName?: string;
  disabled?: boolean;
}) {
  const t = useTranslations('orgScenariosFeature.previewDialog');
  const previewMutation = useStartOrgScenarioPreview();

  const localizeWarning = (warning: string) => {
    if (warning === BACKEND_SIDE_EFFECT_WARNING) {
      return t('sideEffectWarning');
    }
    return warning;
  };

  const previewErrorMessage = (error: unknown) => {
    const err = error as {
      response?: { data?: { detail?: { code?: string; message?: string } } };
    };
    const detail = err.response?.data?.detail;
    const code = detail?.code;
    if (code && isPreviewErrorCode(code)) {
      return t(`errors.${code}`);
    }
    if (typeof detail === 'object' && detail && typeof detail.message === 'string') {
      return detail.message;
    }
    return formatFarmApiError(error, t('startFailed'));
  };

  const [deviceId, setDeviceId] = useState('');
  const [accountId, setAccountId] = useState('');
  const [forceSideEffects, setForceSideEffects] = useState(false);
  const [needsForceAck, setNeedsForceAck] = useState(false);
  const [result, setResult] = useState<PreviewStartResponse | null>(null);

  const { data: devices = [], isLoading: loadingDevices } = useQuery({
    queryKey: ['devices'],
    queryFn: () => devicesApi.list(),
    enabled: open
  });

  const { data: accounts = [], isLoading: loadingAccounts } = useQuery({
    queryKey: ['accounts', 'preview-picker'],
    queryFn: () => accountsApi.list({ state: 'active' }),
    enabled: open
  });

  const onlineDevices = useMemo(
    () => devices.filter(isOnlineDevice),
    [devices]
  );

  useEffect(() => {
    if (!open) return;
    setDeviceId('');
    setAccountId('');
    setForceSideEffects(false);
    setNeedsForceAck(false);
    setResult(null);
  }, [open, scenarioId]);

  useEffect(() => {
    if (!open || deviceId) return;
    if (onlineDevices[0]?.id) setDeviceId(onlineDevices[0].id);
  }, [open, deviceId, onlineDevices]);

  const handleSubmit = () => {
    if (!deviceId) {
      toast.error(t('deviceRequired'));
      return;
    }

    previewMutation.mutate(
      {
        scenarioId,
        body: {
          device_id: deviceId,
          account_id: accountId || null,
          force: forceSideEffects,
          vars: {}
        }
      },
      {
        onSuccess: (data) => {
          setResult(data);
          if (data.warnings?.length) {
            data.warnings.forEach((warning) =>
              toast.warning(localizeWarning(warning))
            );
          }
          toast.success(t('started', { id: data.execution_id.slice(0, 8) }));
        },
        onError: (error) => {
          const err = error as {
            response?: { data?: { detail?: { code?: string } } };
          };
          const code = err.response?.data?.detail?.code;
          if (code === 'PREVIEW_HAS_SIDE_EFFECT_REQUIRES_FORCE') {
            setNeedsForceAck(true);
          }
          toast.error(previewErrorMessage(error));
        }
      }
    );
  };

  const handleClose = () => onOpenChange(false);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>

        {result ? (
          <div className='space-y-4'>
            <Alert>
              <Play className='h-4 w-4' />
              <AlertTitle>{t('successTitle')}</AlertTitle>
              <AlertDescription className='space-y-1 pt-1 text-sm'>
                <p>{t('executionId', { id: result.execution_id })}</p>
                <p>{t('statusLabel', { status: result.status })}</p>
                {result.workflow_id ? (
                  <p>{t('workflowId', { id: result.workflow_id })}</p>
                ) : null}
              </AlertDescription>
            </Alert>
            {result.warnings?.length ? (
              <ul className='space-y-1 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-900 dark:text-amber-100'>
                {result.warnings.map((warning) => (
                  <li key={warning}>{localizeWarning(warning)}</li>
                ))}
              </ul>
            ) : null}
            <DialogFooter>
              <Button onClick={handleClose}>{t('close')}</Button>
            </DialogFooter>
          </div>
        ) : (
          <>
            <Alert variant='destructive' className='border-amber-500/40 bg-amber-500/10 text-amber-950 dark:text-amber-50'>
              <AlertTriangle className='h-4 w-4 text-amber-600' />
              <AlertTitle>{t('realDeviceTitle')}</AlertTitle>
              <AlertDescription>{t('realDeviceHint')}</AlertDescription>
            </Alert>

            {scenarioName ? (
              <p className='text-sm text-muted-foreground'>
                {t('scenarioLabel', { name: scenarioName })}
              </p>
            ) : null}

            <div className='space-y-4'>
              <div className='space-y-1.5'>
                <Label>{t('deviceLabel')}</Label>
                <Select
                  value={deviceId}
                  onValueChange={setDeviceId}
                  disabled={loadingDevices || !onlineDevices.length}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('devicePlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    {onlineDevices.map((device) => (
                      <SelectItem key={device.id} value={device.id}>
                        <span className='inline-flex items-center gap-2'>
                          <Smartphone className='h-3.5 w-3.5 opacity-60' />
                          {deviceLabel(device)}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {!loadingDevices && !onlineDevices.length ? (
                  <p className='text-xs text-muted-foreground'>{t('noOnlineDevices')}</p>
                ) : null}
              </div>

              <div className='space-y-1.5'>
                <Label>{t('accountLabel')}</Label>
                <Select
                  value={accountId || '__none__'}
                  onValueChange={(value) =>
                    setAccountId(value === '__none__' ? '' : value)
                  }
                  disabled={loadingAccounts}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('accountPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='__none__'>{t('accountNone')}</SelectItem>
                    {accounts.map((account) => (
                      <SelectItem key={account.id} value={account.id}>
                        {account.username} ({account.platform})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className='text-xs text-muted-foreground'>{t('accountHint')}</p>
              </div>

              {(needsForceAck || forceSideEffects) && (
                <div className='flex items-start gap-2 rounded-md border p-3'>
                  <Checkbox
                    id='preview-force'
                    checked={forceSideEffects}
                    onCheckedChange={(checked) =>
                      setForceSideEffects(checked === true)
                    }
                  />
                  <div className='space-y-1'>
                    <Label htmlFor='preview-force' className='cursor-pointer'>
                      {t('forceLabel')}
                    </Label>
                    <p className='text-xs text-muted-foreground'>{t('forceHint')}</p>
                  </div>
                </div>
              )}
            </div>

            <DialogFooter className='gap-2 sm:gap-0'>
              <Button variant='outline' onClick={handleClose}>
                {t('cancel')}
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={
                  disabled ||
                  previewMutation.isPending ||
                  !deviceId ||
                  !onlineDevices.length
                }
              >
                {previewMutation.isPending ? (
                  <>
                    <Loader2 className='mr-2 h-4 w-4 animate-spin' />
                    {t('starting')}
                  </>
                ) : (
                  <>
                    <Play className='mr-2 h-4 w-4' />
                    {t('submit')}
                  </>
                )}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
