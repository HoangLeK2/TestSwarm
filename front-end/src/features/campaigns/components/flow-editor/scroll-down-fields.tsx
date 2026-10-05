'use client';

import { useTranslations } from 'next-intl';
import { VariableInsertMenu } from '@/components/variable-insert-menu';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { SCENARIO_VAR_TOKENS } from '../../i18n/scenario-var-tokens';
import type { FlowStep } from '../scenario-steps/types';
import {
  StepPanelField,
  StepPanelHint,
  StepPanelSection
} from './step-panel-primitives';

type ScrollDownStep = FlowStep & {
  repeats?: number;
  start_x_ratio?: number | string;
  start_y_ratio?: number;
  end_y_ratio?: number;
  duration_ms?: number;
  pause_seconds?: number;
};

const X_PRESETS = [
  { id: 'left', value: 0.18 },
  { id: 'center', value: 0.5 },
  { id: 'right', value: 0.82 }
] as const;

function isVarRef(v: string) {
  return /^\$\{[^}]+\}$/.test(v.trim());
}

function parseXRatio(raw: string): number | string | undefined {
  const v = raw.trim();
  if (v === '') return undefined;
  if (isVarRef(v)) return v;
  const n = Number(v.replace(',', '.'));
  return Number.isFinite(n) ? n : v;
}

function xRatioDisplay(step: ScrollDownStep): string {
  if (step.start_x_ratio == null || step.start_x_ratio === '') return '';
  return String(step.start_x_ratio);
}

function activeXPreset(step: ScrollDownStep): string | null {
  const v = step.start_x_ratio;
  if (v == null || v === '' || typeof v === 'string') return null;
  const match = X_PRESETS.find((p) => Math.abs(p.value - Number(v)) < 0.001);
  return match?.id ?? null;
}

