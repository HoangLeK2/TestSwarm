'use client';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useCreateCampaign } from '../hooks/use-campaigns';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger
} from '@/components/ui/dialog';
import { useState } from 'react';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';

type FormData = {
  name: string;
  description?: string;
};

export function CreateCampaignDialog() {
  const t = useTranslations('campaignsFeature.createDialog');
  const schema = z.object({
    name: z.string().min(1, t('nameRequired')),
    description: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useCreateCampaign();
  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema)
  });

  const onSubmit = (data: FormData) => {
    mutate(data, {
      onSuccess: () => { reset(); setOpen(false); }
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen} >
      <DialogTrigger asChild>
        <Button size='sm'><Plus size={16} className='mr-1' />{t('trigger')}</Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4 pt-2'>
          <div className='space-y-1'>
            <Label>{t('nameLabel')}</Label>
            <Input placeholder={t('namePlaceholder')} {...register('name')} />
            {errors.name && <p className='text-xs text-destructive'>{errors.name.message}</p>}
          </div>
          <div className='space-y-1'>
            <Label>{t('descriptionLabel')}</Label>
            <Textarea placeholder={t('descriptionPlaceholder')} {...register('description')} />
          </div>
          {error && (
            <p className='text-xs text-destructive'>
              {(error as any)?.response?.data?.detail ?? t('createFailed')}
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
