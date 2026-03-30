'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Pencil } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useUpdateAccount } from '../hooks/use-accounts';
import type { AccountOut } from '../services/api';
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
  password?: string;
  display_name?: string;
  tags?: string;
  notes?: string;
};

export function EditAccountDialog({ account }: { account: AccountOut }) {
  const t = useTranslations('accountsFeature.editDialog');
  const schema = z.object({
    password: z.string().optional(),
    display_name: z.string().optional(),
    tags: z.string().optional(),
    notes: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useUpdateAccount();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      display_name: account.display_name,
      tags: account.tags,
      notes: account.notes
    }
  });

  useEffect(() => {
    if (open) {
      reset({
        password: '',
        display_name: account.display_name,
        tags: account.tags,
        notes: account.notes
      });
    }
  }, [open, account, reset]);

  const onSubmit = (data: FormData) => {
    const payload: Record<string, any> = {};
    if (data.password) payload.password = data.password;
    if (data.display_name !== undefined) payload.display_name = data.display_name;
    if (data.tags !== undefined) payload.tags = data.tags;
    if (data.notes !== undefined) payload.notes = data.notes;
    mutate(
      { accountId: account.id, data: payload },
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
          <DialogTitle>
            {t('title')} — {account.username}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4 pt-2'>
          <div className='grid grid-cols-2 gap-4'>
            <div className='space-y-1'>
              <Label>{t('passwordLabel')}</Label>
              <Input type='password' placeholder={t('passwordPlaceholder')} {...register('password')} />
            </div>
            <div className='space-y-1'>
              <Label>{t('displayNameLabel')}</Label>
              <Input {...register('display_name')} />
            </div>
          </div>
          <div className='space-y-1'>
            <Label>{t('tagsLabel')}</Label>
            <Input {...register('tags')} />
          </div>
          <div className='space-y-1'>
            <Label>{t('notesLabel')}</Label>
            <Textarea {...register('notes')} />
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
