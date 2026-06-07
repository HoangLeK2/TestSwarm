'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Copy } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import type { ScenarioLibraryItem } from '../lib/scenario-library-item';
import { useCloneScenarioTemplateToOrg } from '../hooks/use-org-scenarios';

type FormData = { name: string };

export function CloneTemplateDialog({
  template,
  className,
  variant = 'outline'
}: {
  template: Pick<ScenarioLibraryItem, 'id' | 'name'>;
  className?: string;
  variant?: 'default' | 'outline';
}) {
  const t = useTranslations('orgScenariosFeature.cloneDialog');
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error, reset } = useCloneScenarioTemplateToOrg();
  const schema = z.object({
    name: z.string().min(1, t('nameRequired'))
  });
  const {
    register,
    handleSubmit,
    reset: resetForm,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { name: `${template.name} copy` }
  });

  const onSubmit = (data: FormData) => {
    mutate(
      {
        templateId: template.id,
        data: { name_override: data.name.trim() }
      },
      {
        onSuccess: () => {
          toast.success(t('cloneSuccess'));
          resetForm({ name: `${template.name} copy` });
          reset();
          setOpen(false);
        }
      }
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) resetForm({ name: `${template.name} copy` });
      }}
    >
      <DialogTrigger asChild>
        <Button size='sm' variant={variant} className={className}>
          <Copy size={14} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4'>
          <p className='text-sm text-muted-foreground'>
            {t('sourceHint', { name: template.name })}
          </p>
          <div className='space-y-1.5'>
            <Label>{t('nameLabel')}</Label>
            <Input {...register('name')} />
            {errors.name && (
              <p className='text-xs text-destructive'>{errors.name.message}</p>
            )}
          </div>
          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('cloneFailed'))}
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
              {isPending ? t('cloning') : t('submit')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
