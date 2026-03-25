'use client';

import { Play, Pause, CheckCircle, Trash2, Zap, Eye } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
import { useCampaignDevices, useDeleteCampaign, useFleetRunCampaign, useRunCampaign, useUpdateCampaignStatus } from '../../hooks/use-campaigns';
import type { CampaignOut } from '../../types';
import { CampaignRunProgress } from './CampaignRunProgress';

export function CampaignActions({ campaign }: { campaign: CampaignOut }) {
  const t = useTranslations('campaignsFeature.list');
  const { mutate: updateStatus, isPending } = useUpdateCampaignStatus();
  const { mutate: runCampaign, isPending: isRunning } = useRunCampaign(() => {
    toast.success(t('campaignDone'));
  });
  const { mutate: fleetRun, isPending: isFleetRunning } = useFleetRunCampaign((result) => {
    toast.success(t('fleetDone', { done: result.done, total: result.total }));
  });
  const { mutate: deleteCampaign, isPending: isDeleting } = useDeleteCampaign();
  const { data: devices = [] } = useCampaignDevices(campaign.id);

  const deviceCount = devices.length;
  const previewSerial = devices[0]?.serial ?? '';

  const hasScenario =
    (Array.isArray(campaign.scenarios) && campaign.scenarios.some((s) => s.steps?.length > 0)) ||
    (Array.isArray(campaign.scenario?.steps) && (campaign.scenario?.steps?.length ?? 0) > 0);

  const handleDelete = () => {
    if (!window.confirm(t('deleteConfirm'))) return;
    deleteCampaign(campaign.id, {
      onSuccess: () => toast.success(t('deleteSuccess')),
      onError: () => toast.error(t('deleteFailed'))
    });
  };

  const handleFleetRun = () => {
    if (!hasScenario) {
      toast.error(t('missingScenario'));
      return;
    }

    fleetRun(campaign, {
      onError: (err: unknown) => {
        const msg = err instanceof Error ? err.message : t('fleetFailed');
        toast.error(msg);
      }
    });
  };

  return (
    <div className='flex flex-col gap-1'>
      <div className='flex gap-1'>
        {campaign.status === 'draft' && (
          <Button
            size='icon'
            variant='ghost'
            className='size-7'
            disabled={isPending || isRunning}
            onClick={() =>
              runCampaign(campaign.id, {
                onError: (err: unknown) => {
                  const msg =
                    err && typeof err === 'object' && 'response' in err
                      ? (err as { response?: { data?: { error?: string } } }).response?.data?.error
                      : null;
                  toast.error(msg ?? t('runFailed'));
                }
              })
            }
            title={deviceCount === 0 ? t('titleNeedDevice') : t('titleRun')}
          >
            <Play size={12} />
          </Button>
        )}

        {campaign.status === 'running' && (
          <>
            <Button
              size='icon'
              variant='ghost'
              className='size-7'
              disabled={isPending}
              onClick={() =>
                updateStatus(
                  { id: campaign.id, status: 'paused' },
                  { onSuccess: () => toast.success(t('paused')) }
                )
              }
              title={t('titlePause')}
            >
              <Pause size={12} />
            </Button>

            <Button
              size='icon'
              variant='ghost'
              className='size-7'
              disabled={isPending}
              onClick={() =>
                updateStatus(
                  { id: campaign.id, status: 'completed' },
                  { onSuccess: () => toast.success(t('markedDone')) }
                )
              }
              title={t('titleComplete')}
            >
              <CheckCircle size={12} />
            </Button>
          </>
        )}

        {campaign.status === 'paused' && (
          <Button
            size='icon'
            variant='ghost'
            className='size-7'
            disabled={isPending || isRunning}
            onClick={() =>
              runCampaign(campaign.id, {
                onError: (err: unknown) => {
                  const msg =
                    err && typeof err === 'object' && 'response' in err
                      ? (err as { response?: { data?: { error?: string } } }).response?.data?.error
                      : null;
                  toast.error(msg ?? t('runFailed'));
                }
              })
            }
            title={deviceCount === 0 ? t('titleNeedDevice') : t('titleResume')}
          >
            <Play size={12} />
          </Button>
        )}

        {hasScenario && campaign.status !== 'running' && (
          <Button
            size='icon'
            variant='ghost'
            className='size-7 text-amber-500 hover:text-amber-500'
            disabled={isFleetRunning || isRunning}
            onClick={handleFleetRun}
            title={t('titleFleet')}
          >
            <Zap size={12} />
          </Button>
        )}

        <Button
          size='icon'
          variant='ghost'
          className='size-7 text-destructive hover:text-destructive'
          disabled={isDeleting}
          onClick={handleDelete}
          title={t('titleDelete')}
        >
          <Trash2 size={12} />
        </Button>
      </div>

      <CampaignRunProgress campaignId={campaign.id} isRunning={campaign.status === 'running'} />

      {campaign.status === 'running' && previewSerial && (
        <Dialog>
          <DialogTrigger asChild>
            <Button
              size='sm'
              variant='outline'
              className='h-7 gap-1 text-[11px]'
              title={t('titleLivePreview')}
            >
              <Eye size={12} />
              Live
            </Button>
          </DialogTrigger>
          <DialogContent className='max-w-[420px]'>
            <DialogHeader>
              <DialogTitle className='text-sm'>{t('liveDialogTitle')}</DialogTitle>
            </DialogHeader>
            <DeviceControlEmbed initialSerial={previewSerial} compact />
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

