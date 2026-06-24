'use client';

import { useState } from 'react';
import { Rocket } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { useCreateCampaign } from '@/features/campaigns/hooks/use-campaigns';
import type { ScenarioTemplateOut } from '../services/api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
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
import { FlowEditor } from '@/features/campaigns/components/flow-editor/flow-editor';
import { cn } from '@/lib/utils';

/** One template variable definition from the DB. */
interface VarDef {
  type: string;
  default: any;
  description?: string;
  required?: boolean;
  min?: number;
  max?: number;
}

/** Separate metadata from raw values; return (defs, initialValues). */
function parseTemplatVars(raw: Record<string, any> | null | undefined): {
  defs: Record<string, VarDef>;
  initValues: Record<string, string>;
} {
  const defs: Record<string, VarDef> = {};
  const initValues: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw ?? {})) {
    if (
      v !== null &&
      typeof v === 'object' &&
      !Array.isArray(v) &&
      'type' in v
    ) {
      defs[k] = v as VarDef;
      initValues[k] = v.default != null ? String(v.default) : '';
    } else {
      // Plain value (no metadata) — treat as string with no description
      defs[k] = { type: 'string', default: v };
      initValues[k] = v != null ? String(v) : '';
    }
  }
  return { defs, initValues };
}

export function UseTemplateDialog({
  template
}: {
  template: ScenarioTemplateOut;
}) {
  const t = useTranslations('scenarioTemplatesFeature.useDialog');
  const tCampaignCreate = useTranslations('campaignsFeature.createDialog');
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [campaignName, setCampaignName] = useState(`${template.name} campaign`);

  const { defs, initValues } = parseTemplatVars(template.variables);
  const [varValues, setVarValues] =
    useState<Record<string, string>>(initValues);

  const { mutate, isPending, error, reset } = useCreateCampaign();

  const createErrorMessage = error
    ? (error as { response?: { status?: number } }).response?.status === 409
      ? tCampaignCreate('nameUnique')
      : formatFarmApiError(error, t('createFailed'))
    : null;

  const handleCreate = () => {
    // Convert string inputs back to proper types (int/float for numeric vars)
    const typedVars: Record<string, any> = {};
    for (const [k, strVal] of Object.entries(varValues)) {
      const defType = defs[k]?.type ?? 'string';
      if (defType === 'integer') {
        const n = parseInt(strVal, 10);
        typedVars[k] = isNaN(n) ? strVal : n;
      } else if (defType === 'float' || defType === 'number') {
        const n = parseFloat(strVal);
        typedVars[k] = isNaN(n) ? strVal : n;
      } else {
        typedVars[k] = strVal;
      }
    }

    mutate(
      {
        name: campaignName,
        scenario: { steps: template.steps },
        variables: typedVars
      },
      {
        onSuccess: () => {
          setOpen(false);
          router.push(ROUTES.CAMPAIGNS.ROOT);
        }
      }
    );
  };

  const varKeys = Object.keys(defs);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size='sm' variant='outline' className='gap-1 text-xs'>
          <Rocket size={12} />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent
        className={cn(
          'z-[1000] flex max-h-[min(92vh,900px)] min-h-0 w-full min-w-0 flex-col gap-4 overflow-hidden p-4 sm:p-6',
          'max-w-[calc(100vw-2rem)] sm:max-w-2xl'
        )}
      >
        <DialogHeader className='shrink-0 space-y-1 text-left'>
          <DialogTitle>{t('title')}</DialogTitle>
          <p className='text-sm text-muted-foreground'>{template.name}</p>
        </DialogHeader>
        <div className='min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto overflow-x-hidden pt-0.5'>
          <div className='space-y-1'>
            <Label>{t('campaignNameLabel')}</Label>
            <Input
              className={cn(
                'max-w-full',
                createErrorMessage && 'border-destructive'
              )}
              value={campaignName}
              onChange={(e) => {
                setCampaignName(e.target.value);
                if (error) reset();
              }}
            />
            {createErrorMessage && (
              <p className='text-[11px] text-destructive'>
                {createErrorMessage}
              </p>
            )}
          </div>

          {varKeys.length > 0 && (
            <div className='space-y-3'>
              <Label>{t('variablesLabel')}</Label>
              {varKeys.map((key) => {
                const def = defs[key];
                return (
                  <div key={key} className='space-y-1'>
                    <div className='flex items-center gap-1.5'>
                      <code className='font-mono text-xs font-semibold text-foreground'>
                        {key}
                      </code>
                      {def.required && (
                        <span className='rounded bg-red-500/10 px-1 py-px text-[9px] font-medium text-red-600 dark:text-red-400'>
                          bắt buộc
                        </span>
                      )}
                      <span className='rounded bg-muted px-1 py-px font-mono text-[9px] text-muted-foreground'>
                        {def.type}
                      </span>
                    </div>
                    {def.description && (
                      <p className='text-[11px] leading-relaxed text-muted-foreground'>
                        {def.description}
                      </p>
                    )}
                    <Input
                      value={varValues[key] ?? ''}
                      onChange={(e) =>
                        setVarValues((prev) => ({
                          ...prev,
                          [key]: e.target.value
                        }))
                      }
                      placeholder={`Nhập giá trị cho ${key}…`}
                      className={cn(
                        'h-8 max-w-full font-mono text-xs',
                        def.required &&
                          !varValues[key]?.trim() &&
                          'border-red-400/60 focus-visible:ring-red-400/30'
                      )}
                      type={
                        def.type === 'integer' ||
                        def.type === 'float' ||
                        def.type === 'number'
                          ? 'number'
                          : 'text'
                      }
                      min={def.min}
                      max={def.max}
                    />
                  </div>
                );
              })}
            </div>
          )}

          <div className='min-w-0 space-y-1'>
            <p className='text-xs font-medium'>
              {t('stepsPreview')} ({template.steps?.length ?? 0} {t('steps')})
            </p>
            {(template.steps?.length ?? 0) > 0 && (
              <div className='min-w-0 max-w-full'>
                <FlowEditor
                  nestedInDialog
                  steps={template.steps}
                  onChange={() => {}}
                  maxHeight='min(240px,32vh)'
                  compact
                />
              </div>
            )}
          </div>
        </div>
        <Button
          onClick={handleCreate}
          disabled={isPending || !campaignName.trim()}
          className='w-full shrink-0'
        >
          {isPending ? t('creating') : t('submit')}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
