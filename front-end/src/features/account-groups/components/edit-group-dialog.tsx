'use client';

import { useEffect } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { useUpdateAccountGroup } from '../hooks/use-account-groups';
import type {
  AccountGroupOut,
  AccountGroupRotationStrategy
} from '../services/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { Info } from 'lucide-react';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

type FormData = {
  name: string;
  rotation_strategy: AccountGroupRotationStrategy;
  description?: string;
};

export function EditGroupDialog({
  group,
  open,
  onOpenChange
}: {
  group: AccountGroupOut;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations('accountGroupsFeature');
  const schema = z.object({
    name: z.string().min(1, t('nameRequired')),
    rotation_strategy: z.enum(['round_robin', 'least_recent']),
    description: z.string().optional()
  });
  const { mutate, isPending, error } = useUpdateAccountGroup();
  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: group.name,
      rotation_strategy: group.rotation_strategy,
      description: group.description ?? ''
    }
  });

  useEffect(() => {
    if (open) {
      reset({
        name: group.name,
        rotation_strategy: group.rotation_strategy,
        description: group.description ?? ''
      });
    }
  }, [open, group, reset]);

  const onSubmit = (data: FormData) => {
    const description = data.description?.trim() || undefined;
    mutate(
      {
        groupId: group.id,
        data: {
          name: data.name,
          rotation_strategy: data.rotation_strategy,
          description
        }
      },
      {
        onSuccess: () => {
          toast.success(t('updateSuccess'));
          onOpenChange(false);
        }
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('editDialog.title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4 pt-2'>
          <div className='space-y-1'>
            <Label>{t('nameLabel')}</Label>
            <Input {...register('name')} />
            {errors.name && (
              <p className='text-xs text-destructive'>{errors.name.message}</p>
            )}
          </div>
          <div className='space-y-2'>
            <Label>{t('rotationLabel')}</Label>
            <Controller
              control={control}
              name='rotation_strategy'
              render={({ field }) => (
                <RadioGroup
                  value={field.value}
                  onValueChange={field.onChange}
                  className='grid gap-2'
                >
                  <TooltipProvider>
                    <div className='flex items-center gap-2'>
                      <RadioGroupItem
                        value='round_robin'
                        id='edit-rotation-round-robin'
                      />
                      <Label
                        htmlFor='edit-rotation-round-robin'
                        className='cursor-pointer text-sm font-normal'
                      >
                        {t('rotationRoundRobin')}
                      </Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info size={13} className='text-muted-foreground' />
                        </TooltipTrigger>
                        <TooltipContent>
                          {t('rotationRoundRobinHint')}
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <div className='flex items-center gap-2'>
                      <RadioGroupItem
                        value='least_recent'
                        id='edit-rotation-least-recent'
                      />
                      <Label
                        htmlFor='edit-rotation-least-recent'
                        className='cursor-pointer text-sm font-normal'
                      >
                        {t('rotationLeastRecent')}
                      </Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info size={13} className='text-muted-foreground' />
                        </TooltipTrigger>
                        <TooltipContent>
                          {t('rotationLeastRecentHint')}
                        </TooltipContent>
                      </Tooltip>
                    </div>
                  </TooltipProvider>
                </RadioGroup>
              )}
            />
          </div>
          <div className='space-y-1'>
            <Label>{t('descriptionLabel')}</Label>
            <Textarea rows={2} {...register('description')} />
          </div>
          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('editDialog.title'))}
            </p>
          )}
          <Button type='submit' className='w-full' disabled={isPending}>
            {isPending ? t('editDialog.submitting') : t('editDialog.submit')}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
