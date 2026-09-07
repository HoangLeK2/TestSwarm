'use client';

import { useEffect, useState } from 'react';
import { ChevronDown, Crosshair, MousePointerClick } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import {
  VariableInsertMenu,
  type VariableInsertMenuGroup
} from '@/components/variable-insert-menu';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StepPanelInput } from './step-panel-primitives';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { SCENARIO_VAR_TOKENS } from '../../i18n/scenario-var-tokens';
import type { FlowStep } from '../scenario-steps/types';
import {
  StepPanelField,
  StepPanelHint,
  StepPanelSection,
  StepPanelToggle
} from './step-panel-primitives';

const SELECTOR_BY_OPTIONS = [
  'text',
  'resource-id',
  'xpath',
  'class name',
  'description',
  'descriptionContains',
  'descriptionStartsWith'
] as const;

/** Legacy alias; normalized to `description` in the UI. */
const DESCRIPTION_SELECTOR_BYS = new Set([
  'description',
  'descriptionContains',
  'descriptionStartsWith',
  'descriptionStartswith',
  'content-desc'
]);

function normalizeSelectorByForUi(
  by: string
): (typeof SELECTOR_BY_OPTIONS)[number] {
  if (by === 'content-desc') return 'description';
  if (by === 'descriptionStartswith') return 'descriptionStartsWith';
  if ((SELECTOR_BY_OPTIONS as readonly string[]).includes(by)) {
    return by as (typeof SELECTOR_BY_OPTIONS)[number];
  }
  return 'text';
}

function valueInsertRowClassName() {
  return 'flex min-w-0 gap-2';
}

function insertToken(raw: string, token: string): string {
  const current = raw ?? '';
  if (!current.trim()) return token;
  const m = current.match(/\$\{[^}]+\}/g);
  const existingTokens: string[] = m ? [...m] : [];
  if (existingTokens.includes(token)) return current;
  return `${current} ${token}`.trim();
}

export type SelectorPatch = {
  by?: string;
  value?: string;
  /** Pass `null` to remove conditions entirely. */
  conditions?: Record<string, unknown> | null;
  /** Pass `null` to remove instance. */
  instance?: number | null;
  /** Pass `null` to remove chain. */
  chain?: Record<string, unknown> | null;
};

export function patchSelector(step: FlowStep, patch: SelectorPatch): FlowStep {
  const cur =
    (
      step as {
        selector?: {
          by?: string;
          value?: string;
          conditions?: Record<string, unknown>;
          instance?: number;
          chain?: Record<string, unknown>;
        };
      }
    ).selector ?? {};
  const by = patch.by ?? cur.by ?? (step as { by?: string }).by ?? 'text';
  const value =
    patch.value ?? cur.value ?? (step as { value?: string }).value ?? '';
  const selector: Record<string, unknown> = { ...cur, by, value };
  if ('conditions' in patch) {
    const c = patch.conditions;
    if (c && Object.keys(c).length > 0) {
      selector.conditions = c;
    } else {
      delete selector.conditions;
    }
  }
  if ('instance' in patch) {
    if (patch.instance != null) selector.instance = patch.instance;
    else delete selector.instance;
  }
  if ('chain' in patch) {
    if (patch.chain) selector.chain = patch.chain;
    else delete selector.chain;
  }
  return { ...step, selector, by, value } as FlowStep;
}

function VariableInsertSelect({
  availableVariables,
  onInsert,
  t
}: {
  availableVariables: string[];
  onInsert: (token: string) => void;
  t: ReturnType<typeof useTranslations<'campaignsFeature.stepEditor'>>;
}) {
  const groups: VariableInsertMenuGroup[] = [
    {
      label: t('variableInsert.availableVariables'),
      items: availableVariables.map((name) => {
        const token = `\${${name}}`;
        return { value: token };
      })
    }
  ];

  return (
    <VariableInsertMenu
      groups={groups}
      label={t('variableInsert.placeholder')}
      onInsert={onInsert}
      align='end'
      triggerClassName='h-9 w-auto shrink-0 px-2 text-[11px]'
    />
  );
}

const SELECTOR_BY_I18N_KEY: Record<
  (typeof SELECTOR_BY_OPTIONS)[number],
  string
> = {
  text: 'byOptions.text',
  'resource-id': 'byOptions.resource_id',
  xpath: 'byOptions.xpath',
  'class name': 'byOptions.class_name',
  description: 'byOptions.description',
  descriptionContains: 'byOptions.descriptionContains',
  descriptionStartsWith: 'byOptions.descriptionStartsWith'
};

