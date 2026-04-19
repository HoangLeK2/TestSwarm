'use client';

import { useState } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useCreateDeviceGroup } from '../hooks/use-device-groups';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { HexColorPopover, sanitizeHex } from '@/components/ui/hex-color-popover';
import { DeviceGroupFormPreview } from './device-group-form-preview';

type FormData = {
  name: string;
  description?: string;
  color?: string;
};

export function CreateDeviceGroupDialog() {
  const t = useTranslations('deviceGroupsFeature.createDialog');
  const tForm = useTranslations('deviceGroupsFeature.groupForm');
  const tList = useTranslations('deviceGroupsFeature.list');
  const schema = z.object({
    name: z.string().min(1, t('nameRequired')),
    description: z.string().optional(),
    color: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useCreateDeviceGroup();
  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', description: '', color: '#6366f1' }
  });

  const name = useWatch({ control, name: 'name', defaultValue: '' });
  const description = useWatch({ control, name: 'description', defaultValue: '' });
  const color = useWatch({ control, name: 'color', defaultValue: '#6366f1' });

  const onSubmit = (data: FormData) => {
    mutate(
      {
        name: data.name,
        description: data.description,
        color: sanitizeHex(data.color || '#6366f1')
      },
      { onSuccess: () => { reset(); setOpen(false); } }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm' className='cursor-pointer'>
          <Plus size={16} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='max-w-lg gap-0 overflow-hidden p-0 sm:max-w-xl'>
        <DialogHeader className='space-y-2 px-6 pb-2 pt-6 text-left'>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription>{t('dialogDescription')}</DialogDescription>
        </DialogHeader>

        <div className='grid max-h-[min(85vh,720px)] auto-rows-min gap-6 overflow-y-auto px-6 pb-6 sm:grid-cols-[minmax(0,1fr)_min(240px,40%)] sm:items-start'>
          <form
            onSubmit={handleSubmit(onSubmit)}
            className='flex min-w-0 flex-col gap-4'
            id='device-group-create-form'
          >
            <div className='space-y-1.5'>
              <Label htmlFor='device-group-create-name'>{t('nameLabel')}</Label>
              <Input
                id='device-group-create-name'
                autoComplete='off'
                placeholder={t('namePlaceholder')}
                className='transition-colors duration-200'
                {...register('name')}
              />
              <p className='text-[11px] leading-snug text-muted-foreground'>{tForm('nameHint')}</p>
              {errors.name && (
                <p className='text-xs text-destructive'>{errors.name.message}</p>
              )}
            </div>

            <div className='space-y-1.5'>
              <Label htmlFor='device-group-create-description'>{t('descriptionLabel')}</Label>
              <Textarea
                id='device-group-create-description'
                placeholder={t('descriptionPlaceholder')}
                rows={3}
                className='min-h-[80px] resize-y transition-colors duration-200'
                {...register('description')}
              />
              <p className='text-[11px] leading-snug text-muted-foreground'>{tForm('descriptionHint')}</p>
            </div>

            <div className='space-y-1.5'>
              <Label htmlFor='device-group-create-color-trigger'>{t('colorLabel')}</Label>
              <Controller
                name='color'
                control={control}
                render={({ field }) => (
                  <HexColorPopover
                    value={field.value || '#6366f1'}
                    onChange={field.onChange}
                    aria-label={t('colorLabel')}
                    className='cursor-pointer'
                  />
                )}
              />
              <p className='text-[11px] leading-snug text-muted-foreground'>{tForm('colorHint')}</p>
            </div>

            {error && (
              <p className='text-xs text-destructive'>
                {formatFarmApiError(error, t('createFailed'))}
              </p>
            )}

            <Button type='submit' className='w-full cursor-pointer' disabled={isPending}>
              {isPending ? t('creating') : t('submit')}
            </Button>
          </form>

          <aside className='sm:sticky sm:top-0 sm:self-start'>
            <DeviceGroupFormPreview
              name={name}
              description={description}
              color={color || '#6366f1'}
              deviceCount={0}
              title={tForm('previewTitle')}
              caption={tForm('previewCaption')}
              emptyNameLabel={tForm('previewNameEmpty')}
              dashLabel={tForm('previewDash')}
              devicesLabel={tList('colDeviceCount')}
            />
          </aside>
        </div>
      </DialogContent>
    </Dialog>
  );
}
