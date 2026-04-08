'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useCreateAccount } from '../hooks/use-accounts';
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
  platform: string;
  username: string;
  password?: string;
  display_name?: string;
  tags?: string;
  notes?: string;
};

export function CreateAccountDialog() {
  const t = useTranslations('accountsFeature.createDialog');
  const schema = z.object({
    platform: z.string().min(1, t('platformRequired')),
    username: z.string().min(1, t('usernameRequired')),
    password: z.string().optional(),
    display_name: z.string().optional(),
    tags: z.string().optional(),
    notes: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useCreateAccount();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = (data: FormData) => {
    mutate(data, {
      onSuccess: () => {
        reset();
        setOpen(false);
      }
    });
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
          <div className='grid grid-cols-2 gap-4'>
            <div className='space-y-1'>
              <Label>{t('platformLabel')}</Label>
              <Input placeholder='facebook' {...register('platform')} />
              {errors.platform && (
                <p className='text-xs text-destructive'>
                  {errors.platform.message}
                </p>
              )}
            </div>
            <div className='space-y-1'>
              <Label>{t('usernameLabel')}</Label>
              <Input placeholder={t('usernamePlaceholder')} {...register('username')} />
              {errors.username && (
                <p className='text-xs text-destructive'>
                  {errors.username.message}
                </p>
              )}
            </div>
          </div>
          <div className='grid grid-cols-2 gap-4'>
            <div className='space-y-1'>
              <Label>{t('passwordLabel')}</Label>
              <Input
                type='password'
                placeholder='********'
                {...register('password')}
              />
            </div>
            <div className='space-y-1'>
              <Label>{t('displayNameLabel')}</Label>
              <Input
                placeholder={t('displayNamePlaceholder')}
                {...register('display_name')}
              />
            </div>
          </div>
          <div className='space-y-1'>
            <Label>{t('tagsLabel')}</Label>
            <Input placeholder={t('tagsPlaceholder')} {...register('tags')} />
          </div>
          <div className='space-y-1'>
            <Label>{t('notesLabel')}</Label>
            <Textarea placeholder={t('notesPlaceholder')} {...register('notes')} />
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