function SelectorBySelect({
  value,
  onChange,
  tSel
}: {
  value: string;
  onChange: (by: string) => void;
  tSel: ReturnType<
    typeof useTranslations<'campaignsFeature.stepEditor.selector'>
  >;
}) {
  const uiValue = normalizeSelectorByForUi(value);
  return (
    <select
      className='w-full rounded-md border border-input bg-background px-2 py-2 text-xs'
      value={uiValue}
      onChange={(e) => onChange(e.target.value)}
    >
      {SELECTOR_BY_OPTIONS.map((o) => (
        <option key={o} value={o}>
          {tSel(
            SELECTOR_BY_I18N_KEY[o] as
              | 'byOptions.text'
              | 'byOptions.resource_id'
          )}
        </option>
      ))}
    </select>
  );
}

const KNOWN_PACKAGES: Record<string, string> = {
  'com.facebook.katana': 'Facebook',
  'com.facebook.lite': 'Facebook Lite',
  'com.android.chrome': 'Chrome',
  'com.google.android.youtube': 'YouTube',
  'com.zhiliaoapp.musically': 'TikTok',
  'com.ss.android.ugc.trill': 'TikTok'
};

function shortWidgetName(className: string): string {
  const raw = className.trim();
  if (!raw) return '';
  const parts = raw.split('.');
  return parts[parts.length - 1] || raw;
}

function friendlyPackageName(packageName: string): string {
  const pkg = packageName.trim();
  if (!pkg) return '';
  return (
    KNOWN_PACKAGES[pkg] ??
    pkg
      .replace(/^com\./, '')
      .split('.')
      .join(' · ')
  );
}

function chainTargetLabel(target: Record<string, unknown>): string {
  const cn = String(target.className ?? target.class ?? '').trim();
  if (cn) return shortWidgetName(cn);
  const text = String(target.text ?? target.value ?? '').trim();
  if (text) return `«${text}»`;
  const rid = String(target.resourceId ?? target['resource-id'] ?? '').trim();
  if (rid) return rid.split('/').pop() ?? rid;
  return '…';
}

function describeChain(
  chain: Record<string, unknown>,
  tSel: ReturnType<
    typeof useTranslations<'campaignsFeature.stepEditor.selector'>
  >
): string {
  const op = String(chain.op ?? '').trim();
  const target = (chain.target ?? {}) as Record<string, unknown>;
  const targetLabel = chainTargetLabel(target);

  if (op === 'child') {
    return tSel('chainSummaryChild', { target: targetLabel });
  }
  if (op === 'sibling') {
    return tSel('chainSummarySibling', { target: targetLabel });
  }
  if (op === 'relative') {
    const dir = String(chain.direction ?? 'right').toLowerCase();
    const dirKey =
      dir === 'left'
        ? 'chainDirectionLeft'
        : dir === 'up'
          ? 'chainDirectionUp'
          : dir === 'down'
            ? 'chainDirectionDown'
            : 'chainDirectionRight';
    return tSel('chainSummaryRelative', {
      direction: tSel(dirKey),
      target: targetLabel
    });
  }
  if (op === 'child_by_text') {
    return tSel('chainSummaryChildByText', {
      text: String(chain.text ?? '')
    });
  }
  if (op === 'child_by_description') {
    return tSel('chainSummaryChildByDesc', {
      text: String(chain.description ?? '')
    });
  }
  return op || 'chain';
}

const INSTANCE_OPTIONS = [
  { value: '', labelKey: 'duplicatePickAuto' as const },
  { value: '0', labelKey: 'duplicatePickFirst' as const },
  { value: '1', labelKey: 'duplicatePickSecond' as const },
  { value: '2', labelKey: 'duplicatePickThird' as const },
  { value: '3', labelKey: 'duplicatePickFourth' as const },
  { value: '4', labelKey: 'duplicatePickFifth' as const }
];

