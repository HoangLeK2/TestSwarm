'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
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
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

type FormData = {
  name: string;
  description?: string;
  color?: string;
};

export function CreateDeviceGroupDialog() {
  const t = useTranslations('deviceGroupsFeature.createDialog');
  const schema = z.object({
    name: z.string().min(1, t('nameRequired')),
    description: z.string().optional(),
    color: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useCreateDeviceGroup();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = (data: FormData) => {
    mutate(
      { name: data.name, description: data.description, color: data.color || '#6366f1' },
      { onSuccess: () => { reset(); setOpen(false); } }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus size={16} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4 pt-2'>
          <div className='space-y-1'>
            <Label>{t('nameLabel')}</Label>
            <Input placeholder={t('namePlaceholder')} {...register('name')} />
            {errors.name && (
              <p className='text-xs text-destructive'>{errors.name.message}</p>
            )}
          </div>
          <div className='space-y-1'>
            <Label>{t('descriptionLabel')}</Label>
            <Textarea
              placeholder={t('descriptionPlaceholder')}
              {...register('description')}
            />
          </div>
          <div className='space-y-1'>
            <Label>{t('colorLabel')}</Label>
            <Input type='color' defaultValue='#6366f1' {...register('color')} className='h-10 w-20' />
          </div>
          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('createFailed'))}
            </p>
          )}
          <Button type='submit' className='w-full' disabled={isPending}>
            {isPending ? t('creating') : t('submit')}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
