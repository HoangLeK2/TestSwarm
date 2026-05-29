'use client';

import { useState } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { useCreateAccountGroup } from '../hooks/use-account-groups';
import type { AccountGroupRotationStrategy } from '../services/api';
import {
  ACCOUNT_PLATFORM_OPTIONS,
  ACCOUNT_PLATFORM_SELECT_OPTIONS
} from '@/constants/account-platforms';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
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
  platform: string;
  rotation_strategy: AccountGroupRotationStrategy;
  description?: string;
};

export function CreateGroupDialog() {
  const t = useTranslations('accountGroupsFeature');
  const schema = z.object({
    name: z.string().min(1, t('nameRequired')),
    platform: z.enum(ACCOUNT_PLATFORM_OPTIONS, {
      message: t('platformRequired')
    }),
    rotation_strategy: z.enum(['round_robin', 'least_recent']),
    description: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const { mutate, isPending, error } = useCreateAccountGroup();
  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      platform: 'facebook',
      rotation_strategy: 'round_robin',
      description: ''
    }
  });

  const onSubmit = (data: FormData) => {
    mutate(
      {
        name: data.name,
        platform: data.platform,
        rotation_strategy: data.rotation_strategy,
        description: data.description || null
      },
      {
        onSuccess: () => {
          toast.success(t('createSuccess'));
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
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus size={16} className='mr-1' />
          {t('createButton')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('createDialog.title')}</DialogTitle>
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
            <Label>{t('platformLabel')}</Label>
            <Controller
              control={control}
              name='platform'
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger className='h-9 w-full'>
                    <SelectValue placeholder={t('platformPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent className='z-[10001]'>
                    {ACCOUNT_PLATFORM_SELECT_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {t(opt.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.platform && (
              <p className='text-xs text-destructive'>
                {errors.platform.message}
              </p>
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
                        id='rotation-round-robin'
                      />
                      <Label
                        htmlFor='rotation-round-robin'
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
                        id='rotation-least-recent'
                      />
                      <Label
                        htmlFor='rotation-least-recent'
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
            <Textarea
              placeholder={t('descriptionPlaceholder')}
              rows={2}
              {...register('description')}
            />
          </div>
          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('createDialog.title'))}
            </p>
          )}
          <div className='flex gap-2'>
            <Button
              type='button'
              variant='outline'
              className='flex-1'
              disabled={isPending}
              onClick={() => setOpen(false)}
            >
              {t('createDialog.cancel')}
            </Button>
            <Button type='submit' className='flex-1' disabled={isPending}>
              {isPending
                ? t('createDialog.submitting')
                : t('createDialog.submit')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