export function ScrollDownStepFields({
  step,
  update,
  availableVariables = []
}: {
  step: ScrollDownStep;
  update: (fields: Partial<FlowStep>) => void;
  availableVariables?: string[];
}) {
  const t = useTranslations('campaignsFeature.stepEditor.scrollDown');
  const tStep = useTranslations('campaignsFeature.stepEditor');

  const startY = step.start_y_ratio ?? 0.65;
  const endY = step.end_y_ratio ?? 0.47;
  const swipeDown = startY > endY;

  return (
    <div className='space-y-3'>
      <StepPanelHint>{t('intro')}</StepPanelHint>

      <StepPanelSection title={t('repeatsSectionTitle')}>
        <div className='grid grid-cols-2 gap-3'>
          <StepPanelField label={t('repeatsLabel')}>
            <div className='flex items-center gap-2'>
              <Input
                type='number'
                min={1}
                max={20}
                className='h-9 w-24 text-xs'
                value={step.repeats ?? 1}
                onChange={(e) =>
                  update({
                    repeats: Math.max(1, Number(e.target.value) || 1)
                  })
                }
              />
              <span className='text-[11px] text-muted-foreground'>
                {t('repeatsUnit')}
              </span>
            </div>
          </StepPanelField>
          <StepPanelField label={t('pauseSecondsLabel')}>
            <div className='flex items-center gap-2'>
              <Input
                type='number'
                min={0}
                step={0.1}
                className='h-9 w-24 text-xs'
                value={step.pause_seconds ?? 0.6}
                onChange={(e) =>
                  update({
                    pause_seconds: Math.max(0, Number(e.target.value) || 0)
                  })
                }
              />
              <span className='text-[11px] text-muted-foreground'>
                {t('secondsUnit')}
              </span>
            </div>
            <p className='mt-1 text-[10px] text-muted-foreground'>
              {t('pauseHint')}
            </p>
          </StepPanelField>
        </div>
      </StepPanelSection>

      <StepPanelSection title={t('gestureSectionTitle')}>
        <StepPanelHint>{t('gestureHint')}</StepPanelHint>
        <div
          className={cn(
            'rounded-md border px-3 py-2 text-[11px]',
            swipeDown
              ? 'border-primary/25 bg-primary/[0.04] text-foreground'
              : 'border-amber-500/30 bg-amber-500/[0.06] text-amber-950 dark:text-amber-100'
          )}
        >
          {swipeDown ? t('directionDownOk') : t('directionWarning')}
        </div>
        <div className='grid grid-cols-2 gap-3'>
          <StepPanelField label={t('startYLabel')}>
            <Input
              type='number'
              min={0}
              max={1}
              step={0.01}
              className='h-9 text-xs'
              value={startY}
              onChange={(e) =>
                update({ start_y_ratio: Number(e.target.value) || 0 })
              }
            />
            <p className='mt-1 text-[10px] text-muted-foreground'>
              {t('startYHint')}
            </p>
          </StepPanelField>
          <StepPanelField label={t('endYLabel')}>
            <Input
              type='number'
              min={0}
              max={1}
              step={0.01}
              className='h-9 text-xs'
              value={endY}
              onChange={(e) =>
                update({ end_y_ratio: Number(e.target.value) || 0 })
              }
            />
            <p className='mt-1 text-[10px] text-muted-foreground'>
              {t('endYHint')}
            </p>
          </StepPanelField>
        </div>
      </StepPanelSection>

      <StepPanelSection title={t('anchorSectionTitle')}>
        <p className='text-[11px] leading-relaxed text-muted-foreground'>
          {t('anchorHint', { varToken: SCENARIO_VAR_TOKENS.SCROLL_X_RATIO })}
        </p>
        <div className='flex flex-wrap gap-1.5'>
          {X_PRESETS.map((p) => (
            <Button
              key={p.id}
              type='button'
              size='sm'
              variant={activeXPreset(step) === p.id ? 'default' : 'outline'}
              className='h-7 text-[10px]'
              onClick={() => update({ start_x_ratio: p.value })}
            >
              {t(`xPreset.${p.id}`)}
            </Button>
          ))}
        </div>
        <StepPanelField label={t('startXCustomLabel')}>
          <Input
            className='h-9 font-mono text-xs'
            placeholder={t('startXRatioPlaceholder', {
              varToken: SCENARIO_VAR_TOKENS.SCROLL_X_RATIO
            })}
            value={xRatioDisplay(step)}
            onChange={(e) => {
              const parsed = parseXRatio(e.target.value);
              if (parsed === undefined) {
                const { start_x_ratio: _removed, ...rest } = step;
                update(rest as Partial<FlowStep>);
                return;
              }
              update({ start_x_ratio: parsed } as Partial<FlowStep>);
            }}
          />
          {availableVariables.length > 0 ? (
            <div className='mt-1.5'>
              <VariableInsertMenu
                groups={[
                  {
                    label: tStep('variableInsert.availableVariables'),
                    items: availableVariables.map((name) => {
                      const token = `\${${name}}`;
                      return { value: token };
                    })
                  }
                ]}
                label={tStep('variableInsert.placeholder')}
                onInsert={(token) =>
                  update({ start_x_ratio: token } as Partial<FlowStep>)
                }
                fullWidth
                align='start'
              />
            </div>
          ) : null}
        </StepPanelField>
      </StepPanelSection>

      <StepPanelSection title={t('speedSectionTitle')}>
        <StepPanelField label={t('durationMsLabel')}>
          <div className='flex items-center gap-2'>
            <Input
              type='number'
              min={50}
              max={3000}
              step={10}
              className='h-9 w-28 text-xs'
              value={step.duration_ms ?? 520}
              onChange={(e) =>
                update({
                  duration_ms: Math.max(50, Number(e.target.value) || 520)
                })
              }
            />
            <span className='text-[11px] text-muted-foreground'>ms</span>
          </div>
          <p className='mt-1 text-[10px] text-muted-foreground'>
            {t('durationHint')}
          </p>
        </StepPanelField>
      </StepPanelSection>
    </div>
  );
}
