'use client';

import { useState } from 'react';
import { Rocket } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { useCreateCampaign } from '@/features/campaigns/hooks/use-campaigns';
import type { ScenarioTemplateOut } from '../services/api';
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
import { FlowEditor } from '@/features/campaigns/components/flow-editor';
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
    if (v !== null && typeof v === 'object' && !Array.isArray(v) && 'type' in v) {
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

export function UseTemplateDialog({ template }: { template: ScenarioTemplateOut }) {
  const t = useTranslations('scenarioTemplatesFeature.useDialog');
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [campaignName, setCampaignName] = useState(`${template.name} campaign`);

  const { defs, initValues } = parseTemplatVars(template.variables);
  const [varValues, setVarValues] = useState<Record<string, string>>(initValues);

  const { mutate, isPending } = useCreateCampaign();

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
        variables: typedVars,
      },
      {
        onSuccess: () => {
          setOpen(false);
          router.push(ROUTES.CAMPAIGNS.ROOT);
        },
      }
    );
  };

  const varKeys = Object.keys(defs);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline' className='text-xs gap-1'>
          <Rocket size={12} />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <p className='text-sm text-muted-foreground'>{template.name}</p>
        </DialogHeader>
        <div className='space-y-4 pt-2'>
          <div className='space-y-1'>
            <Label>{t('campaignNameLabel')}</Label>
            <Input
              value={campaignName}
              onChange={(e) => setCampaignName(e.target.value)}
            />
          </div>

          {varKeys.length > 0 && (
            <div className='space-y-3'>
              <Label>{t('variablesLabel')}</Label>
              {varKeys.map((key) => {
                const def = defs[key];
                return (
                  <div key={key} className='space-y-1'>
                    <div className='flex items-center gap-1.5'>
                      <code className='text-xs font-semibold font-mono text-foreground'>{key}</code>
                      {def.required && (
                        <span className='rounded bg-red-500/10 px-1 py-px text-[9px] font-medium text-red-600 dark:text-red-400'>
                          bắt buộc
                        </span>
                      )}
                      <span className='rounded bg-muted px-1 py-px text-[9px] text-muted-foreground font-mono'>
                        {def.type}
                      </span>
                    </div>
                    {def.description && (
                      <p className='text-[11px] text-muted-foreground leading-relaxed'>{def.description}</p>
                    )}
                    <Input
                      value={varValues[key] ?? ''}
                      onChange={(e) => setVarValues((prev) => ({ ...prev, [key]: e.target.value }))}
                      placeholder={`Nhập giá trị cho ${key}…`}
                      className={cn(
                        'h-8 font-mono text-xs',
                        def.required && !varValues[key]?.trim() && 'border-red-400/60 focus-visible:ring-red-400/30',
                      )}
                      type={def.type === 'integer' || def.type === 'float' || def.type === 'number' ? 'number' : 'text'}
                      min={def.min}
                      max={def.max}
                    />
                  </div>
                );
              })}
            </div>
          )}

          <div className='space-y-1'>
            <p className='text-xs font-medium'>
              {t('stepsPreview')} ({template.steps?.length ?? 0} {t('steps')})
            </p>
            {(template.steps?.length ?? 0) > 0 && (
              <FlowEditor
                steps={template.steps}
                onChange={() => {}}
                maxHeight='200px'
                compact
              />
            )}
          </div>
          <Button
            onClick={handleCreate}
            disabled={isPending || !campaignName.trim()}
            className='w-full'
          >
            {isPending ? t('creating') : t('submit')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
