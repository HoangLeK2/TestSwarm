'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Pencil } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useUpdateDeviceGroup } from '../hooks/use-device-groups';
import type { DeviceGroupOut } from '../services/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

type FormData = { name: string; description?: string; color?: string };

export function EditDeviceGroupDialog({ group }: { group: DeviceGroupOut }) {
  const t = useTranslations('deviceGroupsFeature.editDialog');
  const schema = z.object({
    name: z.string().min(1, t('nameRequired')),
    description: z.string().optional(),
    color: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useUpdateDeviceGroup();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: group.name,
      description: group.description,
      color: group.color
    }
  });

  useEffect(() => {
    if (open) reset({ name: group.name, description: group.description, color: group.color });
  }, [open, group, reset]);

  const onSubmit = (data: FormData) => {
    mutate(
      { groupId: group.id, data: { name: data.name, description: data.description, color: data.color } },
      { onSuccess: () => setOpen(false) }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='icon' variant='ghost' className='size-8'>
          <Pencil size={14} />
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4 pt-2'>
          <div className='space-y-1'>
            <Label>{t('nameLabel')}</Label>
            <Input {...register('name')} />
            {errors.name && <p className='text-xs text-destructive'>{errors.name.message}</p>}
          </div>
          <div className='space-y-1'>
            <Label>{t('descriptionLabel')}</Label>
            <Textarea {...register('description')} />
          </div>
          <div className='space-y-1'>
            <Label>{t('colorLabel')}</Label>
            <Input type='color' {...register('color')} className='h-10 w-20' />
          </div>
          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('updateFailed'))}
            </p>
          )}
          <Button type='submit' className='w-full' disabled={isPending}>
            {isPending ? t('updating') : t('submit')}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
