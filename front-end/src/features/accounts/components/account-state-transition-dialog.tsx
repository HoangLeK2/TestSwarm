'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ArrowRightLeft } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useTransitionAccountState } from '../hooks/use-accounts';
import type { AccountOut } from '../services/api';
import {
  ACCOUNT_STATES,
  allowedTransitionTargets,
  type AccountStateKey
} from '../lib/account-fsm';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

type FormData = {
  to: AccountStateKey;
  reason: string;
};

type Props = {
  account: AccountOut;
  defaultTo?: AccountStateKey;
  trigger?: React.ReactNode;
};

export function AccountStateTransitionDialog({
  account,
  defaultTo,
  trigger
}: Props) {
  const t = useTranslations('accountsFeature.stateDialog');
  const tList = useTranslations('accountsFeature.list');
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useTransitionAccountState();

  const current = (account.state || account.status) as AccountStateKey;
  const targets = allowedTransitionTargets(current);
  const firstTarget =
    defaultTo && targets.includes(defaultTo) ? defaultTo : targets[0];

  const schema = z.object({
    to: z.enum(ACCOUNT_STATES),
    reason: z.string().min(1).max(2000)
  });

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      to: firstTarget ?? 'active',
      reason: ''
    }
  });

  const toValue = watch('to');

  useEffect(() => {
    if (open && firstTarget) {
      reset({ to: firstTarget, reason: '' });
    }
  }, [open, firstTarget, reset]);

  const statusLabel = (key: AccountStateKey) => {
    const map: Record<AccountStateKey, string> = {
      unassigned: tList('statusUnassigned'),
      assigned: tList('statusAssigned'),
      active: tList('statusActive'),
      suspended: tList('statusVerifying'),
      banned: tList('statusBanned'),
      retired: tList('statusRetired')
    };
    return map[key] ?? key;
  };

  const onSubmit = (data: FormData) => {
    const body = {
      to: data.to,
      reason: data.reason.trim(),
      expected_state_changed_at: account.state_changed_at ?? null
    };
    mutate(
      { accountId: account.id, body },
      { onSuccess: () => setOpen(false) }
    );
  };

  if (targets.length === 0) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size='sm' variant='outline' className='h-8 gap-1'>
            <ArrowRightLeft size={14} />
            {defaultTo
              ? t('triggerTo', { status: statusLabel(defaultTo) })
              : t('trigger')}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>
            {t('title', { username: account.username })}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4'>
          <p className='text-sm text-muted-foreground'>
            {t('currentState', { status: statusLabel(current) })}
          </p>
          <div className='space-y-2'>
            <Label>{t('targetState')}</Label>
            <Select
              value={toValue}
              onValueChange={(v) => setValue('to', v as AccountStateKey)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {targets.map((s) => (
                  <SelectItem key={s} value={s}>
                    {statusLabel(s)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-2'>
            <Label htmlFor='reason'>{t('reason')}</Label>
            <Textarea id='reason' rows={3} {...register('reason')} />
            {errors.reason ? (
              <p className='text-xs text-destructive'>
                {errors.reason.message}
              </p>
            ) : null}
          </div>
          {account.state_reason ? (
            <p className='text-xs text-muted-foreground'>
              {t('lastReason', { reason: account.state_reason })}
            </p>
          ) : null}
          {error ? (
            <p className='text-sm text-destructive'>
              {formatFarmApiError(error, t('submitFailed'))}
            </p>
          ) : null}
          <Button type='submit' disabled={isPending} className='w-full'>
            {isPending ? t('submitting') : t('submit')}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
