'use client';

import { useEffect, useState, type ReactNode } from 'react';
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

function editableAccountValues(account: AccountOut): FormData {
  return {
    password: '',
    display_name: account.display_name || account.observed_display_name || '',
    tags: account.tags || '',
    notes: account.notes || ''
  };
}

function accountStateLabel(account: AccountOut, t: (key: string) => string) {
  const normalized = (account.state || account.status || '').toLowerCase();
  if (normalized === 'unassigned') return t('stateUnassigned');
  if (normalized === 'assigned') return t('stateAssigned');
  if (normalized === 'active') return t('stateActive');
  if (normalized === 'suspended') return t('stateSuspended');
  if (normalized === 'banned') return t('stateBanned');
  if (normalized === 'retired') return t('stateRetired');
  return account.state || account.status || '-';
}

function hasChanged(
  key: keyof Pick<FormData, 'display_name' | 'tags' | 'notes'>,
  account: AccountOut,
  value: string | undefined
) {
  const next = value ?? '';
  if (key === 'display_name' && !account.display_name) {
    return next !== (account.observed_display_name || '');
  }
  return next !== (account[key] || '');
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className='min-w-0'>
      <dt className='text-xs text-muted-foreground'>{label}</dt>
      <dd className='truncate text-sm font-medium text-foreground'>{value}</dd>
    </div>
  );
}

export function EditAccountDialog({
  account,
  trigger
}: {
  account: AccountOut;
  trigger?: ReactNode;
}) {
  const t = useTranslations('accountsFeature.editDialog');
  const schema = z.object({
    password: z.string().optional(),
    display_name: z.string().optional(),
    tags: z.string().optional(),
    notes: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useUpdateAccount();
  const initialValues = editableAccountValues(account);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: initialValues
  });

  useEffect(() => {
    if (open) {
      reset(editableAccountValues(account));
    }
  }, [open, account, reset]);

  const onSubmit = (data: FormData) => {
    const payload: Record<string, any> = {};
    if (data.password) payload.password = data.password;
    if (hasChanged('display_name', account, data.display_name)) {
      payload.display_name = data.display_name;
    }
    if (hasChanged('tags', account, data.tags)) payload.tags = data.tags;
    if (hasChanged('notes', account, data.notes)) payload.notes = data.notes;
    if (Object.keys(payload).length === 0) {
      setOpen(false);
      return;
    }
    mutate(
      { accountId: account.id, data: payload },
      { onSuccess: () => setOpen(false) }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size='icon' variant='ghost' className='size-8'>
            <Pencil size={14} />
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-lg'>
        <DialogHeader>
          <DialogTitle>
            {t('title')} — {account.username}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4 pt-2'>
          <dl className='grid gap-3 rounded-lg border bg-muted/30 p-3 sm:grid-cols-2'>
            <SummaryItem label={t('usernameLabel')} value={account.username} />
            <SummaryItem label={t('platformLabel')} value={account.platform} />
            <SummaryItem
              label={t('stateLabel')}
              value={accountStateLabel(account, t)}
            />
            {account.observed_display_name ? (
              <SummaryItem
                label={t('observedDisplayNameLabel')}
                value={account.observed_display_name}
              />
            ) : null}
          </dl>
          <div className='grid grid-cols-2 gap-4'>
            <div className='space-y-1'>
              <Label>{t('passwordLabel')}</Label>
              <Input
                type='password'
                placeholder={t('passwordPlaceholder')}
                {...register('password')}
              />
            </div>
            <div className='space-y-1'>
              <Label>{t('displayNameLabel')}</Label>
              <Input
                placeholder={t('displayNamePlaceholder')}
                {...register('display_name')}
              />
              {!account.display_name && account.observed_display_name ? (
                <p className='text-xs text-muted-foreground'>
                  {t('observedDisplayNameHint', {
                    name: account.observed_display_name
                  })}
                </p>
              ) : null}
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
