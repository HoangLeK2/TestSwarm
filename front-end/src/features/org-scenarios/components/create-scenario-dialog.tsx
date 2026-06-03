'use client';

import { useState, type ReactNode } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
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
import { useCreateOrgScenario } from '../hooks/use-org-scenarios';
import type { OrgScenarioSummaryOut } from '../services/api';

type FormData = {
  name: string;
  description?: string;
  tags?: string;
};

type CreateOrgScenarioDialogProps = {
  /** Called after a scenario shell is created (e.g. auto-select in campaign picker). */
  onCreated?: (scenario: OrgScenarioSummaryOut) => void;
  /** Custom trigger; defaults to primary “New scenario” button. */
  trigger?: ReactNode;
};

export function CreateOrgScenarioDialog({
  onCreated,
  trigger
}: CreateOrgScenarioDialogProps = {}) {
  const t = useTranslations('orgScenariosFeature.createDialog');
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error, reset: resetMutation } = useCreateOrgScenario();
  const schema = z.object({
    name: z.string().min(1, t('nameRequired')),
    description: z.string().optional(),
    tags: z.string().optional()
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {}
  });

  const onSubmit = (data: FormData) => {
    const tags = (data.tags ?? '')
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
    mutate(
      {
        name: data.name.trim(),
        description: data.description?.trim() ?? '',
        kind: 'sequence',
        tags
      },
      {
        onSuccess: (created) => {
          reset();
          resetMutation();
          setOpen(false);
          onCreated?.(created);
        }
      }
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size='sm'>
            <Plus size={16} className='mr-1' />
            {t('trigger')}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4'>
          <div className='space-y-1.5'>
            <Label>{t('nameLabel')}</Label>
            <Input placeholder={t('namePlaceholder')} {...register('name')} />
            {errors.name && (
              <p className='text-xs text-destructive'>{errors.name.message}</p>
            )}
          </div>
          <div className='space-y-1.5'>
            <Label>{t('descriptionLabel')}</Label>
            <Textarea
              placeholder={t('descriptionPlaceholder')}
              className='min-h-[72px] resize-none'
              {...register('description')}
            />
          </div>
          <div className='space-y-1.5'>
            <Label>{t('tagsLabel')}</Label>
            <Input placeholder={t('tagsPlaceholder')} {...register('tags')} />
          </div>
          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('createFailed'))}
            </p>
          )}
          <div className='flex justify-end gap-2'>
            <Button
              type='button'
              variant='ghost'
              size='sm'
              onClick={() => setOpen(false)}
            >
              {t('cancel')}
            </Button>
            <Button type='submit' size='sm' disabled={isPending}>
              {isPending ? t('creating') : t('submit')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
