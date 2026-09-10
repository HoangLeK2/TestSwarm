'use client';

import { useId, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { usePermission } from '@/features/auth/hooks/use-permission';
import { useUpdateDeviceName, useUpdateDeviceTags } from '../hooks/use-devices';
import {
  deviceDisplayName,
  devicePrimarySerial,
  type DeviceDisplayLike
} from '../lib/device-display-name';
import { useTranslations } from 'next-intl';

export type EditableDeviceDisplay = DeviceDisplayLike & {
  id?: string | null;
  /** Omit entirely where tags are not loaded — the field is then not offered,
   *  so a caller that cannot see the current tags can never blank them. */
  tags?: string | null;
};

/** Device update popup. Renders nothing without `devices:update` or an id. */
export function DeviceUpdateDialog({
  device,
  trigger,
  onSaved
}: {
  device: EditableDeviceDisplay;
  trigger: ReactNode;
  onSaved?: () => void;
}) {
  const t = useTranslations('devicesFarm.deviceName');
  const canUpdate = usePermission('devices', 'update');
  const updateName = useUpdateDeviceName();
  const updateTags = useUpdateDeviceTags();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(device.name ?? '');
  const [tags, setTags] = useState(device.tags ?? '');
  const inputId = useId();
  const tagsId = useId();
  const editsTags = device.tags !== undefined;

  if (!canUpdate || !device.id) return null;

  const save = async () => {
    if (!device.id) return;
    try {
      if (value.trim() !== (device.name ?? '').trim()) {
        await updateName.mutateAsync({
          deviceId: device.id,
          name: value.trim()
        });
      }
      if (editsTags && tags.trim() !== (device.tags ?? '').trim()) {
        await updateTags.mutateAsync({
          deviceId: device.id,
          tags: tags.trim()
        });
      }
      toast.success(t('saved'));
      setOpen(false);
      onSaved?.();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('saveFailed'));
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Re-seed from the row on every open: the fleet grid re-polls every few
        // seconds, so a stale draft would silently overwrite a rename made
        // elsewhere.
        if (next) {
          setValue(device.name ?? '');
          setTags(device.tags ?? '');
        }
        setOpen(next);
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader className='text-left'>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription className='font-mono'>
            {devicePrimarySerial(device) || deviceDisplayName(device)}
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
          className='space-y-4'
        >
          <div className='space-y-1.5'>
            <Label htmlFor={inputId}>{t('label')}</Label>
            <Input
              id={inputId}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              maxLength={255}
              autoFocus
              placeholder={t('placeholder')}
            />
          </div>
          {editsTags ? (
            <div className='space-y-1.5'>
              <Label htmlFor={tagsId}>{t('tagsLabel')}</Label>
              <Input
                id={tagsId}
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                maxLength={255}
                placeholder={t('tagsPlaceholder')}
              />
            </div>
          ) : null}
          <DialogFooter>
            <Button
              type='button'
              variant='outline'
              onClick={() => setOpen(false)}
            >
              {t('cancel')}
            </Button>
            <Button
              type='submit'
              disabled={updateName.isPending || updateTags.isPending}
            >
              {t('save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
