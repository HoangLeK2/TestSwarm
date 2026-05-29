'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useCampaigns, useCreateCampaign } from '../hooks/use-campaigns';
import { useDeviceGroups } from '@/features/device-groups/hooks/use-device-groups';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { VariableEditor } from '@/components/variable-editor';
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
import { useState } from 'react';
import { Plus, Layers, FileText, MonitorSpeaker, Variable } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { cn } from '@/lib/utils';

type FormData = {
  name: string;
  description?: string;
};

type SocialPlatform = 'facebook' | 'instagram' | 'tiktok' | 'linkedin';

const PLATFORM_OPTIONS: Array<{ value: SocialPlatform; labelKey: string }> = [
  { value: 'facebook', labelKey: 'platformFacebook' },
  { value: 'instagram', labelKey: 'platformInstagram' },
  { value: 'tiktok', labelKey: 'platformTiktok' },
  { value: 'linkedin', labelKey: 'platformLinkedin' }
];

function Section({
  icon: Icon,
  title,
  hint,
  children
}: {
  icon: React.ElementType;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className='space-y-3'>
      <div className='flex items-center gap-2'>
        <Icon size={13} className='shrink-0 text-muted-foreground' />
        <span className='text-xs font-semibold text-foreground'>{title}</span>
        {hint && (
          <span className='text-[10px] text-muted-foreground'>{hint}</span>
        )}
      </div>
      <div className='pl-5'>{children}</div>
    </div>
  );
}