function SelectorAdvancedBlock({
  className,
  packageName,
  instance,
  chain,
  onPatchConditions,
  onInstanceChange,
  onChainChange,
  onClearAll,
  tSel
}: {
  className: string;
  packageName: string;
  instance: number | undefined;
  chain: Record<string, unknown> | undefined;
  onPatchConditions: (patch: Record<string, unknown>) => void;
  onInstanceChange: (instance: number | undefined) => void;
  onChainChange: (chain: Record<string, unknown> | undefined) => void;
  onClearAll: () => void;
  tSel: ReturnType<
    typeof useTranslations<'campaignsFeature.stepEditor.selector'>
  >;
}) {
  const [open, setOpen] = useState(false);
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const [chainJsonOpen, setChainJsonOpen] = useState(false);
  const [chainJson, setChainJson] = useState('');

  const hasChain = !!chain && Object.keys(chain).length > 0;
  const advancedCount =
    (className.trim() ? 1 : 0) +
    (packageName.trim() ? 1 : 0) +
    (instance != null ? 1 : 0) +
    (hasChain ? 1 : 0);

  const instanceValue =
    instance == null ? '' : String(Math.min(4, Math.max(0, instance)));

  const summaryLines: string[] = [];
  if (className.trim()) {
    summaryLines.push(
      tSel('summaryWidget', { name: shortWidgetName(className) })
    );
  }
  if (packageName.trim()) {
    summaryLines.push(
      tSel('summaryApp', { name: friendlyPackageName(packageName) })
    );
  }
  if (instance != null) {
    const opt = INSTANCE_OPTIONS.find((o) => o.value === instanceValue);
    summaryLines.push(
      tSel('summaryInstance', {
        label: opt ? tSel(opt.labelKey) : `#${instance + 1}`
      })
    );
  }
  if (hasChain && chain) {
    summaryLines.push(
      tSel('summaryChain', { desc: describeChain(chain, tSel) })
    );
  }

  useEffect(() => {
    if (!chainJsonOpen) return;
    setChainJson(
      hasChain
        ? JSON.stringify({ chain }, null, 2)
        : '{\n  "chain": {\n    "op": "child",\n    "target": { "className": "android.widget.Switch" }\n  }\n}'
    );
  }, [chainJsonOpen, chain, hasChain]);

  const applyChainJson = () => {
    try {
      const parsed = JSON.parse(chainJson) as Record<string, unknown>;
      const next =
        (parsed.chain as Record<string, unknown> | undefined) ??
        (parsed.op ? parsed : undefined);
      if (!next?.op) {
        toast.error(tSel('chainInvalid'));
        return;
      }
      onChainChange(next);
      setChainJsonOpen(false);
    } catch {
      toast.error(tSel('chainInvalid'));
    }
  };

  return (
    <div className='rounded-lg border border-dashed border-border/70 bg-muted/10'>
      <button
        type='button'
        className='flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left'
        onClick={() => setOpen((v) => !v)}
      >
        <span className='text-xs font-medium text-foreground'>
          {tSel('advancedTitle')}
        </span>
        <span className='flex items-center gap-1.5'>
          {advancedCount > 0 ? (
            <Badge variant='secondary' className='h-5 px-1.5 text-[10px]'>
              {tSel('advancedHasValues', { count: advancedCount })}
            </Badge>
          ) : null}
          <ChevronDown
            size={14}
            className={cn(
              'shrink-0 text-muted-foreground transition-transform',
              open && 'rotate-180'
            )}
          />
        </span>
      </button>

      {open ? (
        <div className='space-y-3 border-t border-border/60 px-3 pb-3 pt-2'>
          <StepPanelHint>{tSel('advancedIntro')}</StepPanelHint>

          {summaryLines.length > 0 ? (
            <div className='space-y-2 rounded-md border border-border/50 bg-background/80 p-2.5'>
              <div className='flex items-center justify-between gap-2'>
                <span className='text-[11px] font-semibold text-foreground'>
                  {tSel('advancedSummaryTitle')}
                </span>
                <Button
                  type='button'
                  variant='ghost'
                  size='sm'
                  className='h-6 px-2 text-[10px] text-muted-foreground'
                  onClick={onClearAll}
                >
                  {tSel('advancedClearAll')}
                </Button>
              </div>
              <ul className='space-y-1 text-[11px] leading-relaxed text-muted-foreground'>
                {summaryLines.map((line) => (
                  <li key={line} className='flex gap-1.5'>
                    <span className='text-primary'>•</span>
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <StepPanelField label={tSel('duplicatePickLabel')}>
            <select
              className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
              value={instanceValue}
              onChange={(e) => {
                const v = e.target.value;
                onInstanceChange(
                  v === '' ? undefined : Math.max(0, parseInt(v, 10) || 0)
                );
              }}
            >
              {INSTANCE_OPTIONS.map((o) => (
                <option key={o.value || 'auto'} value={o.value}>
                  {tSel(o.labelKey)}
                </option>
              ))}
            </select>
          </StepPanelField>

          <div className='rounded-md border border-border/40'>
            <button
              type='button'
              className='flex w-full items-center justify-between px-2.5 py-2 text-left text-[11px] font-medium text-muted-foreground'
              onClick={() => setTechnicalOpen((v) => !v)}
            >
              <span>{tSel('technicalDetailsTitle')}</span>
              <ChevronDown
                size={12}
                className={cn(
                  'transition-transform',
                  technicalOpen && 'rotate-180'
                )}
              />
            </button>
            {technicalOpen ? (
              <div className='space-y-3 border-t border-border/40 px-2.5 pb-2.5 pt-2'>
                <p className='text-[10px] text-muted-foreground'>
                  {tSel('technicalDetailsHint')}
                </p>
                <StepPanelField label={tSel('classNameLabel')}>
                  <Input
                    className='h-9 font-mono text-xs'
                    value={className}
                    onChange={(e) =>
                      onPatchConditions({ className: e.target.value.trim() })
                    }
                    placeholder={tSel('classNamePlaceholder')}
                  />
                </StepPanelField>
                <StepPanelField label={tSel('packageNameLabel')}>
                  <Input
                    className='h-9 font-mono text-xs'
                    value={packageName}
                    onChange={(e) =>
                      onPatchConditions({
                        packageName: e.target.value.trim()
                      })
                    }
                    placeholder={tSel('packageNamePlaceholder')}
                  />
                </StepPanelField>
              </div>
            ) : null}
          </div>

          {hasChain || chainJsonOpen ? (
            <div className='space-y-2 rounded-md border border-amber-500/20 bg-amber-500/[0.04] p-2.5'>
              <p className='text-[11px] font-semibold text-foreground'>
                {tSel('chainBlockTitle')}
              </p>
              <p className='text-[10px] leading-relaxed text-muted-foreground'>
                {tSel('chainBlockHint')}
              </p>
              {hasChain && chain && !chainJsonOpen ? (
                <p className='text-[11px] text-foreground'>
                  {describeChain(chain, tSel)}
                </p>
              ) : null}
              {chainJsonOpen ? (
                <div className='space-y-2'>
                  <textarea
                    className='min-h-[88px] w-full rounded-md border bg-background p-2 font-mono text-[10px]'
                    value={chainJson}
                    onChange={(e) => setChainJson(e.target.value)}
                  />
                  <div className='flex flex-wrap gap-2'>
                    <Button
                      size='sm'
                      variant='secondary'
                      className='h-7 text-[10px]'
                      onClick={applyChainJson}
                    >
                      {tSel('chainApply')}
                    </Button>
                    <Button
                      size='sm'
                      variant='ghost'
                      className='h-7 text-[10px]'
                      onClick={() => setChainJsonOpen(false)}
                    >
                      {tSel('chainHide')}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className='flex flex-wrap gap-2'>
                  <Button
                    type='button'
                    size='sm'
                    variant='outline'
                    className='h-7 text-[10px]'
                    onClick={() => setChainJsonOpen(true)}
                  >
                    {tSel('chainEditJson')}
                  </Button>
                  {hasChain ? (
                    <Button
                      type='button'
                      size='sm'
                      variant='ghost'
                      className='h-7 text-[10px] text-destructive'
                      onClick={() => onChainChange(undefined)}
                    >
                      {tSel('chainRemove')}
                    </Button>
                  ) : null}
                </div>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function FallbackRatioFields({
  rx,
  ry,
  onRxChange,
  onRyChange,
  onRequestPick,
  tSel
}: {
  rx: number;
  ry: number;
  onRxChange: (n: number) => void;
  onRyChange: (n: number) => void;
  onRequestPick?: () => void;
  tSel: ReturnType<
    typeof useTranslations<'campaignsFeature.stepEditor.selector'>
  >;
}) {
  return (
    <StepPanelSection
      title={tSel('fallbackTitle')}
      badge={
        onRequestPick ? (
          <Button
            size='sm'
            variant='outline'
            className='h-7 gap-1 px-2 text-[10px]'
            onClick={onRequestPick}
          >
            <MousePointerClick size={10} />
            {tSel('pickFallbackCoords')}
          </Button>
        ) : undefined
      }
    >
      <StepPanelHint>{tSel('fallbackHint')}</StepPanelHint>
      <div className='grid grid-cols-2 gap-3'>
        <StepPanelField label={tSel('fallbackX')}>
          <Input
            type='number'
            min={0}
            max={1}
            step={0.01}
            className='h-9 text-xs'
            value={rx}
            onChange={(e) => onRxChange(parseFloat(e.target.value) || 0)}
          />
        </StepPanelField>
        <StepPanelField label={tSel('fallbackY')}>
          <Input
            type='number'
            min={0}
            max={1}
            step={0.01}
            className='h-9 text-xs'
            value={ry}
            onChange={(e) => onRyChange(parseFloat(e.target.value) || 0)}
          />
        </StepPanelField>
      </div>
    </StepPanelSection>
  );
}

export function SelectorFields({
  step,
  onChange,
  onRequestPickSelector,
  availableVariables,
  t
}: {
  step: FlowStep;
  onChange: (s: FlowStep) => void;
  onRequestPickSelector?: () => void;
  availableVariables: string[];
  t: ReturnType<typeof useTranslations<'campaignsFeature.stepEditor'>>;
}) {
  const tSel = useTranslations('campaignsFeature.stepEditor.selector');
  const sel = (
    step as {
      selector?: {
        by?: string;
        value?: string;
        conditions?: Record<string, unknown>;
        instance?: number;
        chain?: Record<string, unknown>;
      };
    }
  ).selector;
  const by = sel?.by ?? (step as { by?: string }).by ?? 'text';
  const value = sel?.value ?? (step as { value?: string }).value ?? '';
  const conditions = (sel?.conditions ?? {}) as Record<string, unknown>;
  const className = String(conditions.className ?? '');
  const packageName = String(conditions.packageName ?? '');
  const clickable =
    conditions.clickable === true || conditions.clickable === 'true';

  const patchConditions = (patch: Record<string, unknown>) => {
    const next = { ...conditions };
    for (const [k, v] of Object.entries(patch)) {
      if (v === '' || v === false || v == null) delete next[k];
      else next[k] = v;
    }
    onChange(
      patchSelector(step, {
        conditions: Object.keys(next).length > 0 ? next : undefined
      })
    );
  };

  return (
    <StepPanelSection
      title={tSel('sectionTitle')}
      badge={
        onRequestPickSelector ? (
          <Button
            size='sm'
            variant='outline'
            className='h-7 gap-1 border-amber-400/50 px-2 text-[10px] text-amber-800 hover:bg-amber-50 dark:text-amber-300 dark:hover:bg-amber-950/30'
            onClick={onRequestPickSelector}
          >
            <Crosshair size={10} />
            {tSel('pickFromScreen')}
          </Button>
        ) : undefined
      }
    >
      <StepPanelField label={tSel('byLabel')}>
        <SelectorBySelect
          value={by}
          onChange={(nextBy) => onChange(patchSelector(step, { by: nextBy }))}
          tSel={tSel}
        />
      </StepPanelField>

      <StepPanelField label={tSel('valueLabel')}>
        <div className={valueInsertRowClassName()}>
          <StepPanelInput
            className='h-9 min-w-0 flex-1 text-xs'
            value={value}
            onValueCommit={(nextValue) =>
              onChange(patchSelector(step, { value: nextValue }))
            }
            placeholder={tSel('valuePlaceholder', {
              varToken: SCENARIO_VAR_TOKENS.VAR
            })}
          />
          <VariableInsertSelect
            availableVariables={availableVariables}
            t={t}
            onInsert={(token) =>
              onChange(
                patchSelector(step, { value: insertToken(value, token) })
              )
            }
          />
        </div>
      </StepPanelField>

      <StepPanelToggle
        label={tSel('clickableLabel')}
        description={tSel('clickableDescription')}
        checked={clickable}
        onCheckedChange={(checked) =>
          patchConditions({ clickable: checked ? true : undefined })
        }
      />

      <SelectorAdvancedBlock
        className={className}
        packageName={packageName}
        instance={sel?.instance}
        chain={sel?.chain}
        onPatchConditions={patchConditions}
        onInstanceChange={(instance) =>
          onChange(patchSelector(step, { instance }))
        }
        onChainChange={(chain) => onChange(patchSelector(step, { chain }))}
        onClearAll={() => {
          const nextConditions = { ...conditions };
          delete nextConditions.className;
          delete nextConditions.packageName;
          delete nextConditions.resourceId;
          onChange(
            patchSelector(step, {
              conditions:
                Object.keys(nextConditions).length > 0 ? nextConditions : null,
              instance: null,
              chain: null
            })
          );
        }}
        tSel={tSel}
      />
    </StepPanelSection>
  );
}
