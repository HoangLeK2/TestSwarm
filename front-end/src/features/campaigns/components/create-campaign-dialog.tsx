'use client';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useCreateCampaign } from '../hooks/use-campaigns';
import { useDeviceGroups } from '@/features/device-groups/hooks/use-device-groups';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { VariableEditor } from '@/components/variable-editor';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '@/components/ui/select';
import { useState } from 'react';
import { Plus } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

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
  const [variables, setVariables] = useState<Record<string, any>>({});
  const [targetGroupId, setTargetGroupId] = useState<string | undefined>(undefined);
  const { mutate, isPending, error } = useCreateCampaign();
  const { data: groups } = useDeviceGroups();
  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema)
  });

  const onSubmit = (data: FormData) => {
    mutate(
      {
        ...data,
        variables: Object.keys(variables).length > 0 ? variables : undefined,
        target_group_id: targetGroupId || undefined
      },
      {
        onSuccess: () => {
          reset();
          setVariables({});
          setTargetGroupId(undefined);
          setOpen(false);
        }
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen} >
      <DialogTrigger asChild>
        <Button size='sm'><Plus size={16} className='mr-1' />{t('trigger')}</Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-lg'>
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
          <div className='space-y-1'>
            <Label>{t('targetGroupLabel')}</Label>
            <Select
              value={targetGroupId ?? '_none'}
              onValueChange={(v) => setTargetGroupId(v === '_none' ? undefined : v)}
            >
              <SelectTrigger>
                <SelectValue placeholder={t('targetGroupPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='_none'>{t('noGroup')}</SelectItem>
                {(groups ?? []).map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    <span className='flex items-center gap-2'>
                      <span
                        className='inline-block size-3 rounded-full'
                        style={{ backgroundColor: g.color }}
                      />
                      {g.name} ({g.device_count})
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className='space-y-1'>
            <Label>{t('variablesLabel')}</Label>
            <VariableEditor variables={variables} onChange={setVariables} />
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