export function CreateCampaignDialog() {
  const t = useTranslations('campaignsFeature.createDialog');
  const { data: campaigns } = useCampaigns();
  const existingNames = new Set(
    (campaigns ?? [])
      .map((c) => (c.name ?? '').trim().toLowerCase())
      .filter(Boolean)
  );
  const schema = z.object({
    name: z
      .string()
      .min(1, t('nameRequired'))
      .refine(
        (v) => !existingNames.has(v.trim().toLowerCase()),
        t('nameUnique')
      ),
    description: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const [variables, setVariables] = useState<Record<string, any>>({});
  const [platform, setPlatform] = useState<SocialPlatform>('facebook');
  const [targetGroupId, setTargetGroupId] = useState<string | undefined>(
    undefined
  );
  const { mutate, isPending, error } = useCreateCampaign();
  const { data: groups } = useDeviceGroups();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = (data: FormData) => {
    const nextVariables: Record<string, any> = {
      ...variables,
      __PLATFORM__: platform
    };
    mutate(
      {
        ...data,
        variables:
          Object.keys(nextVariables).length > 0 ? nextVariables : undefined,
        target_group_id: targetGroupId || undefined
      },
      {
        onSuccess: () => {
          reset();
          setVariables({});
          setPlatform('facebook');
          setTargetGroupId(undefined);
          setOpen(false);
        }
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus size={16} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>

      <DialogContent className='max-h-[90vh] max-w-lg gap-0 overflow-y-auto p-0'>
        <DialogHeader className='border-b px-5 py-4'>
          <div className='flex items-center gap-2'>
            <Layers size={15} className='text-primary' />
            <DialogTitle className='text-sm font-semibold'>
              {t('title')}
            </DialogTitle>
          </div>
          <p className='mt-0.5 text-[11px] text-muted-foreground'>
            Campaign gộp nhiều thiết bị và kịch bản vào một lần chạy.
          </p>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)}>
          <div className='space-y-5 px-5 py-5'>
            {/* Basic info */}
            <Section icon={FileText} title='Thông tin cơ bản'>
              <div className='space-y-3'>
                <div className='space-y-1.5'>
                  <Label className='text-xs'>{t('nameLabel')}</Label>
                  <Input
                    placeholder={t('namePlaceholder')}
                    className={cn('h-9', errors.name && 'border-destructive')}
                    {...register('name')}
                  />
                  {errors.name && (
                    <p className='text-[11px] text-destructive'>
                      {errors.name.message}
                    </p>
                  )}
                </div>
                <div className='space-y-1.5'>
                  <Label className='text-xs'>{t('descriptionLabel')}</Label>
                  <Textarea
                    placeholder={t('descriptionPlaceholder')}
                    className='min-h-[60px] resize-none text-sm'
                    {...register('description')}
                  />
                </div>
              </div>
            </Section>

            <hr className='border-border' />

            <Section icon={Layers} title={t('platformLabel')} hint='(required)'>
              <Select
                value={platform}
                onValueChange={(v) => setPlatform(v as SocialPlatform)}
              >
                <SelectTrigger className='h-9 w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className='z-[10001]'>
                  {PLATFORM_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {t(opt.labelKey)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className='mt-1.5 text-[11px] text-muted-foreground'>
                {t('platformHint')}
              </p>
            </Section>

            <hr className='border-border' />

            {/* Target group */}
            <Section
              icon={MonitorSpeaker}
              title={t('targetGroupLabel')}
              hint='(tuỳ chọn)'
            >
              <Select
                value={targetGroupId ?? '_none'}
                onValueChange={(v) =>
                  setTargetGroupId(v === '_none' ? undefined : v)
                }
              >
                <SelectTrigger className='h-9 w-full'>
                  <SelectValue placeholder={t('targetGroupPlaceholder')} />
                </SelectTrigger>
                {/* z-[10001] to appear above DialogContent (which is at z-10000) */}
                <SelectContent className='z-[10001]'>
                  <SelectItem value='_none'>
                    <span className='text-muted-foreground'>
                      {t('noGroup')}
                    </span>
                  </SelectItem>
                  {(groups ?? []).map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      <span className='flex items-center gap-2'>
                        <span
                          className='inline-block size-3 shrink-0 rounded-full'
                          style={{ backgroundColor: g.color }}
                        />
                        <span>{g.name}</span>
                        <span className='text-muted-foreground'>
                          ({g.device_count})
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                  {(groups ?? []).length === 0 && (
                    <div className='px-2 py-1.5 text-xs text-muted-foreground'>
                      Chưa có nhóm nào. Tạo nhóm thiết bị trước.
                    </div>
                  )}
                </SelectContent>
              </Select>
              <p className='mt-1.5 text-[11px] text-muted-foreground'>
                Campaign sẽ chạy trên tất cả thiết bị trong nhóm này. Bỏ trống
                để chọn thiết bị sau.
              </p>
            </Section>

            <hr className='border-border' />

            {/* Variables */}
            <Section
              icon={Variable}
              title={t('variablesLabel')}
              hint='(tuỳ chọn)'
            >
              <p className='mb-2 text-[11px] text-muted-foreground'>
                Biến được dùng trong kịch bản qua cú pháp{' '}
                <code className='rounded bg-muted px-1 font-mono'>
                  {'${tên_biến}'}
                </code>
                . Ví dụ:{' '}
                <code className='rounded bg-muted px-1 font-mono'>
                  username
                </code>
                ,{' '}
                <code className='rounded bg-muted px-1 font-mono'>
                  password
                </code>
                .
              </p>
              <p className='mb-2 text-[11px] text-muted-foreground'>
                {t('accountModeHint')}
              </p>
              <VariableEditor variables={variables} onChange={setVariables} />
            </Section>
          </div>

          {/* Footer */}
          <div className='border-t bg-muted/30 px-5 py-3'>
            {error && (
              <p className='mb-2 text-[11px] text-destructive'>
                {formatFarmApiError(error, t('createFailed'))}
              </p>
            )}
            <div className='flex justify-end gap-2'>
              <Button
                type='button'
                variant='ghost'
                size='sm'
                onClick={() => setOpen(false)}
                disabled={isPending}
              >
                Huỷ
              </Button>
              <Button type='submit' size='sm' disabled={isPending}>
                {isPending ? t('creating') : t('submit')}
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
