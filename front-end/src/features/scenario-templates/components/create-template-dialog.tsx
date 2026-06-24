'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus, ExternalLink } from 'lucide-react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useCreateScenarioTemplate } from '../hooks/use-scenario-templates';
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
import { FlowEditor } from '@/features/campaigns/components/flow-editor/flow-editor';
import { VariableEditor } from '@/components/variable-editor';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

type FormData = {
  name: string;
  display_name?: string;
  description?: string;
  category?: string;
  tags?: string;
};

export function CreateTemplateDialog() {
  const t = useTranslations('scenarioTemplatesFeature.createDialog');
  const schema = z.object({
    name: z.string().min(1, t('technicalNameRequired')),
    display_name: z.string().optional(),
    description: z.string().optional(),
    category: z.string().optional(),
    tags: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const [childStepEditorOpen, setChildStepEditorOpen] = useState(false);
  const [steps, setSteps] = useState<FlowStep[]>([]);
  const [variables, setVariables] = useState<Record<string, any>>({});
  const { mutate, mutateAsync, isPending, error } = useCreateScenarioTemplate();
  const router = useRouter();
  const locale = useLocale();
  const [openingControl, setOpeningControl] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = (data: FormData) => {
    mutate(
      {
        name: data.name,
        display_name: data.display_name,
        description: data.description,
        category: data.category || 'general',
        tags: data.tags,
        steps,
        variables
      },
      {
        onSuccess: () => {
          reset();
          setSteps([]);
          setVariables({});
          setOpen(false);
        }
      }
    );
  };

  // "Tạo + mở ở Control": create the template with current metadata (steps can
  // be empty at this point) and immediately navigate to the control page with
  // ?templateId=, where the user can record/edit steps on a real device and
  // save back via the existing template update API.
  const onSubmitAndOpenControl = handleSubmit(async (data) => {
    setOpeningControl(true);
    try {
      const created = await mutateAsync({
        name: data.name,
        display_name: data.display_name,
        description: data.description,
        category: data.category || 'general',
        tags: data.tags,
        steps,
        variables
      });
      reset();
      setSteps([]);
      setVariables({});
      setOpen(false);
      router.push(
        `/${locale}/dashboard/device-farm/control?templateId=${encodeURIComponent(created.id)}`
      );
    } catch {
      // error surfaced via the `error` render below
    } finally {
      setOpeningControl(false);
    }
  });

  return (
    <Dialog open={open} onOpenChange={setOpen} modal={!childStepEditorOpen}>
      <DialogTrigger asChild>
        <Button size='sm'>
          <Plus size={16} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-h-[90vh] max-w-4xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4 pt-2'>
          <div className='grid grid-cols-2 gap-4'>
            <div className='space-y-1'>
              <Label>{t('technicalNameLabel')}</Label>
              <Input
                className='font-mono text-sm'
                placeholder={t('technicalNamePlaceholder')}
                {...register('name')}
              />
              {errors.name && (
                <p className='text-xs text-destructive'>
                  {errors.name.message}
                </p>
              )}
            </div>
            <div className='space-y-1'>
              <Label>{t('displayNameLabel')}</Label>
              <Input
                placeholder={t('displayNamePlaceholder')}
                {...register('display_name')}
              />
            </div>
          </div>
          <div className='grid grid-cols-2 gap-4'>
            <div className='space-y-1'>
              <Label>{t('categoryLabel')}</Label>
              <Input placeholder='general' {...register('category')} />
            </div>
          </div>
          <div className='space-y-1'>
            <Label>{t('descriptionLabel')}</Label>
            <Textarea
              placeholder={t('descriptionPlaceholder')}
              {...register('description')}
              rows={2}
            />
          </div>
          <div className='space-y-1'>
            <Label>{t('tagsLabel')}</Label>
            <Input placeholder={t('tagsPlaceholder')} {...register('tags')} />
          </div>

          {/* Steps — FlowEditor */}
          <div className='space-y-1'>
            <Label>
              {t('stepsLabel', { fallback: 'Các bước' })} ({steps.length})
            </Label>
            <FlowEditor
              nestedInDialog
              steps={steps}
              onChange={setSteps}
              onChildStepEditorOpenChange={setChildStepEditorOpen}
              maxHeight='300px'
            />
          </div>

          {/* Variables */}
          <details className='group'>
            <summary className='flex cursor-pointer items-center gap-1 text-sm font-medium'>
              <span>
                {t('variablesLabel', { fallback: 'Biến (Variables)' })}
              </span>
              {Object.keys(variables).length > 0 && (
                <span className='text-xs text-muted-foreground'>
                  ({Object.keys(variables).length})
                </span>
              )}
            </summary>
            <div className='pt-2'>
              <VariableEditor variables={variables} onChange={setVariables} />
              <p className='mt-1 text-[10px] text-muted-foreground'>
                {'${VAR_NAME}'} trong steps sẽ được thay thế khi chạy. Built-in:{' '}
                {'${__NOW__}'} {'${__DATE__}'} {'${__DEVICE_SERIAL__}'}
              </p>
            </div>
          </details>

          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('createFailed'))}
            </p>
          )}
          <div className='flex flex-col gap-2 sm:flex-row'>
            <Button
              type='button'
              variant='outline'
              className='w-full sm:flex-1'
              disabled={isPending || openingControl}
              onClick={() => {
                void onSubmitAndOpenControl();
              }}
            >
              <ExternalLink size={14} className='mr-1' />
              {openingControl ? t('openingControl') : t('submitAndOpenControl')}
            </Button>
            <Button
              type='submit'
              className='w-full sm:flex-1'
              disabled={isPending || openingControl}
            >
              {isPending ? t('creating') : t('submit')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
