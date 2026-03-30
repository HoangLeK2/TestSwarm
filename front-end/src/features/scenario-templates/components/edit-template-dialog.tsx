'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Pencil } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useUpdateScenarioTemplate } from '../hooks/use-scenario-templates';
import type { ScenarioTemplateOut } from '../services/api';
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
import { FlowEditor } from '@/features/campaigns/components/flow-editor';
import { VariableEditor } from '@/components/variable-editor';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

type FormData = {
  name: string;
  description?: string;
  category?: string;
  tags?: string;
};

export function EditTemplateDialog({
  template,
  children
}: {
  template: ScenarioTemplateOut;
  children?: React.ReactNode;
}) {
  const t = useTranslations('scenarioTemplatesFeature.editDialog');
  const schema = z.object({
    name: z.string().min(1, t('nameRequired')),
    description: z.string().optional(),
    category: z.string().optional(),
    tags: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const [steps, setSteps] = useState<FlowStep[]>([]);
  const [variables, setVariables] = useState<Record<string, any>>({});
  const { mutate, isPending, error } = useUpdateScenarioTemplate();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: template.name,
      description: template.description,
      category: template.category,
      tags: template.tags
    }
  });

  useEffect(() => {
    if (open) {
      reset({
        name: template.name,
        description: template.description,
        category: template.category,
        tags: template.tags
      });
      setSteps(template.steps?.length ? [...template.steps] : []);
      setVariables(template.variables ?? {});
    }
  }, [open, template, reset]);

  const onSubmit = (data: FormData) => {
    mutate(
      {
        templateId: template.id,
        data: {
          name: data.name,
          description: data.description,
          category: data.category || 'general',
          tags: data.tags,
          steps,
          variables
        }
      },
      { onSuccess: () => setOpen(false) }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {children ?? (
          <Button size='icon' variant='ghost' className='size-8'>
            <Pencil size={14} />
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className='z-[1000] max-h-[90vh] max-w-4xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className='space-y-4 pt-2'>
          <div className='grid grid-cols-2 gap-4'>
            <div className='space-y-1'>
              <Label>{t('nameLabel')}</Label>
              <Input {...register('name')} />
              {errors.name && <p className='text-xs text-destructive'>{errors.name.message}</p>}
            </div>
            <div className='space-y-1'>
              <Label>{t('categoryLabel')}</Label>
              <Input {...register('category')} />
            </div>
          </div>
          <div className='space-y-1'>
            <Label>{t('descriptionLabel')}</Label>
            <Textarea {...register('description')} rows={2} />
          </div>
          <div className='space-y-1'>
            <Label>{t('tagsLabel')}</Label>
            <Input {...register('tags')} />
          </div>

          {/* Steps — FlowEditor */}
          <div className='space-y-1'>
            <Label>{t('stepsLabel')} ({steps.length})</Label>
            <FlowEditor steps={steps} onChange={setSteps} maxHeight='350px' />
          </div>

          {/* Variables */}
          <details className='group'>
            <summary className='cursor-pointer text-sm font-medium flex items-center gap-1'>
              <span>{t('variablesLabel', { fallback: 'Biến (Variables)' })}</span>
              {Object.keys(variables).length > 0 && (
                <span className='text-xs text-muted-foreground'>
                  ({Object.keys(variables).length})
                </span>
              )}
            </summary>
            <div className='pt-2'>
              <VariableEditor variables={variables} onChange={setVariables} />
              <p className='mt-1 text-[10px] text-muted-foreground'>
                {'${VAR_NAME}'} trong steps sẽ được thay thế khi chạy.
              </p>
            </div>
          </details>

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
