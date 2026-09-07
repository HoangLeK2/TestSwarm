'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Crop as CropIcon,
  AlertTriangle,
  CheckCircle2,
  Monitor,
  MousePointerClick,
  Move,
  ShieldCheck,
  Info
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import {
  VariableInsertMenu,
  type VariableInsertMenuGroup,
  type VariableInsertMenuItem
} from '@/components/variable-insert-menu';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { getVariableDisplayMetadata } from '@/lib/variable-display-metadata';
import type { VariableDisplayMetadata } from '@/lib/variable-display-metadata';
import { cn } from '@/lib/utils';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  LoopConfigFields,
  RepeatUntilFields
} from '../scenario-steps/control-flow-editors';
import {
  RunScenarioFields,
  type RunScenarioCampaignOption
} from '../scenario-steps/run-scenario-editor';
import { type FlowStep } from '../scenario-steps/types';
import { SCENARIO_VAR_TOKENS } from '../../i18n/scenario-var-tokens';
import { ExtractStepFields } from './extract-fields';
import { AppAutomationStepFields } from './app-automation-fields';
import { ScrollDownStepFields } from './scroll-down-fields';
import { FallbackRatioFields, SelectorFields } from './selector-fields';
import { PlatformSelect } from './platform-select';
import { usePlatformCapabilities } from '../../hooks/use-platform-capabilities';
import { SessionGateAccountBinder } from './session-gate-account-binder';
import { PLATFORM_AWARE_STEP_TYPES } from './platform-aware-steps';
import {
  normalizeSystemVariableCondition,
  PLATFORM_SESSION_READY_VARIABLE
} from './system-variable-condition';
import {
  AppLifecycleStepFields,
  F,
  StepErrorPolicySection,
  StepPanelField,
  StepPanelHeader,
  StepPanelHint,
  StepPanelMetaFields,
  StepPanelSection,
  StepPanelTextarea,
  StepPanelToggle,
  StepRetryPolicySection
} from './step-panel-primitives';
import {
  defaultSocialAction,
  getSocialActionOptions
} from './social-action-options';
import { TapImageFields } from './tap-image-fields';
import { VerifyScreenFields } from './verify-screen-fields';
import type { VariablePreviewValues } from './variable-preview';
import {
  evaluateNodeCapabilityStatus,
  nodeCapabilityBadgeLabel,
  type DeviceCapabilityMap,
  type NodeCapabilityRegistry,
  type NodeCapabilityStatus
} from '../../lib/node-capabilities';
import {
  analyzeStepConfiguration,
  type StepConfigurationStatus
} from '../../lib/step-configuration-status';
import type {
  StepVariableLineage,
  StepVariableLineageIssue
} from '../../lib/step-variable-lineage';
import { scenarioLintIssueSeverity } from '../../lib/scenario-lint-preflight';
import {
  stepVariableLineageQuickFixes,
  type StepVariableLineageQuickFix
} from '../../lib/step-variable-lineage-quick-fix';

type SetupTabValue = 'action' | 'screen' | 'data-save' | 'settings';

interface Props {
  step: FlowStep;
  onChange: (step: FlowStep) => void;
  onClose: () => void;
  availableVariables?: string[];
  /** Called when user wants to pick a selector from the device screen/tree. Should close the panel first. */
  onRequestPickSelector?: () => void;
  /** Pick single tap ratios on mirror (tap_ratio / tap fallback). */
  onRequestPickTapCoords?: () => void;
  /** Pick swipe segment on mirror (swipe_ratio). */
  onRequestPickSwipeCoords?: () => void;
  /**
   * Crop a region of the mirror as a tap_image template. Resolves with the
   * stored key plus the screen size it was cropped at — matching needs that to
   * correct for phones with a different resolution.
   */
  onRequestCropImage?: () => Promise<{
    templateKey: string;
    screenW?: number;
    screenH?: number;
    preview: string;
    warning: string;
  } | null>;
  /**
   * Drag a rectangle on the mirror to bound an OCR read. Like the pickers
   * above it closes the panel first, so the caller applies the result itself.
   */
  onRequestPickRegion?: () => Promise<null>;
  /** Other scenarios in the campaign — for run_scenario picker (templates always loaded inside RunScenarioFields). */
  campaignScenarios?: RunScenarioCampaignOption[];
  runtimeContext?: SessionGateRuntimeContext;
  variablePreviewValues?: VariablePreviewValues;
  /** Backend scenario schema registry keyed by step type. */
  nodeCapabilities?: NodeCapabilityRegistry;
  /** Runtime facts for the currently previewed phone. Unknown keys stay informational. */
  deviceCapabilities?: DeviceCapabilityMap;
  /** Static variable read/write analysis for this step in the smart step tree. */
  variableLineage?: StepVariableLineage;
  /** Insert a support step immediately before the currently edited step. */
  onInsertStepBefore?: (step: FlowStep) => void;
  /** Select another step from the same smart step tree by lineage path key. */
  onSelectVariableLineagePathKey?: (pathKey: string) => void;
}

export type SessionGateRuntimeContext = {
  deviceLabel: string;
  /** Phone the editor previews against — lets the panel bind an account to it. */
  deviceId?: string | null;
  platform: string | null;
  accountLabel: string | null;
  sessionState: string | null;
  loading?: boolean;
  error?: boolean;
};

/**
 * OCR read area: whole screen, or a rectangle dragged on the device mirror.
 *
 * The raw JSON textarea stays as the escape hatch — a scenario may carry a
 * region computed elsewhere, and hand-typing ratios must keep working — but
 * nobody should have to guess four numbers when the phone is on screen.
 */
function OcrRegionField({
  region,
  onChange,
  onRequestPickRegion
}: {
  region: unknown;
  onChange: (next: unknown | undefined) => void;
  onRequestPickRegion?: () => Promise<null>;
}) {
  const tOcr = useTranslations('campaignsFeature.stepEditor.ocr');
  const rect = region as
    | { x1?: number; y1?: number; x2?: number; y2?: number }
    | undefined;
  const hasRegion =
    rect != null &&
    typeof rect === 'object' &&
    ['x1', 'y1', 'x2', 'y2'].every(
      (k) => typeof (rect as never)[k] === 'number'
    );
  const pct = (v: number | undefined) => `${Math.round((v ?? 0) * 100)}%`;

  return (
    <div className='space-y-2'>
      <div className='grid grid-cols-2 gap-2'>
        <Button
          type='button'
          size='sm'
          variant={hasRegion ? 'outline' : 'secondary'}
          className='h-7 gap-1.5 text-[10px]'
          onClick={() => onChange(undefined)}
        >
          <Monitor size={12} />
          {tOcr('wholeScreen')}
        </Button>
        <Button
          type='button'
          size='sm'
          variant={hasRegion ? 'secondary' : 'outline'}
          className='h-7 gap-1.5 text-[10px]'
          disabled={!onRequestPickRegion}
          title={
            onRequestPickRegion ? undefined : tOcr('pickRegionUnavailable')
          }
          onClick={() => {
            void onRequestPickRegion?.();
          }}
        >
          <CropIcon size={12} />
          {hasRegion ? tOcr('pickRegionAgain') : tOcr('pickRegion')}
        </Button>
      </div>

      <p className='text-[10px] text-muted-foreground'>
        {hasRegion
          ? tOcr('regionSummary', {
              x1: pct(rect?.x1),
              y1: pct(rect?.y1),
              x2: pct(rect?.x2),
              y2: pct(rect?.y2)
            })
          : tOcr('wholeScreenHint')}
      </p>

      <JsonTextarea
        label={tOcr('region')}
        value={region}
        onCommit={onChange}
        placeholder='{"x1":0,"y1":0.3,"x2":1,"y2":0.7}'
      />
    </div>
  );
}

function translateVariableInfo(
  t: (key: string) => string,
  key: string | undefined,
  fallback: string
) {
  if (!key) return fallback;
  try {
    const translated = t(key);
    return translated && translated !== key ? translated : fallback;
  } catch {
    return fallback;
  }
}

function variableCategoryLabel(
  metadata: VariableDisplayMetadata,
  t: (key: string) => string
) {
  return translateVariableInfo(
    t,
    `variableInfo.categories.${metadata.category}`,
    metadata.category
  );
}

function useVariableInfoTranslator() {
  const tVarInfo = useTranslations('components.variableEditor');
  return useCallback((key: string) => tVarInfo(key as never), [tVarInfo]);
}

function variableNameFromToken(token: string): string {
  const match = token.match(/^\$\{(.+)\}$/);
  return match ? match[1] : token;
}

function buildVariableMenuItem({
  name,
  value,
  code,
  t
}: {
  name: string;
  value: string;
  code: string;
  t: (key: string) => string;
}): VariableInsertMenuItem {
  const metadata = getVariableDisplayMetadata(name);
  const label = translateVariableInfo(
    t,
    metadata.labelKey,
    metadata.fallbackLabel
  );
  const description = translateVariableInfo(t, metadata.descriptionKey, '');
  const origin = translateVariableInfo(t, metadata.originKey, '');
  const originLabel = translateVariableInfo(
    t,
    'variableInfo.originLabel',
    'Nguồn'
  );

  return {
    value,
    label,
    code,
    badge: variableCategoryLabel(metadata, t),
    description,
    detail: origin ? `${originLabel}: ${origin}` : undefined
  };
}

function IfVariableSourceHint({
  name,
  t
}: {
  name?: string | null;
  t: (key: string) => string;
}) {
  const trimmed = String(name ?? '').trim();
  if (!trimmed) return null;
  const metadata = getVariableDisplayMetadata(trimmed);
  const label = translateVariableInfo(
    t,
    metadata.labelKey,
    metadata.fallbackLabel
  );
  const description = translateVariableInfo(t, metadata.descriptionKey, '');
  const origin = translateVariableInfo(t, metadata.originKey, '');

  if (!description && !origin) return null;

  return (
    <div className='rounded-md border bg-muted/25 px-2.5 py-2 text-[11px] leading-relaxed'>
      <div className='flex min-w-0 flex-wrap items-center gap-1.5'>
        <Info className='size-3.5 shrink-0 text-muted-foreground' />
        <span className='min-w-0 truncate font-medium text-foreground'>
          {label}
        </span>
        <span className='rounded border bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground'>
          {variableCategoryLabel(metadata, t)}
        </span>
      </div>
      {origin ? (
        <p className='mt-1 text-muted-foreground'>
          <span className='font-medium text-foreground'>
            {t('variableInfo.originLabel')}:
          </span>{' '}
          {origin}
        </p>
      ) : null}
      {description ? (
        <p className='mt-1 text-muted-foreground'>{description}</p>
      ) : null}
    </div>
  );
}

/** Value field + variable insert: keep stacked inside narrow editor panels. */
function valueInsertRowClassName() {
  return 'flex min-w-0 flex-col gap-2';
}

function keywordInputValue(value: unknown): string {
  return Array.isArray(value) ? value.join(', ') : String(value ?? '');
}

function keywordListFromInput(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function JsonTextarea({
  label,
  value,
  onCommit,
  placeholder
}: {
  label: string;
  value: unknown;
  onCommit: (next: unknown | undefined) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(
    value == null ? '' : JSON.stringify(value, null, 2)
  );

  useEffect(() => {
    setDraft(value == null ? '' : JSON.stringify(value, null, 2));
  }, [value]);

  return (
    <F label={label}>
      <textarea
        className='min-h-[92px] w-full rounded border bg-background px-2 py-1.5 font-mono text-xs'
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const trimmed = draft.trim();
          if (!trimmed) return onCommit(undefined);
          try {
            onCommit(JSON.parse(trimmed));
          } catch {
            // keep draft while invalid JSON
          }
        }}
      />
    </F>
  );
}

const BUILTIN_VARIABLE_TOKENS = [
  '${__NOW__}',
  '${__DATE__}',
  '${__TIME__}',
  '${__DEVICE_SERIAL__}',
  '${__DEVICE_MODEL__}',
  '${__RANDOM_INT_1_100__}',
  '${__RANDOM_UUID__}',
  '${__STEP_INDEX__}',
  '${__LOOP_INDEX__}',
  // Account rotation — injected when the scenario is bound to an account group.
  // Password is resolved at Temporal runtime from __ACCOUNT_ID__ so plaintext
  // never lands in the workflow event history.
  '${__ACCOUNT_ID__}',
  '${__ACCOUNT_USERNAME__}',
  '${__ACCOUNT_PASSWORD__}',
  '${__ACCOUNT_DISPLAY_NAME__}',
  '${__ACCOUNT_PLATFORM__}'
] as const;

const SOURCE_POOL_VARIABLE_TOKENS = [
  '${GROUP_NAME}',
  '${GROUP_URL}',
  '${GROUP_SEARCH_QUERY}',
  '${GROUP_SELECTOR_BY}',
  '${GROUP_SELECTOR_VALUE}',
  '${GROUP_FALLBACK_SELECTOR_BY}',
  '${GROUP_FALLBACK_SELECTOR_VALUE}'
] as const;

function insertToken(raw: string, token: string): string {
  const current = raw ?? '';
  if (!current.trim()) return token;
  const m = current.match(/\$\{[^}]+\}/g);
  const existingTokens: string[] = m ? [...m] : [];
  if (existingTokens.includes(token)) return current;
  return `${current} ${token}`.trim();
}

function VariableInsertSelect({
  availableVariables,
  onInsert,
  t
}: {
  availableVariables: string[];
  onInsert: (token: string) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  const variableInfoT = useVariableInfoTranslator();
  const groups: VariableInsertMenuGroup[] = [
    {
      label: t('variableInsert.availableVariables'),
      items: availableVariables.map((name) => {
        const token = `\${${name}}`;
        return buildVariableMenuItem({
          name,
          value: token,
          code: token,
          t: variableInfoT
        });
      })
    },
    {
      label: t('variableInsert.builtinVariables'),
      items: BUILTIN_VARIABLE_TOKENS.map((token) =>
        buildVariableMenuItem({
          name: variableNameFromToken(token),
          value: token,
          code: token,
          t: variableInfoT
        })
      )
    },
    {
      label: t('variableInsert.sourcePoolVariables'),
      items: SOURCE_POOL_VARIABLE_TOKENS.map((token) =>
        buildVariableMenuItem({
          name: variableNameFromToken(token),
          value: token,
          code: token,
          t: variableInfoT
        })
      )
    }
  ];

  return (
    <VariableInsertMenu
      groups={groups}
      label={t('variableInsert.placeholder')}
      onInsert={onInsert}
      align='end'
      triggerClassName='w-full shrink-0'
    />
  );
}

function VariableTextInput({
  availableVariables,
  value,
  onValueChange,
  placeholder,
  className = 'h-8 text-xs',
  insertMode = 'append',
  t
}: {
  availableVariables: string[];
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  insertMode?: 'append' | 'replace';
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div className={valueInsertRowClassName()}>
      <Input
        className={cn('min-w-0 flex-1', className)}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onValueChange(event.target.value)}
      />
      <VariableInsertSelect
        availableVariables={availableVariables}
        t={t}
        onInsert={(token) =>
          onValueChange(
            insertMode === 'replace' ? token : insertToken(value, token)
          )
        }
      />
    </div>
  );
}

function VariableNameSelect({
  availableVariables,
  onSelect
}: {
  availableVariables: string[];
  onSelect: (name: string) => void;
}) {
  const variableInfoT = useVariableInfoTranslator();
  if (availableVariables.length === 0) return null;
  return (
    <VariableInsertMenu
      groups={[
        {
          label: 'Biến có thể dùng',
          items: availableVariables.map((name) =>
            buildVariableMenuItem({
              name,
              value: name,
              code: name,
              t: variableInfoT
            })
          )
        }
      ]}
      label='Chọn biến...'
      onInsert={onSelect}
      align='end'
      className='w-[min(34rem,calc(100vw-2rem))]'
      triggerClassName='w-full shrink-0 sm:w-[13rem]'
    />
  );
}

function VariableTextarea({
  availableVariables,
  value,
  onValueChange,
  placeholder,
  className = 'min-h-[92px] w-full rounded border bg-background px-2 py-1.5 text-xs',
  t
}: {
  availableVariables: string[];
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div className='space-y-2'>
      <textarea
        className={className}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onValueChange(event.target.value)}
      />
      <VariableInsertSelect
        availableVariables={availableVariables}
        t={t}
        onInsert={(token) => onValueChange(insertToken(value, token))}
      />
    </div>
  );
}

/**
 * One fact row in the session-gate summary.
 *
 * An unknown value is the common case while a scenario is still being wired,
 * so it reads as a muted hint rather than as data — the operator can tell at a
 * glance which rows are still missing.
 */
function SessionGateFact({
  label,
  value,
  placeholder
}: {
  label: string;
  value?: string | null;
  placeholder: string;
}) {
  const filled = Boolean(value);
  return (
    <div className='flex items-baseline justify-between gap-3 px-3 py-2'>
      <dt className='shrink-0 text-[11px] text-muted-foreground'>{label}</dt>
      <dd
        className={cn(
          'min-w-0 truncate text-right text-xs',
          filled
            ? 'font-medium text-foreground'
            : 'italic text-muted-foreground'
        )}
        title={value || placeholder}
      >
        {value || placeholder}
      </dd>
    </div>
  );
}

function NodeCapabilitySummary({
  status,
  evidence,
  inspectorHints,
  description,
  t
}: {
  status: NodeCapabilityStatus;
  evidence: string[];
  inspectorHints: string[];
  description?: string;
  t: (key: string, values?: Record<string, unknown>) => string;
}) {
  const blocked = status.missing.length > 0;
  const unknown = !blocked && status.unknown.length > 0;
  const Icon = blocked ? AlertTriangle : unknown ? Info : CheckCircle2;
  const tone = blocked
    ? 'border-destructive/40 bg-destructive/5 text-destructive'
    : unknown
      ? 'border-amber-500/35 bg-amber-50/70 text-amber-800 dark:bg-amber-950/20 dark:text-amber-200'
      : 'border-emerald-500/30 bg-emerald-50/70 text-emerald-800 dark:bg-emerald-950/20 dark:text-emerald-200';
  const title = blocked
    ? t('missingTitle')
    : unknown
      ? t('unknownTitle')
      : t('readyTitle');
  const details = blocked
    ? status.missing
    : unknown
      ? status.unknown
      : status.required;

  return (
    <StepPanelSection
      title={t('sectionTitle')}
      badge={
        <Badge variant='outline' className='h-5 rounded-md px-1.5 text-[10px]'>
          {status.risk}
        </Badge>
      }
      className='space-y-2'
    >
      <div className={cn('rounded-md border px-2.5 py-2', tone)}>
        <div className='flex min-w-0 items-center gap-2'>
          <Icon className='size-3.5 shrink-0' aria-hidden />
          <span className='min-w-0 truncate text-xs font-medium'>{title}</span>
        </div>
        <p className='mt-1 break-words text-[10px] leading-relaxed opacity-90'>
          {nodeCapabilityBadgeLabel(status)}
        </p>
      </div>
      {description ? (
        <p className='text-[11px] leading-relaxed text-muted-foreground'>
          {description}
        </p>
      ) : null}
      {details.length > 0 ? (
        <div className='flex flex-wrap gap-1'>
          {details.map((key) => (
            <Badge
              key={key}
              variant={blocked ? 'destructive' : 'secondary'}
              className='max-w-full rounded-md px-1.5 py-0 text-[10px] font-normal'
              title={key}
            >
              <span className='max-w-[14rem] truncate'>{key}</span>
            </Badge>
          ))}
        </div>
      ) : (
        <p className='text-[10px] text-muted-foreground'>
          {t('noRequirements')}
        </p>
      )}
      {(evidence.length > 0 || inspectorHints.length > 0) && (
        <div className='grid gap-1.5 text-[10px] text-muted-foreground'>
          {evidence.length > 0 && (
            <p>
              <span className='font-medium text-foreground'>
                {t('evidenceLabel')}
              </span>{' '}
              {evidence.join(', ')}
            </p>
          )}
          {inspectorHints.length > 0 && (
            <p>
              <span className='font-medium text-foreground'>
                {t('inspectorLabel')}
              </span>{' '}
              {inspectorHints.join(', ')}
            </p>
          )}
        </div>
      )}
    </StepPanelSection>
  );
}

function StepConfigurationSummary({
  status,
  t
}: {
  status: StepConfigurationStatus;
  t: (key: string, values?: Record<string, unknown>) => string;
}) {
  if (status.state === 'complete') return null;

  const blocked = status.state === 'missing';
  const Icon = blocked ? AlertTriangle : Info;
  const tone = blocked
    ? 'border-destructive/40 bg-destructive/5 text-destructive'
    : 'border-amber-500/35 bg-amber-50/70 text-amber-800 dark:bg-amber-950/20 dark:text-amber-200';
  const title = blocked ? t('missingTitle') : t('warningTitle');

  return (
    <StepPanelSection
      title={t('sectionTitle')}
      badge={
        <Badge variant='outline' className='h-5 rounded-md px-1.5 text-[10px]'>
          {t(blocked ? 'badgeMissing' : 'badgeWarning', {
            count: status.issues.length
          })}
        </Badge>
      }
      className='space-y-2'
    >
      <div className={cn('rounded-md border px-2.5 py-2', tone)}>
        <div className='flex min-w-0 items-center gap-2'>
          <Icon className='size-3.5 shrink-0' aria-hidden />
          <span className='min-w-0 truncate text-xs font-medium'>{title}</span>
        </div>
        <p className='mt-1 break-words text-[10px] leading-relaxed opacity-90'>
          {t(blocked ? 'missingDescription' : 'warningDescription')}
        </p>
      </div>
      <div className='flex flex-wrap gap-1'>
        {status.issues.map((issue) => (
          <Badge
            key={`${issue.code}:${issue.labelKey}:${issue.values?.number ?? ''}`}
            variant={issue.severity === 'missing' ? 'destructive' : 'secondary'}
            className='max-w-full rounded-md px-1.5 py-0 text-[10px] font-normal'
          >
            <span className='max-w-[16rem] truncate'>
              {t(`fields.${issue.labelKey}`, issue.values)}
            </span>
          </Badge>
        ))}
      </div>
    </StepPanelSection>
  );
}

function VariableLineageSummary({
  lineage,
  step,
  availableVariables,
  onApplyQuickFix,
  canInsertStepBefore,
  canSelectProducer,
  t
}: {
  lineage?: StepVariableLineage;
  step: FlowStep;
  availableVariables: string[];
  onApplyQuickFix: (fix: StepVariableLineageQuickFix) => void;
  canInsertStepBefore: boolean;
  canSelectProducer: boolean;
  t: (key: string, values?: Record<string, unknown>) => string;
}) {
  const criticalIssueCount =
    lineage?.issues.filter(
      (issue) => scenarioLintIssueSeverity(issue) === 'critical'
    ).length ?? 0;

  if (
    !lineage ||
    (lineage.references.length === 0 &&
      lineage.produced.length === 0 &&
      lineage.issues.length === 0)
  ) {
    return null;
  }

  return (
    <StepPanelSection
      title={t('sectionTitle')}
      badge={
        lineage.issues.length > 0 ? (
          <Badge
            variant={criticalIssueCount > 0 ? 'destructive' : 'outline'}
            className='h-5 rounded-md px-1.5 text-[10px]'
          >
            {criticalIssueCount > 0
              ? t('badgeCritical', {
                  count: lineage.issues.length,
                  critical: criticalIssueCount
                })
              : t('badgeWarning', { count: lineage.issues.length })}
          </Badge>
        ) : undefined
      }
      className='space-y-2'
    >
      {lineage.issues.length > 0 && (
        <div className='space-y-1.5'>
          {lineage.issues.map((issue) => (
            <VariableLineageIssueRow
              key={`${issue.kind}:${issue.variable}:${issue.source}`}
              issue={issue}
              step={step}
              availableVariables={availableVariables}
              onApplyQuickFix={onApplyQuickFix}
              canInsertStepBefore={canInsertStepBefore}
              canSelectProducer={canSelectProducer}
              t={t}
            />
          ))}
        </div>
      )}
      <VariableNameList
        label={t('referencesLabel')}
        emptyLabel={t('noneReferences')}
        names={lineage.references.map((reference) => reference.name)}
      />
      <VariableNameList
        label={t('producedLabel')}
        emptyLabel={t('noneProduced')}
        names={lineage.produced.map((production) => production.name)}
      />
    </StepPanelSection>
  );
}

function VariableLineageIssueRow({
  issue,
  step,
  availableVariables,
  onApplyQuickFix,
  canInsertStepBefore,
  canSelectProducer,
  t
}: {
  issue: StepVariableLineageIssue;
  step: FlowStep;
  availableVariables: string[];
  onApplyQuickFix: (fix: StepVariableLineageQuickFix) => void;
  canInsertStepBefore: boolean;
  canSelectProducer: boolean;
  t: (key: string, values?: Record<string, unknown>) => string;
}) {
  const critical = scenarioLintIssueSeverity(issue) === 'critical';
  const fixes = stepVariableLineageQuickFixes(
    issue,
    step,
    availableVariables
  ).filter((fix) => {
    if (fix.kind === 'insert_step_before') return canInsertStepBefore;
    if (fix.kind === 'select_producer') return canSelectProducer;
    return true;
  });

  return (
    <div
      className={cn(
        'rounded-md border px-2.5 py-2',
        critical
          ? 'border-destructive/40 bg-destructive/5 text-destructive'
          : 'border-amber-500/35 bg-amber-50/70 text-amber-900 dark:bg-amber-950/20 dark:text-amber-200'
      )}
    >
      <div className='flex min-w-0 items-center gap-2'>
        <AlertTriangle className='size-3.5 shrink-0' aria-hidden />
        <span className='min-w-0 truncate text-xs font-medium'>
          {t(`issues.${issue.kind}`, {
            variable: issue.variable,
            source: issue.source
          })}
        </span>
      </div>
      {issue.producerPathKey ? (
        <div
          className={cn(
            'mt-1 truncate pl-5 text-[10px]',
            critical
              ? 'text-destructive/80'
              : 'text-amber-800/80 dark:text-amber-100/75'
          )}
        >
          {t('producerHint', {
            path: issue.producerPathKey,
            stepType: issue.producerStepType ?? issue.producerPathKey
          })}
        </div>
      ) : null}
      {fixes.length > 0 ? (
        <div className='mt-2 flex min-w-0 flex-wrap gap-1.5 pl-5'>
          {fixes.map((fix) =>
            fix.kind === 'guidance' ? (
              <span
                key={fix.id}
                className={cn(
                  'inline-flex min-w-0 items-center rounded-md bg-background/70 px-2 py-1 text-[10px] leading-snug',
                  critical
                    ? 'text-destructive'
                    : 'text-amber-900 dark:text-amber-100'
                )}
                title={t(fix.descriptionKey)}
              >
                {t(fix.labelKey)}
              </span>
            ) : (
              <Button
                key={fix.id}
                type='button'
                variant='outline'
                size='sm'
                className='h-6 min-w-0 rounded-md px-2 text-[10px]'
                title={t(fix.descriptionKey)}
                onClick={() => onApplyQuickFix(fix)}
              >
                {t(fix.labelKey)}
              </Button>
            )
          )}
        </div>
      ) : null}
    </div>
  );
}

function VariableNameList({
  label,
  emptyLabel,
  names
}: {
  label: string;
  emptyLabel: string;
  names: string[];
}) {
  const uniqueNames = Array.from(new Set(names)).sort((a, b) =>
    a.localeCompare(b)
  );

  return (
    <div className='space-y-1'>
      <p className='text-[10px] font-medium uppercase tracking-wide text-muted-foreground'>
        {label}
      </p>
      {uniqueNames.length > 0 ? (
        <div className='flex flex-wrap gap-1'>
          {uniqueNames.map((name) => (
            <Badge
              key={name}
              variant='secondary'
              className='max-w-full rounded-md px-1.5 py-0 font-mono text-[10px] font-normal'
              title={name}
            >
              <span className='max-w-[14rem] truncate'>{name}</span>
            </Badge>
          ))}
        </div>
      ) : (
        <p className='text-[10px] text-muted-foreground'>{emptyLabel}</p>
      )}
    </div>
  );
}

export function StepDetailPanel({
  step: stepProp,
  onChange,
  onClose,
  availableVariables = [],
  onRequestPickSelector,
  onRequestPickTapCoords,
  onRequestPickSwipeCoords,
  onRequestCropImage,
  onRequestPickRegion,
  campaignScenarios = [],
  runtimeContext,
  variablePreviewValues,
  nodeCapabilities,
  deviceCapabilities,
  variableLineage,
  onInsertStepBefore,
  onSelectVariableLineagePathKey
}: Props) {
  const locale = useLocale();
  const t = useTranslations('campaignsFeature.stepEditor');
  const tField = useTranslations('campaignsFeature.stepEditor.stepFields');
  const tApp = useTranslations('campaignsFeature.stepEditor.appLifecycle');
  const tSec = useTranslations('campaignsFeature.stepEditor.sections');
  const tSel = useTranslations('campaignsFeature.stepEditor.selector');
  const tIfVar = useTranslations('campaignsFeature.stepEditor.ifVariable');
  const tTarget = useTranslations('campaignsFeature.stepEditor.selectTarget');
  const tOcr = useTranslations('campaignsFeature.stepEditor.ocr');
  const tCap = useTranslations('campaignsFeature.stepEditor.nodeCapability');
  const tSetup = useTranslations('campaignsFeature.stepEditor.setupFlow');
  const tConfig = useTranslations(
    'campaignsFeature.stepEditor.configurationStatus'
  );
  const tLineage = useTranslations(
    'campaignsFeature.stepEditor.variableLineage'
  );
  const tSocialActions = useTranslations(
    'campaignsFeature.stepEditor.socialActions'
  );
  const { optionsForStep } = usePlatformCapabilities();
  const variableInfoT = useVariableInfoTranslator();
  const fallbackText = (value: string, key: string, vi: string, en: string) =>
    value.endsWith(`.${key}`) ? (locale.startsWith('vi') ? vi : en) : value;
  const matchedProfileSourceTitle = fallbackText(
    tSec('matchedProfileSource'),
    'matchedProfileSource',
    'Nguồn bài viết đã match',
    'Matched post source'
  );
  const matchedProfileVerificationTitle = fallbackText(
    tSec('matchedProfileVerification'),
    'matchedProfileVerification',
    'Điều kiện xác minh profile',
    'Profile verification rules'
  );
  const matchedProfileResultTitle = fallbackText(
    tSec('matchedProfileResult'),
    'matchedProfileResult',
    'Kết quả và giới hạn',
    'Result and limits'
  );
  const actionIndexLabel = fallbackText(
    tField('actionIndex'),
    'actionIndex',
    'Thứ tự action',
    'Action index'
  );
  const matchedProfileVerificationHint = fallbackText(
    tField('matchedProfileVerificationHint'),
    'matchedProfileVerificationHint',
    'Profile phải có keyword bắt buộc. Keyword cộng điểm tăng độ tin cậy, keyword cấm sẽ loại target.',
    'The profile must contain the required keywords. Bonus keywords improve confidence; blocked keywords reject the target.'
  );
  const matchedProfileResultHint = fallbackText(
    tField('matchedProfileResultHint'),
    'matchedProfileResultHint',
    'Nếu profile đủ điều kiện, target proof được lưu vào biến này để bước gửi kết bạn dùng tiếp.',
    'When the profile passes verification, target proof is saved here for the friend-request step.'
  );
  const [step, setStep] = useState(() =>
    normalizeSystemVariableCondition(stepProp)
  );
  const stepRef = useRef(step);
  stepRef.current = step;
  const pendingCommitRef = useRef<FlowStep | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const stepIdentity =
    String(
      (stepProp as Record<string, unknown>)._fgId ??
        (stepProp as Record<string, unknown>).id ??
        ''
    ) || stepProp.type;
  const stepIdentityRef = useRef(stepIdentity);

  useEffect(() => {
    if (stepIdentityRef.current === stepIdentity) return;
    stepIdentityRef.current = stepIdentity;
    const normalized = normalizeSystemVariableCondition(stepProp);
    setStep(normalized);
    if (normalized !== stepProp) onChangeRef.current(normalized);
  }, [stepProp, stepIdentity]);

  useEffect(() => {
    return () => {
      if (pendingCommitRef.current)
        onChangeRef.current(pendingCommitRef.current);
    };
  }, []);

  /** Persist edits; text fields use StepPanelInput for draft state. Controlled fields (e.g. toggles) need local step sync. */
  const commitStep = useCallback(
    (next: FlowStep) => {
      pendingCommitRef.current = next;
      setStep(next);
      onChange(next);
    },
    [onChange]
  );

  const update = useCallback(
    (fields: Partial<FlowStep>) => {
      const next = { ...stepRef.current } as FlowStep;
      const record = next as Record<string, unknown>;
      for (const [key, value] of Object.entries(fields)) {
        if (value === undefined) {
          delete record[key];
        } else {
          record[key] = value;
        }
      }
      pendingCommitRef.current = next;
      setStep(next);
      onChange(next);
    },
    [onChange]
  );
  const applyVariableLineageQuickFix = useCallback(
    (fix: StepVariableLineageQuickFix) => {
      if (fix.kind === 'patch_step') {
        update(fix.patch);
        return;
      }
      if (fix.kind === 'insert_step_before') {
        onInsertStepBefore?.(fix.step);
        return;
      }
      if (fix.kind === 'select_producer') {
        onSelectVariableLineagePathKey?.(fix.producerPathKey);
      }
    },
    [onInsertStepBefore, onSelectVariableLineagePathKey, update]
  );
  const isVarRef = (v: string) => /^\$\{[^}]+\}$/.test(v);
  const parseNumOrVar = (raw: string, fallback: number): number | string => {
    const v = raw.trim();
    if (!v) return fallback;
    if (isVarRef(v)) return v;
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };
  const parentLinkMode =
    step.parent_id_var === '_active_comment_parent_hash'
      ? 'auto'
      : step.parent_id_var
        ? 'custom'
        : 'none';
  const doubleTapCoordMode =
    step.rx != null && step.ry != null ? 'ratio' : 'absolute';
  const pinchCoordMode =
    step.rx != null && step.ry != null ? 'ratio' : 'absolute';
  const dragCoordMode =
    step.rx1 != null && step.ry1 != null && step.rx2 != null && step.ry2 != null
      ? 'ratio'
      : 'absolute';
  const isExtractStep = step.type === 'extract';
  const primarySetupTab: SetupTabValue = isExtractStep ? 'screen' : 'action';
  const [setupTab, setSetupTab] = useState<SetupTabValue>(primarySetupTab);
  useEffect(() => {
    setSetupTab(primarySetupTab);
  }, [primarySetupTab, stepIdentity]);
  const nodeCapability = nodeCapabilities?.[step.type];
  const nodeCapabilityStatus = nodeCapability
    ? evaluateNodeCapabilityStatus(nodeCapability, deviceCapabilities)
    : null;
  const configurationStatus = analyzeStepConfiguration(step);
  const socialPlatformOptions = useMemo(
    () => optionsForStep(step.type),
    [optionsForStep, step.type]
  );
  const selectedSocialPlatform =
    typeof step.platform === 'string' && step.platform !== 'auto'
      ? socialPlatformOptions.find((option) => option.value === step.platform)
      : socialPlatformOptions.find((option) => option.supported);
  const selectedSocialPlatformLabel =
    selectedSocialPlatform?.label ??
    (typeof step.platform === 'string' && step.platform !== 'auto'
      ? step.platform
      : 'Auto');
  const selectedSocialPlatformSupported =
    selectedSocialPlatform?.supported ?? false;
  const socialActionOptions = getSocialActionOptions(
    step.type,
    selectedSocialPlatform?.facets
  );
  const currentSocialAction =
    step.action ??
    defaultSocialAction(step.type, selectedSocialPlatform?.facets);
  const currentSocialActionSupported =
    !currentSocialAction ||
    socialActionOptions.some((option) => option.value === currentSocialAction);
  const renderedSocialActionOptions = currentSocialActionSupported
    ? socialActionOptions
    : [{ value: currentSocialAction }, ...socialActionOptions];
  const showContentCommentText =
    step.type === 'content_interaction' && currentSocialAction === 'comment';
  const isSocialActionStep = [
    'content_interaction',
    'connection_request',
    'community_membership'
  ].includes(step.type);
  const missingCommentText =
    showContentCommentText && !String(step.comment_text ?? '').trim();
  const socialSetupState = !selectedSocialPlatformSupported
    ? 'unsupported'
    : !currentSocialActionSupported || missingCommentText
      ? 'needs_setup'
      : 'ready';
  const socialSetupBadgeClassName =
    socialSetupState === 'ready'
      ? 'border-emerald-500/40 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-200'
      : socialSetupState === 'unsupported'
        ? 'border-destructive/40 bg-destructive/5 text-destructive'
        : 'border-amber-500/40 bg-amber-50 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200';
  const socialActionLabel = socialActionOptions.some(
    (known) => known.value === currentSocialAction
  )
    ? tSocialActions(
        currentSocialAction as Parameters<typeof tSocialActions>[0]
      )
    : currentSocialAction || '—';
  const setupTabs: Array<{
    value: SetupTabValue;
    label: string;
    description: string;
  }> = [
    {
      value: primarySetupTab,
      label: isExtractStep ? t('tabs.screen') : tSetup('configure'),
      description: isExtractStep
        ? tSetup('screenDescription')
        : tSetup('configureDescription')
    },
    ...(isExtractStep
      ? [
          {
            value: 'data-save' as const,
            label: tSetup('dataSave'),
            description: tSetup('dataSaveDescription')
          }
        ]
      : []),
    {
      value: 'settings',
      label: tSetup('errorHandling'),
      description: tSetup('errorDescription')
    }
  ];
  const currentSetupTab = setupTabs.some((tab) => tab.value === setupTab)
    ? setupTab
    : primarySetupTab;
  const currentSetupIndex = Math.max(
    0,
    setupTabs.findIndex((tab) => tab.value === currentSetupTab)
  );
  const nextSetupTab = setupTabs[currentSetupIndex + 1];
  const handleDoneAndClose = useCallback(() => {
    if (pendingCommitRef.current) {
      onChangeRef.current(pendingCommitRef.current);
      pendingCommitRef.current = null;
    }
    onClose();
  }, [onClose]);
  return (
    <div className='flex h-full min-h-0 flex-col bg-card'>
      <StepPanelHeader
        step={step}
        variablePreviewValues={variablePreviewValues}
      />

      <div className='min-h-0 flex-1 space-y-4 overflow-y-auto p-3 sm:p-4'>
        {nodeCapability && nodeCapabilityStatus ? (
          <NodeCapabilitySummary
            status={nodeCapabilityStatus}
            evidence={nodeCapability.recorder_evidence ?? []}
            inspectorHints={nodeCapability.inspector_hints ?? []}
            description={nodeCapability.description}
            t={(key, values) => tCap(key as never, values as never)}
          />
        ) : null}

        <StepConfigurationSummary
          status={configurationStatus}
          t={(key, values) => tConfig(key as never, values as never)}
        />

        <VariableLineageSummary
          lineage={variableLineage}
          step={step}
          availableVariables={availableVariables}
          onApplyQuickFix={applyVariableLineageQuickFix}
          canInsertStepBefore={Boolean(onInsertStepBefore)}
          canSelectProducer={Boolean(onSelectVariableLineagePathKey)}
          t={(key, values) => tLineage(key as never, values as never)}
        />

        <StepPanelMetaFields step={step} commitStep={commitStep} t={t} />

        <Tabs
          value={currentSetupTab}
          onValueChange={(value) => setSetupTab(value as SetupTabValue)}
          className='space-y-3'
        >
          <div className='rounded-md border bg-muted/10 p-2'>
            <div className='mb-2 flex items-center justify-between gap-2'>
              <p className='truncate text-xs font-semibold text-foreground'>
                {tSetup('title')}
              </p>
              <span className='shrink-0 text-[10px] font-medium text-muted-foreground'>
                {currentSetupIndex + 1}/{setupTabs.length}
              </span>
            </div>
            <TabsList
              className={cn(
                'grid h-8 w-full gap-1 bg-muted/45 p-1',
                setupTabs.length === 3 ? 'grid-cols-3' : 'grid-cols-2'
              )}
            >
              {setupTabs.map((tab, index) => (
                <TabsTrigger
                  key={tab.value}
                  value={tab.value}
                  className='h-6 min-w-0 gap-1 rounded px-1.5 text-[11px] shadow-none data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm'
                >
                  <span className='flex size-4 shrink-0 items-center justify-center rounded-full bg-background text-[9px] font-semibold text-muted-foreground data-[state=active]:text-foreground'>
                    {index + 1}
                  </span>
                  <span className='min-w-0 truncate font-medium'>
                    {tab.label}
                  </span>
                </TabsTrigger>
              ))}
            </TabsList>
            <p className='mt-2 line-clamp-2 text-[10px] leading-snug text-muted-foreground'>
              {setupTabs[currentSetupIndex]?.description}
            </p>
          </div>

          <TabsContent value={primarySetupTab} className='mt-0 space-y-3'>
            <StepPanelSection title={tSec('stepConfig')}>
              {step.type === 'tap' && (
                <>
                  <StepPanelHint>{tSel('autoFillHint')}</StepPanelHint>
                  <SelectorFields
                    step={step}
                    onChange={commitStep}
                    onRequestPickSelector={onRequestPickSelector}
                    availableVariables={availableVariables}
                    t={t}
                  />
                  <FallbackRatioFields
                    rx={step.fallback?.rx ?? 0.5}
                    ry={step.fallback?.ry ?? 0.5}
                    onRxChange={(rx) =>
                      update({
                        fallback: { ...(step.fallback ?? {}), rx }
                      })
                    }
                    onRyChange={(ry) =>
                      update({
                        fallback: { ...(step.fallback ?? {}), ry }
                      })
                    }
                    onRequestPick={onRequestPickTapCoords}
                    tSel={tSel}
                  />
                  <StepPanelField label={tSec('timing')}>
                    <div className='flex items-center gap-2'>
                      <Input
                        type='number'
                        min={0.1}
                        step={0.1}
                        className='h-9 w-28 text-xs'
                        value={step.timeout ?? 4}
                        onChange={(e) =>
                          update({
                            timeout: Math.max(
                              0.1,
                              Number(e.target.value) || 0.1
                            )
                          })
                        }
                      />
                      <span className='text-[11px] text-muted-foreground'>
                        {tField('unitSeconds')}
                      </span>
                    </div>
                  </StepPanelField>
                </>
              )}

              {(step.type === 'launch_app' ||
                step.type === 'stop_app' ||
                step.type === 'clear_app' ||
                step.type === 'wait_app') && (
                <AppLifecycleStepFields
                  step={step}
                  update={update}
                  tApp={tApp}
                />
              )}

              {(step.type === 'push_file' || step.type === 'pull_file') && (
                <>
                  <F
                    label={
                      step.type === 'push_file'
                        ? tApp('localPathPush')
                        : tApp('localPathPull')
                    }
                  >
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 font-mono text-xs'
                      value={step.local_path ?? ''}
                      placeholder={tApp('placeholderLocal')}
                      onValueChange={(value) => update({ local_path: value })}
                    />
                  </F>
                  <F
                    label={
                      step.type === 'push_file'
                        ? tApp('remotePathPush')
                        : tApp('remotePathPull')
                    }
                  >
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 font-mono text-xs'
                      value={step.remote_path ?? ''}
                      placeholder={tApp('placeholderRemote')}
                      onValueChange={(value) => update({ remote_path: value })}
                    />
                  </F>
                  {step.type === 'push_file' && (
                    <F label={tApp('fileMode')}>
                      <Input
                        type='number'
                        className='h-8 w-28 font-mono text-xs'
                        value={step.mode ?? ''}
                        placeholder={tApp('fileModePlaceholder')}
                        onChange={(e) =>
                          update({
                            mode: e.target.value
                              ? Number(e.target.value)
                              : undefined
                          })
                        }
                      />
                    </F>
                  )}
                  <StepPanelHint>{tApp('fileTransferHint')}</StepPanelHint>
                </>
              )}

              {step.type === 'open_url' && (
                <>
                  <F label='URL'>
                    <div className={valueInsertRowClassName()}>
                      <Input
                        className='h-9 min-w-0 flex-1 text-xs'
                        value={step.url ?? ''}
                        onChange={(e) => update({ url: e.target.value })}
                      />
                      <VariableInsertSelect
                        availableVariables={availableVariables}
                        t={t}
                        onInsert={(token) =>
                          update({ url: insertToken(step.url ?? '', token) })
                        }
                      />
                    </div>
                  </F>
                  <F label={tField('browserPackage')}>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.package ?? ''}
                      onChange={(e) =>
                        update({ package: e.target.value || undefined })
                      }
                    />
                  </F>
                </>
              )}

              {step.type === 'install_apk' && (
                <>
                  <F label={tApp('installApkUrlLabel')}>
                    <div className={valueInsertRowClassName()}>
                      <Input
                        className='h-9 min-w-0 flex-1 font-mono text-xs'
                        value={step.url ?? ''}
                        placeholder={tApp('installApkUrlPlaceholder')}
                        onChange={(e) => update({ url: e.target.value })}
                      />
                      <VariableInsertSelect
                        availableVariables={availableVariables}
                        t={t}
                        onInsert={(token) =>
                          update({ url: insertToken(step.url ?? '', token) })
                        }
                      />
                    </div>
                  </F>
                  <F label={tApp('installApkTimeoutLabel')}>
                    <div className='flex items-center gap-2'>
                      <Input
                        type='number'
                        min={10}
                        max={600}
                        step={10}
                        className='h-8 w-28 text-xs'
                        value={step.timeout ?? 90}
                        onChange={(e) =>
                          update({ timeout: Number(e.target.value) || 90 })
                        }
                      />
                      <span className='text-[11px] text-muted-foreground'>
                        {tApp('installApkTimeoutUnit')}
                      </span>
                    </div>
                  </F>
                  <StepPanelHint>
                    {tApp('installApkHint', {
                      varToken: SCENARIO_VAR_TOKENS.VAR
                    })}
                  </StepPanelHint>
                </>
              )}

              {step.type === 'wait' && (
                <F label={tField('durationSeconds')}>
                  <Input
                    type='number'
                    min={0}
                    step={0.5}
                    className='h-8 w-24 text-xs'
                    value={step.seconds ?? 1}
                    onChange={(e) =>
                      update({ seconds: Number(e.target.value) || 0 })
                    }
                  />
                </F>
              )}

              {[
                'tap_selector',
                'wait_element',
                'assert_element',
                'scroll_to',
                'long_tap_selector'
              ].includes(step.type) && (
                <>
                  <SelectorFields
                    step={step}
                    onChange={commitStep}
                    onRequestPickSelector={onRequestPickSelector}
                    availableVariables={availableVariables}
                    t={t}
                  />
                  {step.type !== 'long_tap_selector' && (
                    <StepPanelField label={tSec('timing')}>
                      <div className='flex items-center gap-2'>
                        <Input
                          type='number'
                          min={0.1}
                          step={0.1}
                          className='h-9 w-28 text-xs'
                          value={
                            step.timeout ??
                            (step.type === 'wait_element'
                              ? 10
                              : step.type === 'assert_element'
                                ? 5
                                : 8)
                          }
                          onChange={(e) =>
                            update({
                              timeout: Math.max(
                                0.1,
                                Number(e.target.value) || 0.1
                              )
                            })
                          }
                        />
                        <span className='text-[11px] text-muted-foreground'>
                          {tField('unitSeconds')}
                        </span>
                      </div>
                    </StepPanelField>
                  )}
                  {(step.type === 'wait_element' ||
                    step.type === 'assert_element') && (
                    <F label={tField('pollIntervalSeconds')}>
                      <Input
                        type='number'
                        min={0.1}
                        step={0.1}
                        className='h-8 w-24 text-xs'
                        value={step.poll ?? 0.5}
                        onChange={(e) =>
                          update({
                            poll: Math.max(0.1, Number(e.target.value) || 0.1)
                          })
                        }
                      />
                    </F>
                  )}
                  {step.type === 'tap_selector' && (
                    <FallbackRatioFields
                      rx={step.fallback_rx ?? 0.5}
                      ry={step.fallback_ry ?? 0.5}
                      onRxChange={(rx) => update({ fallback_rx: rx })}
                      onRyChange={(ry) => update({ fallback_ry: ry })}
                      onRequestPick={onRequestPickTapCoords}
                      tSel={tSel}
                    />
                  )}
                  {step.type === 'scroll_to' && (
                    <div className='grid grid-cols-2 gap-2'>
                      <F label={tField('scrollDirection')}>
                        <select
                          className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                          value={step.direction ?? 'down'}
                          onChange={(e) =>
                            update({ direction: e.target.value })
                          }
                        >
                          <option value='down'>down</option>
                          <option value='up'>up</option>
                        </select>
                      </F>
                      <F label='max_swipes'>
                        <Input
                          type='number'
                          min={1}
                          className='h-8 text-xs'
                          value={step.max_swipes ?? 5}
                          onChange={(e) =>
                            update({ max_swipes: Number(e.target.value) || 1 })
                          }
                        />
                      </F>
                    </div>
                  )}
                  {step.type === 'long_tap_selector' && (
                    <F label={tField('holdMs')}>
                      <Input
                        type='number'
                        min={100}
                        className='h-8 w-24 text-xs'
                        value={step.duration_ms ?? 800}
                        onChange={(e) =>
                          update({ duration_ms: Number(e.target.value) })
                        }
                      />
                    </F>
                  )}
                </>
              )}

              {step.type === 'tap_xml_match' && (
                <>
                  <StepPanelHint>{t('tapXmlMatch.hint')}</StepPanelHint>
                  <div className='grid grid-cols-1 gap-2 sm:grid-cols-2'>
                    <F label={t('tapXmlMatch.attributeLabel')}>
                      <select
                        className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                        value={step.attr ?? step.by ?? 'content-desc'}
                        onChange={(e) =>
                          update({ attr: e.target.value, by: undefined })
                        }
                      >
                        <option value='content-desc'>
                          {t('tapXmlMatch.attrContentDesc')}
                        </option>
                        <option value='text'>
                          {t('tapXmlMatch.attrText')}
                        </option>
                        <option value='resource-id'>
                          {t('tapXmlMatch.attrResourceId')}
                        </option>
                        <option value='class'>
                          {t('tapXmlMatch.attrClass')}
                        </option>
                      </select>
                    </F>
                    <F label={t('tapXmlMatch.matchModeLabel')}>
                      <select
                        className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                        value={step.equals != null ? 'equals' : 'contains'}
                        onChange={(e) => {
                          const currentValue = String(
                            step.contains ?? step.equals ?? step.value ?? ''
                          );
                          update(
                            e.target.value === 'equals'
                              ? {
                                  equals: currentValue,
                                  contains: undefined,
                                  value: undefined
                                }
                              : {
                                  contains: currentValue,
                                  equals: undefined,
                                  value: undefined
                                }
                          );
                        }}
                      >
                        <option value='contains'>
                          {t('tapXmlMatch.matchContains')}
                        </option>
                        <option value='equals'>
                          {t('tapXmlMatch.matchEquals')}
                        </option>
                      </select>
                    </F>
                  </div>
                  <F label={t('tapXmlMatch.valueLabel')}>
                    <div className={valueInsertRowClassName()}>
                      <VariableTextInput
                        availableVariables={availableVariables}
                        t={t}
                        className='h-8 font-mono text-xs'
                        value={String(
                          step.contains ?? step.equals ?? step.value ?? ''
                        )}
                        placeholder={t('tapXmlMatch.valuePlaceholder', {
                          varToken: SCENARIO_VAR_TOKENS.VAR
                        })}
                        onValueChange={(value) =>
                          update(
                            step.equals != null
                              ? {
                                  equals: value,
                                  contains: undefined,
                                  value: undefined
                                }
                              : {
                                  contains: value,
                                  equals: undefined,
                                  value: undefined
                                }
                          )
                        }
                      />
                    </div>
                  </F>
                  <StepPanelToggle
                    label={t('tapXmlMatch.clickableLabel')}
                    description={t('tapXmlMatch.clickableDescription')}
                    checked={step.clickable ?? true}
                    onCheckedChange={(checked) =>
                      update({ clickable: checked })
                    }
                  />
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tField('timeoutSeconds')}>
                      <Input
                        type='number'
                        min={0.1}
                        step={0.1}
                        className='h-8 text-xs'
                        value={step.timeout ?? 6}
                        onChange={(e) =>
                          update({
                            timeout: Math.max(0.1, Number(e.target.value) || 6)
                          })
                        }
                      />
                    </F>
                    <F label={tField('pollSeconds')}>
                      <Input
                        type='number'
                        min={0.05}
                        step={0.05}
                        className='h-8 text-xs'
                        value={step.poll ?? 0.25}
                        onChange={(e) =>
                          update({
                            poll: Math.max(0.05, Number(e.target.value) || 0.25)
                          })
                        }
                      />
                    </F>
                  </div>
                </>
              )}

              {step.type === 'tap_ratio' && (
                <div className='space-y-2'>
                  {onRequestPickTapCoords && (
                    <Button
                      size='sm'
                      variant='outline'
                      className='h-7 w-full gap-1.5 border-sky-400/50 text-[10px] text-sky-800 hover:bg-sky-50 dark:text-sky-300 dark:hover:bg-sky-950/30'
                      onClick={onRequestPickTapCoords}
                    >
                      <MousePointerClick size={12} />
                      {tField('pickTapCoordsCta')}
                    </Button>
                  )}
                  <div className='grid grid-cols-2 gap-2'>
                    <F label='X (0-1)'>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.01}
                        className='h-8 text-xs'
                        value={step.x ?? 0.5}
                        onChange={(e) =>
                          update({ x: parseFloat(e.target.value) || 0 })
                        }
                      />
                    </F>
                    <F label='Y (0-1)'>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.01}
                        className='h-8 text-xs'
                        value={step.y ?? 0.5}
                        onChange={(e) =>
                          update({ y: parseFloat(e.target.value) || 0 })
                        }
                      />
                    </F>
                  </div>
                </div>
              )}

              {step.type === 'swipe_ratio' && (
                <div className='space-y-2'>
                  {onRequestPickSwipeCoords && (
                    <Button
                      size='sm'
                      variant='outline'
                      className='h-7 w-full gap-1.5 border-sky-400/50 text-[10px] text-sky-800 hover:bg-sky-50 dark:text-sky-300 dark:hover:bg-sky-950/30'
                      onClick={onRequestPickSwipeCoords}
                    >
                      <Move size={12} />
                      {tField('pickSwipeCoordsCta')}
                    </Button>
                  )}
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tField('fromX')}>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.01}
                        className='h-8 text-xs'
                        value={step.x1 ?? 0.5}
                        onChange={(e) =>
                          update({ x1: parseFloat(e.target.value) })
                        }
                      />
                    </F>
                    <F label={tField('fromY')}>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.01}
                        className='h-8 text-xs'
                        value={step.y1 ?? 0.8}
                        onChange={(e) =>
                          update({ y1: parseFloat(e.target.value) })
                        }
                      />
                    </F>
                    <F label={tField('toX')}>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.01}
                        className='h-8 text-xs'
                        value={step.x2 ?? 0.5}
                        onChange={(e) =>
                          update({ x2: parseFloat(e.target.value) })
                        }
                      />
                    </F>
                    <F label={tField('toY')}>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.01}
                        className='h-8 text-xs'
                        value={step.y2 ?? 0.2}
                        onChange={(e) =>
                          update({ y2: parseFloat(e.target.value) })
                        }
                      />
                    </F>
                  </div>
                  <F label={tField('swipeMs')}>
                    <Input
                      type='number'
                      min={50}
                      className='h-8 w-28 text-xs'
                      value={step.duration_ms ?? 300}
                      onChange={(e) =>
                        update({ duration_ms: Number(e.target.value) || 300 })
                      }
                    />
                  </F>
                </div>
              )}

              {['login_if_needed', 'fill_form', 'assert_app_state'].includes(
                step.type
              ) && (
                <AppAutomationStepFields
                  step={step}
                  update={update}
                  availableVariables={availableVariables}
                />
              )}

              {PLATFORM_AWARE_STEP_TYPES.has(step.type) && (
                <PlatformSelect
                  value={step.platform}
                  onChange={(platform) => update({ platform })}
                  stepType={step.type}
                />
              )}

              {step.type === 'platform_session_gate' && (
                <div className='space-y-3'>
                  <div className='overflow-hidden rounded-lg border'>
                    <div className='flex items-center gap-2 border-b bg-muted/40 px-3 py-2'>
                      <ShieldCheck className='size-3.5 text-muted-foreground' />
                      <p className='text-xs font-medium'>
                        {t('sessionGate.contextTitle')}
                      </p>
                    </div>
                    <dl className='divide-y'>
                      <SessionGateFact
                        label={t('sessionGate.phone')}
                        value={runtimeContext?.deviceLabel}
                        placeholder={t('sessionGate.selectPhone')}
                      />
                      <SessionGateFact
                        label={t('sessionGate.account')}
                        value={
                          runtimeContext?.loading
                            ? t('sessionGate.loading')
                            : runtimeContext?.accountLabel
                        }
                        placeholder={t('sessionGate.noPrimaryAccount')}
                      />
                      <SessionGateFact
                        label={t('sessionGate.platform')}
                        value={
                          runtimeContext?.loading
                            ? t('sessionGate.loading')
                            : runtimeContext?.platform
                        }
                        placeholder={t('sessionGate.notAvailable')}
                      />
                      <SessionGateFact
                        label={t('sessionGate.session')}
                        value={
                          runtimeContext?.loading
                            ? t('sessionGate.loading')
                            : runtimeContext?.error
                              ? t('sessionGate.loadFailed')
                              : runtimeContext?.sessionState
                        }
                        placeholder={t('sessionGate.noSession')}
                      />
                    </dl>
                    {!runtimeContext?.loading &&
                    !runtimeContext?.accountLabel ? (
                      <SessionGateAccountBinder
                        deviceId={runtimeContext?.deviceId ?? null}
                        platform={step.platform ?? 'facebook'}
                      />
                    ) : null}
                  </div>
                  <div className='grid grid-cols-2 gap-3'>
                    <F label={t('sessionGate.phase')}>
                      <select
                        className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'
                        value={step.phase ?? 'preflight'}
                        onChange={(e) => {
                          const phase = e.target.value;
                          update({
                            phase,
                            timeout: phase === 'confirm' ? 20 : 0
                          });
                        }}
                      >
                        <option value='preflight'>
                          {t('sessionGate.preflight')}
                        </option>
                        <option value='confirm'>
                          {t('sessionGate.confirm')}
                        </option>
                      </select>
                    </F>
                    <F label={t('sessionGate.timeout')}>
                      <Input
                        type='number'
                        min={0}
                        max={30}
                        step={1}
                        className='h-8 text-xs'
                        value={
                          step.timeout ?? (step.phase === 'confirm' ? 20 : 0)
                        }
                        onChange={(e) =>
                          update({ timeout: Number(e.target.value) || 0 })
                        }
                      />
                    </F>
                  </div>
                  <p className='text-[11px] leading-snug text-muted-foreground'>
                    {step.phase === 'confirm'
                      ? t('sessionGate.phaseHintConfirm')
                      : t('sessionGate.phaseHintPreflight')}
                  </p>
                </div>
              )}

              {step.type === 'input_text' && (
                <>
                  <F label={tField('textToType')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      value={step.text ?? ''}
                      onValueChange={(value) => update({ text: value })}
                      className='h-8 text-xs'
                      t={t}
                    />
                  </F>
                  {/* <F label={tField('inputMethod')}>
                    <select
                      className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={step.via ?? 'u2'}
                      onChange={(e) => update({ via: e.target.value })}
                    >
                      <option value='u2'>u2</option>
                      <option value='a11y_key'>a11y_key</option>
                    </select>
                  </F> */}
                </>
              )}

              {step.type === 'input_selector' && (
                <>
                  <SelectorFields
                    step={step}
                    onChange={commitStep}
                    onRequestPickSelector={onRequestPickSelector}
                    availableVariables={availableVariables}
                    t={t}
                  />
                  <F label={tField('textToType')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      value={step.text ?? ''}
                      onValueChange={(value) => update({ text: value })}
                      className='h-8 text-xs'
                      t={t}
                    />
                  </F>
                  <StepPanelToggle
                    label={tField('clearBeforeTyping')}
                    checked={step.clear_first ?? true}
                    onCheckedChange={(checked) =>
                      update({ clear_first: checked })
                    }
                  />
                </>
              )}

              {step.type === 'key' && (
                <F label={tField('key')}>
                  <select
                    className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                    value={step.key ?? 'enter'}
                    onChange={(e) => update({ key: e.target.value })}
                  >
                    <option value='enter'>Enter</option>
                    <option value='back'>Back</option>
                    <option value='home'>Home</option>
                    <option value='recent'>Recent Apps</option>
                  </select>
                </F>
              )}

              {step.type === 'adb_shell' && (
                <>
                  <StepPanelHint>{t('adbShell.hint')}</StepPanelHint>
                  <F label={t('adbShell.commandLabel')}>
                    <div className='space-y-2'>
                      <StepPanelTextarea
                        className='min-h-[96px] w-full resize-y rounded-md border bg-background px-2.5 py-2 font-mono text-xs leading-relaxed shadow-sm'
                        value={step.command ?? step.cmd ?? ''}
                        placeholder='settings put system screen_brightness 80'
                        spellCheck={false}
                        onValueCommit={(value) => update({ command: value })}
                      />
                      <VariableInsertSelect
                        availableVariables={availableVariables}
                        t={t}
                        onInsert={(token) =>
                          update({
                            command: insertToken(
                              step.command ?? step.cmd ?? '',
                              token
                            )
                          })
                        }
                      />
                    </div>
                  </F>
                  <div className='grid gap-2 sm:grid-cols-3'>
                    <F label={t('adbShell.timeoutLabel')}>
                      <Input
                        type='number'
                        min={1}
                        max={120}
                        step={1}
                        className='h-8 text-xs'
                        value={step.timeout ?? 30}
                        onChange={(e) =>
                          update({ timeout: Number(e.target.value) || 30 })
                        }
                      />
                    </F>
                    <F label={t('adbShell.saveAsLabel')}>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.save_as ?? ''}
                        placeholder='ADB_OUTPUT'
                        onChange={(e) =>
                          update({ save_as: e.target.value || undefined })
                        }
                      />
                    </F>
                    <F label={t('adbShell.maxOutputLabel')}>
                      <Input
                        type='number'
                        min={1000}
                        max={50000}
                        step={1000}
                        className='h-8 text-xs'
                        value={step.max_output_chars ?? 8000}
                        onChange={(e) =>
                          update({
                            max_output_chars: Number(e.target.value) || 8000
                          })
                        }
                      />
                    </F>
                  </div>
                  <StepPanelToggle
                    label={t('adbShell.failOnErrorLabel')}
                    description={t('adbShell.failOnErrorDescription')}
                    checked={step.fail_on_error ?? true}
                    onCheckedChange={(checked) =>
                      update({ fail_on_error: checked })
                    }
                  />
                </>
              )}

              {step.type === 'scroll_down' && (
                <ScrollDownStepFields
                  step={step}
                  update={update}
                  availableVariables={availableVariables}
                />
              )}

              {step.type === 'wait_stable' && (
                <div className='grid grid-cols-2 gap-2'>
                  <F label={tField('timeoutSeconds')}>
                    <Input
                      type='number'
                      min={1}
                      step={0.5}
                      className='h-8 text-xs'
                      value={step.timeout ?? 5}
                      onChange={(e) =>
                        update({ timeout: Number(e.target.value) || 5 })
                      }
                    />
                  </F>
                  <F label={tField('stableForSeconds')}>
                    <Input
                      type='number'
                      min={0.1}
                      step={0.1}
                      className='h-8 text-xs'
                      value={step.stable_duration ?? 0.4}
                      onChange={(e) =>
                        update({
                          stable_duration: Number(e.target.value) || 0.4
                        })
                      }
                    />
                  </F>
                </div>
              )}

              {step.type === 'verify_screen' && (
                <VerifyScreenFields
                  step={step}
                  update={update}
                  onRequestCropImage={onRequestCropImage}
                />
              )}

              {step.type === 'dismiss_popup' && (
                <F label={tField('retryCount')}>
                  <Input
                    type='number'
                    min={1}
                    max={10}
                    className='h-8 w-24 text-xs'
                    value={step.retries ?? 3}
                    onChange={(e) =>
                      update({ retries: Number(e.target.value) || 3 })
                    }
                  />
                </F>
              )}

              {step.type === 'social_select_target' && (
                <>
                  <StepPanelHint>
                    {tTarget('hint', {
                      kind:
                        step.target_type === 'post'
                          ? tTarget('kindPost')
                          : tTarget('kindPerson')
                    })}
                  </StepPanelHint>
                  <F label={tTarget('targetTypeLabel')}>
                    <select
                      className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
                      value={step.target_type ?? 'person'}
                      onChange={(e) =>
                        update({
                          target_type: e.target.value,
                          ...(e.target.value === 'post'
                            ? { display_name: undefined }
                            : { display_text: undefined })
                        })
                      }
                    >
                      <option value='person'>{tTarget('optionPerson')}</option>
                      <option value='post'>{tTarget('optionPost')}</option>
                    </select>
                  </F>
                  <F label={tField('searchKeyword')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      value={step.search ?? ''}
                      placeholder={
                        step.target_type === 'post'
                          ? '${POST_SEARCH}'
                          : '${PEOPLE_SEARCH}'
                      }
                      onValueChange={(value) =>
                        update({ search: value || undefined })
                      }
                    />
                  </F>
                  <F
                    label={
                      step.target_type === 'post'
                        ? tField('matchPostText')
                        : tField('matchDisplayName')
                    }
                  >
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      value={
                        step.target_type === 'post'
                          ? (step.display_text ?? '')
                          : (step.display_name ?? '')
                      }
                      placeholder={
                        step.target_type === 'post'
                          ? '${POST_ROW_TEXT}'
                          : '${PEOPLE_ROW_TEXT}'
                      }
                      onValueChange={(value) =>
                        update(
                          step.target_type === 'post'
                            ? { display_text: value || undefined }
                            : { display_name: value || undefined }
                        )
                      }
                    />
                  </F>
                  <F label={tField('requiredKeywords')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      value={keywordInputValue(step.required_keywords)}
                      placeholder='Hoang Le, OpenAI'
                      onValueChange={(value) =>
                        update({
                          required_keywords: keywordListFromInput(value)
                        })
                      }
                    />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tField('bonusKeywords')}>
                      <VariableTextInput
                        availableVariables={availableVariables}
                        t={t}
                        className='h-8 text-xs'
                        value={keywordInputValue(step.optional_keywords)}
                        placeholder='company, city'
                        onValueChange={(value) =>
                          update({
                            optional_keywords: keywordListFromInput(value)
                          })
                        }
                      />
                    </F>
                    <F label={tField('blockedKeywords')}>
                      <VariableTextInput
                        availableVariables={availableVariables}
                        t={t}
                        className='h-8 text-xs'
                        value={keywordInputValue(step.forbidden_keywords)}
                        placeholder='fake, page'
                        onValueChange={(value) =>
                          update({
                            forbidden_keywords: keywordListFromInput(value)
                          })
                        }
                      />
                    </F>
                  </div>
                  <div className='grid grid-cols-3 gap-2'>
                    <F label={tField('minScore')}>
                      <Input
                        type='number'
                        min={0}
                        max={200}
                        className='h-8 text-xs'
                        value={step.min_score ?? 80}
                        onChange={(e) =>
                          update({
                            min_score: Math.max(
                              0,
                              Math.min(200, Number(e.target.value) || 80)
                            )
                          })
                        }
                      />
                    </F>
                    <F label={tField('timeoutSeconds')}>
                      <Input
                        type='number'
                        min={1}
                        max={60}
                        step={0.5}
                        className='h-8 text-xs'
                        value={step.timeout ?? 12}
                        onChange={(e) =>
                          update({
                            timeout: Math.max(1, Number(e.target.value) || 12)
                          })
                        }
                      />
                    </F>
                    <F label={tField('saveTarget')}>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={
                          step.save_as ??
                          (step.target_type === 'post'
                            ? '_post_target'
                            : '_people_target')
                        }
                        onChange={(e) =>
                          update({
                            save_as:
                              e.target.value ||
                              (step.target_type === 'post'
                                ? '_post_target'
                                : '_people_target')
                          })
                        }
                      />
                    </F>
                  </div>
                  <label className='flex items-center gap-2 text-xs text-muted-foreground'>
                    <input
                      type='checkbox'
                      checked={step.require_unique ?? true}
                      onChange={(e) =>
                        update({ require_unique: e.target.checked })
                      }
                    />
                    {tField('requireUniqueCandidate')}
                  </label>
                </>
              )}

              {step.type === 'social_connect_visible_people' && (
                <>
                  <StepPanelHint>{tField('connectVisibleHint')}</StepPanelHint>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tField('minScore')}>
                      <Input
                        type='number'
                        min={0}
                        max={200}
                        className='h-8 text-xs'
                        value={step.min_score ?? 40}
                        onChange={(e) =>
                          update({
                            min_score: Math.max(
                              0,
                              Math.min(200, Number(e.target.value) || 40)
                            )
                          })
                        }
                      />
                    </F>
                    <F label={tField('timeoutSeconds')}>
                      <Input
                        type='number'
                        min={1}
                        max={60}
                        step={0.5}
                        className='h-8 text-xs'
                        value={step.timeout ?? 8}
                        onChange={(e) =>
                          update({
                            timeout: Math.max(1, Number(e.target.value) || 8)
                          })
                        }
                      />
                    </F>
                  </div>
                  <F label={tField('mutualKeywords')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      value={keywordInputValue(step.common_keywords)}
                      placeholder={tField('phMutualKeywords')}
                      onValueChange={(value) =>
                        update({
                          common_keywords: keywordListFromInput(value)
                        })
                      }
                    />
                  </F>
                  <F label={tField('blockedKeywords')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      value={keywordInputValue(step.forbidden_keywords)}
                      placeholder='trang, page, sponsored, anonymous'
                      onValueChange={(value) =>
                        update({
                          forbidden_keywords: keywordListFromInput(value)
                        })
                      }
                    />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tField('waitVerifySeconds')}>
                      <Input
                        type='number'
                        min={0}
                        max={10}
                        step={0.1}
                        className='h-8 text-xs'
                        value={step.verify_wait_s ?? 0.8}
                        onChange={(e) =>
                          update({
                            verify_wait_s: Math.max(
                              0,
                              Math.min(10, Number(e.target.value) || 0.8)
                            )
                          })
                        }
                      />
                    </F>
                    <F label={tField('saveResult')}>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.save_as ?? '_visible_connection_action'}
                        onChange={(e) =>
                          update({
                            save_as:
                              e.target.value || '_visible_connection_action'
                          })
                        }
                      />
                    </F>
                  </div>
                  <label className='flex items-center gap-2 text-xs text-muted-foreground'>
                    <input
                      type='checkbox'
                      checked={step.require_common ?? true}
                      onChange={(e) =>
                        update({ require_common: e.target.checked })
                      }
                    />
                    {tField('requireCommonBeforeInvite')}
                  </label>
                </>
              )}

              {step.type === 'social_scan_posts_interact' && (
                <>
                  <StepPanelHint>{t('scanPostsHint')}</StepPanelHint>
                  <F label={tField('postKeywords')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      value={keywordInputValue(step.keywords)}
                      placeholder={tField('phPostKeywords')}
                      onValueChange={(value) =>
                        update({
                          keywords: keywordListFromInput(value)
                        })
                      }
                    />
                  </F>
                  <F label='Comment'>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      value={step.comment_text ?? ''}
                      placeholder='${COMMENT_TEXT}'
                      onValueChange={(value) =>
                        update({ comment_text: value || undefined })
                      }
                    />
                  </F>
                  <div className='grid grid-cols-3 gap-2'>
                    <F label={tField('postCount')}>
                      <Input
                        type='number'
                        min={1}
                        max={50}
                        className='h-8 text-xs'
                        value={step.target_count ?? 1}
                        onChange={(e) =>
                          update({
                            target_count: Math.max(
                              1,
                              Math.min(50, Number(e.target.value) || 1)
                            )
                          })
                        }
                      />
                    </F>
                    <F label='Max scroll'>
                      <Input
                        type='number'
                        min={0}
                        max={200}
                        className='h-8 text-xs'
                        value={step.max_scrolls ?? 6}
                        onChange={(e) =>
                          update({
                            max_scrolls: Math.max(
                              0,
                              Math.min(200, Number(e.target.value) || 0)
                            )
                          })
                        }
                      />
                    </F>
                    <F label={tField('timeoutSeconds')}>
                      <Input
                        type='number'
                        min={1}
                        max={600}
                        className='h-8 text-xs'
                        value={step.timeout ?? 45}
                        onChange={(e) =>
                          update({
                            timeout: Math.max(1, Number(e.target.value) || 45)
                          })
                        }
                      />
                    </F>
                  </div>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label='Match keyword'>
                      <select
                        className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                        value={step.match_mode ?? 'any'}
                        onChange={(e) => update({ match_mode: e.target.value })}
                      >
                        <option value='any'>{tField('matchModeAny')}</option>
                        <option value='all'>{tField('matchModeAll')}</option>
                      </select>
                    </F>
                    <F label={tField('swipeXPosition')}>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.01}
                        className='h-8 text-xs'
                        value={step.scroll_x_ratio ?? 0.5}
                        onChange={(e) =>
                          update({
                            scroll_x_ratio: Math.max(
                              0,
                              Math.min(1, Number(e.target.value) || 0.5)
                            )
                          })
                        }
                      />
                    </F>
                  </div>
                  <label className='flex items-center gap-2 text-xs text-muted-foreground'>
                    <input
                      type='checkbox'
                      checked={step.like_post ?? true}
                      onChange={(e) => update({ like_post: e.target.checked })}
                    />
                    Like post khi match
                  </label>
                  <label className='flex items-center gap-2 text-xs text-muted-foreground'>
                    <input
                      type='checkbox'
                      checked={step.require_comment ?? true}
                      onChange={(e) =>
                        update({ require_comment: e.target.checked })
                      }
                    />
                    {tField('requireCommentSubmitted')}
                  </label>
                </>
              )}

              {(step.type === 'social_open_author_from_post_match' ||
                step.type === 'social_open_commenter_from_post_match') && (
                <>
                  <StepPanelSection title={matchedProfileSourceTitle}>
                    <StepPanelHint>
                      {step.type === 'social_open_commenter_from_post_match'
                        ? tField('adapterHintCommenter')
                        : tField('adapterHintAuthor')}
                    </StepPanelHint>
                    <div className='grid min-w-0 grid-cols-1 gap-2'>
                      <F label={tField('scanVar')}>
                        <Input
                          className='h-8 min-w-0 font-mono text-xs'
                          value={step.source_var ?? '_post_scan'}
                          onChange={(e) =>
                            update({
                              source_var: e.target.value || '_post_scan'
                            })
                          }
                        />
                      </F>
                      <F label={actionIndexLabel}>
                        <Input
                          type='number'
                          min={0}
                          max={20}
                          className='h-8 text-xs'
                          value={step.action_index ?? 0}
                          onChange={(e) =>
                            update({
                              action_index: Math.max(
                                0,
                                Math.min(20, Number(e.target.value) || 0)
                              )
                            })
                          }
                        />
                      </F>
                    </div>
                  </StepPanelSection>

                  <StepPanelSection title={matchedProfileVerificationTitle}>
                    <StepPanelHint>
                      {matchedProfileVerificationHint}
                    </StepPanelHint>
                    <F label={tField('requiredProfileKeywords')}>
                      <VariableTextInput
                        availableVariables={availableVariables}
                        t={t}
                        className='h-8 text-xs'
                        value={keywordInputValue(step.required_keywords)}
                        placeholder={tField('phProfileKeywords')}
                        onValueChange={(value) =>
                          update({
                            required_keywords: keywordListFromInput(value)
                          })
                        }
                      />
                    </F>
                    <F label={tField('bonusKeywords')}>
                      <VariableTextInput
                        availableVariables={availableVariables}
                        t={t}
                        className='h-8 text-xs'
                        value={keywordInputValue(step.optional_keywords)}
                        placeholder={tField('phBonusKeywords')}
                        onValueChange={(value) =>
                          update({
                            optional_keywords: keywordListFromInput(value)
                          })
                        }
                      />
                    </F>
                    <F label={tField('blockedKeywords')}>
                      <VariableTextInput
                        availableVariables={availableVariables}
                        t={t}
                        className='h-8 text-xs'
                        value={keywordInputValue(step.forbidden_keywords)}
                        placeholder='page, group, anonymous'
                        onValueChange={(value) =>
                          update({
                            forbidden_keywords: keywordListFromInput(value)
                          })
                        }
                      />
                    </F>
                  </StepPanelSection>

                  <StepPanelSection title={matchedProfileResultTitle}>
                    <StepPanelHint>{matchedProfileResultHint}</StepPanelHint>
                    <div className='grid min-w-0 grid-cols-1 gap-2'>
                      <F label={tField('minScore')}>
                        <Input
                          type='number'
                          min={0}
                          max={200}
                          className='h-8 text-xs'
                          value={step.min_score ?? 80}
                          onChange={(e) =>
                            update({
                              min_score: Math.max(
                                0,
                                Math.min(200, Number(e.target.value) || 80)
                              )
                            })
                          }
                        />
                      </F>
                      <F label={tField('timeoutSeconds')}>
                        <Input
                          type='number'
                          min={1}
                          max={60}
                          step={0.5}
                          className='h-8 text-xs'
                          value={step.timeout ?? 12}
                          onChange={(e) =>
                            update({
                              timeout: Math.max(1, Number(e.target.value) || 12)
                            })
                          }
                        />
                      </F>
                      <F label={tField('saveTarget')}>
                        <Input
                          className='h-8 min-w-0 font-mono text-xs'
                          value={step.save_as ?? '_people_target'}
                          onChange={(e) =>
                            update({
                              save_as: e.target.value || '_people_target'
                            })
                          }
                        />
                      </F>
                    </div>
                  </StepPanelSection>
                </>
              )}

              {isSocialActionStep && (
                <>
                  <StepPanelSection
                    title={tField('capabilitySetup')}
                    badge={
                      <Badge
                        variant='outline'
                        className={cn(
                          'h-5 rounded-md px-1.5 text-[10px]',
                          socialSetupBadgeClassName
                        )}
                      >
                        {tField(socialSetupState)}
                      </Badge>
                    }
                    className='space-y-3 border-primary/20 bg-primary/5'
                  >
                    <StepPanelHint>
                      {tField('capabilitySetupHint')}
                    </StepPanelHint>
                    <div className='grid gap-2 sm:grid-cols-3'>
                      <div className='rounded-md border bg-background/80 p-2.5'>
                        <div className='mb-1 flex items-center justify-between gap-2'>
                          <span className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                            1 · {tField('runTarget')}
                          </span>
                          <Badge
                            variant='secondary'
                            className='max-w-24 truncate'
                          >
                            {selectedSocialPlatformLabel}
                          </Badge>
                        </div>
                        <p className='text-[11px] leading-relaxed text-muted-foreground'>
                          {selectedSocialPlatform?.coverage ??
                            tField('selectProviderAbove')}
                        </p>
                      </div>
                      <div className='rounded-md border bg-background/80 p-2.5'>
                        <div className='mb-1 flex items-center justify-between gap-2'>
                          <span className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                            2 · {tField('target')}
                          </span>
                          <Badge
                            variant='outline'
                            className='max-w-24 truncate'
                          >
                            {step.require_verified_target
                              ? tField('verified')
                              : tField('currentScreen')}
                          </Badge>
                        </div>
                        <p className='truncate font-mono text-[11px] text-muted-foreground'>
                          {step.require_verified_target ??
                            tField('currentScreenTarget')}
                        </p>
                      </div>
                      <div className='rounded-md border bg-background/80 p-2.5'>
                        <div className='mb-1 flex items-center justify-between gap-2'>
                          <span className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                            3 · {tField('action')}
                          </span>
                          <Badge
                            variant={
                              currentSocialActionSupported
                                ? 'secondary'
                                : 'destructive'
                            }
                            className='max-w-24 truncate'
                          >
                            {socialActionLabel}
                          </Badge>
                        </div>
                        <p className='text-[11px] leading-relaxed text-muted-foreground'>
                          {showContentCommentText
                            ? missingCommentText
                              ? tField('commentTextRequired')
                              : tField('commentTextReady')
                            : tField('providerActionResolved')}
                        </p>
                      </div>
                    </div>
                    {!selectedSocialPlatformSupported && (
                      <p className='rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-[11px] leading-relaxed text-destructive'>
                        {tField('unsupportedProviderHint')}
                      </p>
                    )}
                  </StepPanelSection>

                  <StepPanelSection title={tField('actionContent')}>
                    <F label={tField('action')}>
                      <select
                        className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                        value={currentSocialAction}
                        onChange={(e) => update({ action: e.target.value })}
                        disabled={renderedSocialActionOptions.length <= 1}
                      >
                        {renderedSocialActionOptions.map((option) => (
                          <option key={option.value} value={option.value}>
                            {socialActionOptions.some(
                              (known) => known.value === option.value
                            )
                              ? tSocialActions(
                                  option.value as Parameters<
                                    typeof tSocialActions
                                  >[0]
                                )
                              : option.value}
                          </option>
                        ))}
                      </select>
                      {renderedSocialActionOptions.length <= 1 && (
                        <p className='mt-1 text-[11px] text-muted-foreground'>
                          {tField('singleProviderActionHint')}
                        </p>
                      )}
                      {!currentSocialActionSupported && (
                        <p className='mt-1 text-[11px] text-destructive'>
                          {tField('unsupportedActionHint')}
                        </p>
                      )}
                    </F>
                    {showContentCommentText && (
                      <F label={tField('commentText')}>
                        <VariableTextInput
                          availableVariables={availableVariables}
                          t={t}
                          className={cn(
                            'h-8 text-xs',
                            missingCommentText &&
                              'border-amber-500 focus-visible:ring-amber-500'
                          )}
                          value={step.comment_text ?? ''}
                          placeholder='${COMMENT_TEXT}'
                          onValueChange={(value) =>
                            update({ comment_text: value || undefined })
                          }
                        />
                        {missingCommentText && (
                          <p className='mt-1 text-[11px] text-amber-700 dark:text-amber-200'>
                            {tField('commentTextRequired')}
                          </p>
                        )}
                      </F>
                    )}
                  </StepPanelSection>

                  <StepPanelSection
                    title={tField('advancedBehavior')}
                    badge={
                      <Badge
                        variant='outline'
                        className='h-5 rounded-md px-1.5 text-[10px]'
                      >
                        {tField('advanced')}
                      </Badge>
                    }
                    className='bg-muted/10'
                  >
                    <div className='grid grid-cols-3 gap-2'>
                      <F label={tField('findButtonSeconds')}>
                        <Input
                          type='number'
                          min={0.1}
                          max={60}
                          step={0.1}
                          className='h-8 text-xs'
                          value={step.timeout ?? 6}
                          onChange={(e) =>
                            update({
                              timeout: Math.max(
                                0.1,
                                Number(e.target.value) || 6
                              )
                            })
                          }
                        />
                      </F>
                      <F label={tField('pollSeconds')}>
                        <Input
                          type='number'
                          min={0.05}
                          max={10}
                          step={0.05}
                          className='h-8 text-xs'
                          value={step.poll ?? 0.4}
                          onChange={(e) =>
                            update({
                              poll: Math.max(
                                0.05,
                                Number(e.target.value) || 0.4
                              )
                            })
                          }
                        />
                      </F>
                      <F label={tField('verifySeconds')}>
                        <Input
                          type='number'
                          min={0.1}
                          max={60}
                          step={0.1}
                          className='h-8 text-xs'
                          value={step.verify_timeout ?? 5}
                          onChange={(e) =>
                            update({
                              verify_timeout: Math.max(
                                0.1,
                                Number(e.target.value) || 5
                              )
                            })
                          }
                        />
                      </F>
                    </div>
                    <F label={tField('saveResultToVar')}>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.save_as ?? ''}
                        placeholder='SOCIAL_ACTION_RESULT'
                        onChange={(e) =>
                          update({ save_as: e.target.value || undefined })
                        }
                      />
                    </F>
                    <F label={tField('requireVerifiedTarget')}>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.require_verified_target ?? ''}
                        placeholder='_people_target'
                        onChange={(e) =>
                          update({
                            require_verified_target: e.target.value || undefined
                          })
                        }
                      />
                    </F>
                  </StepPanelSection>
                </>
              )}

              {step.type === 'social_find_comment_button' && (
                <>
                  <div className='rounded-md border border-sky-400/40 bg-sky-50/60 px-3 py-2.5 text-[11px] leading-relaxed text-sky-950 dark:border-sky-500/30 dark:bg-sky-950/30 dark:text-sky-100'>
                    {tField('findCommentButtonHint')}
                  </div>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tField('waitButtonMaxSeconds')}>
                      <Input
                        type='number'
                        min={0.5}
                        step={0.5}
                        className='h-8 text-xs'
                        value={step.timeout ?? 6}
                        onChange={(e) =>
                          update({
                            timeout: Math.max(0.5, Number(e.target.value) || 6)
                          })
                        }
                      />
                    </F>
                    <F label={tField('checkIntervalSeconds')}>
                      <Input
                        type='number'
                        min={0.1}
                        step={0.1}
                        className='h-8 text-xs'
                        value={step.poll ?? 0.4}
                        onChange={(e) =>
                          update({
                            poll: Math.max(0.1, Number(e.target.value) || 0.4)
                          })
                        }
                      />
                    </F>
                  </div>
                  <StepPanelToggle
                    label={tField('ignoreButtonMissingError')}
                    description={tField('ignoreButtonMissingErrorHint')}
                    checked={step.ignore_error !== false}
                    onCheckedChange={(checked) =>
                      update({ ignore_error: checked })
                    }
                  />
                </>
              )}

              {step.type === 'social_tap_comment_target' && (
                <>
                  <div className='rounded-md border border-blue-400/40 bg-blue-50/60 px-3 py-2.5 text-[11px] leading-relaxed text-blue-950 dark:border-blue-500/30 dark:bg-blue-950/30 dark:text-blue-100'>
                    {tField('tapCommentTargetHint')}
                  </div>
                  <F label={tField('waitCommentSheetSeconds')}>
                    <Input
                      type='number'
                      min={0}
                      step={0.1}
                      className='h-8 w-28 text-xs'
                      value={step.post_tap_wait_s ?? 0.35}
                      onChange={(e) =>
                        update({
                          post_tap_wait_s: Math.max(
                            0,
                            Number(e.target.value) || 0.35
                          )
                        })
                      }
                    />
                  </F>
                  <StepPanelToggle
                    label={tField('ignoreSheetOpenError')}
                    description={tField('ignoreSheetOpenErrorHint')}
                    checked={step.ignore_error !== false}
                    onCheckedChange={(checked) =>
                      update({ ignore_error: checked })
                    }
                  />
                </>
              )}

              {step.type === 'social_apply_comment_filter' && (
                <>
                  <div className='rounded-md border border-emerald-400/40 bg-emerald-50/60 px-3 py-2.5 text-[11px] leading-relaxed text-emerald-950 dark:border-emerald-500/30 dark:bg-emerald-950/30 dark:text-emerald-100'>
                    {tField('commentFilterHint')}
                  </div>
                  <F label={tField('commentFilter')}>
                    <select
                      className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
                      value={
                        step.comment_filter ??
                        (step.switch_to_all_comments === false
                          ? 'none'
                          : 'all_comments')
                      }
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === 'none') {
                          update({
                            comment_filter: 'none',
                            switch_to_all_comments: false
                          });
                        } else {
                          update({
                            comment_filter: v,
                            switch_to_all_comments: true
                          });
                        }
                      }}
                    >
                      <option value='none'>
                        {tField('commentFilterKeep')}
                      </option>
                      <option value='most_relevant'>
                        {tField('commentFilterMostRelevant')}
                      </option>
                      <option value='newest'>
                        {tField('commentFilterNewest')}
                      </option>
                      <option value='all_comments'>
                        {tField('commentFilterAll')}
                      </option>
                    </select>
                  </F>
                  <F label={tField('waitAfterFilterSeconds')}>
                    <Input
                      type='number'
                      min={0}
                      step={0.1}
                      className='h-8 w-28 text-xs'
                      value={step.comment_filter_settle_s ?? 0.45}
                      onChange={(e) =>
                        update({
                          comment_filter_settle_s: Math.max(
                            0,
                            Number(e.target.value) || 0.45
                          )
                        })
                      }
                    />
                  </F>
                </>
              )}

              {step.type === 'social_open_comments' && (
                <>
                  <div className='rounded-md border border-amber-400/50 bg-amber-50/70 px-3 py-2.5 text-[11px] leading-relaxed text-amber-950 dark:border-amber-500/30 dark:bg-amber-950/30 dark:text-amber-100'>
                    <div className='mb-1 font-semibold'>
                      Legacy compound node
                    </div>
                    <div>
                      {tField('legacyCommentNodeHint')}
                      <code className='mx-1 rounded bg-amber-100 px-1 dark:bg-amber-900/50'>
                        {tField('legacyNodeFind')}
                      </code>
                      →
                      <code className='mx-1 rounded bg-amber-100 px-1 dark:bg-amber-900/50'>
                        {tField('legacyNodeTap')}
                      </code>
                      →
                      <code className='mx-1 rounded bg-amber-100 px-1 dark:bg-amber-900/50'>
                        {tField('legacyNodeFilter')}
                      </code>
                      →
                      <code className='mx-1 rounded bg-amber-100 px-1 dark:bg-amber-900/50'>
                        extract fb_comments
                      </code>
                      .
                    </div>
                  </div>
                  <StepPanelToggle
                    label={tField('skipWhenButtonMissing')}
                    description={tField('legacySkipHint')}
                    checked={step.ignore_error !== false}
                    onCheckedChange={(checked) =>
                      update({ ignore_error: checked })
                    }
                  />
                </>
              )}

              {step.type === 'tap_image' && (
                <TapImageFields
                  step={step}
                  update={update}
                  onRequestCropImage={onRequestCropImage}
                />
              )}

              {step.type === 'tap_position' && (
                <F label={tField('position')}>
                  <select
                    className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                    value={step.pos ?? 'middle_center'}
                    onChange={(e) => update({ pos: e.target.value })}
                  >
                    <option value='top_left'>{tField('posTopLeft')}</option>
                    <option value='top_center'>{tField('posTopCenter')}</option>
                    <option value='search_bar'>{tField('posSearchBar')}</option>
                    <option value='top_right'>{tField('posTopRight')}</option>
                    <option value='middle_left'>
                      {tField('posMiddleLeft')}
                    </option>
                    <option value='middle_center'>
                      {tField('posMiddleCenter')}
                    </option>
                    <option value='middle_right'>
                      {tField('posMiddleRight')}
                    </option>
                    <option value='bottom_left'>
                      {tField('posBottomLeft')}
                    </option>
                    <option value='bottom_center'>
                      {tField('posBottomCenter')}
                    </option>
                    <option value='bottom_right'>
                      {tField('posBottomRight')}
                    </option>
                  </select>
                </F>
              )}

              {step.type === 'loop' && (
                <F label={tField('loopConfig')}>
                  <LoopConfigFields
                    step={step}
                    onUpdate={update}
                    availableVariables={availableVariables}
                  />
                </F>
              )}

              {step.type === 'repeat' && (
                <>
                  <F label={tField('iterationCount')}>
                    <Input
                      type='number'
                      min={1}
                      className='h-8 w-24 text-xs'
                      value={step.count ?? 3}
                      onChange={(e) =>
                        update({ count: Number(e.target.value) })
                      }
                    />
                  </F>
                  <F label={tField('delayBetweenSeconds')}>
                    <Input
                      type='number'
                      min={0}
                      step={0.5}
                      className='h-8 w-24 text-xs'
                      value={step.delay_between ?? 0}
                      onChange={(e) =>
                        update({ delay_between: Number(e.target.value) })
                      }
                    />
                  </F>
                </>
              )}

              {step.type === 'repeat_until' && (
                <F label={tField('stopCondition')}>
                  <RepeatUntilFields
                    step={step}
                    onChange={(f, v) => update({ [f]: v } as Partial<FlowStep>)}
                    availableVariables={availableVariables}
                  />
                </F>
              )}

              {step.type === 'if_element' && (
                <>
                  <SelectorFields
                    step={step}
                    onChange={commitStep}
                    onRequestPickSelector={onRequestPickSelector}
                    availableVariables={availableVariables}
                    t={t}
                  />
                  <F label={tField('timeoutSeconds')}>
                    <Input
                      type='number'
                      min={0.1}
                      step={0.1}
                      className='h-8 w-24 text-xs'
                      value={step.timeout ?? 3}
                      onChange={(e) =>
                        update({
                          timeout: Math.max(0.1, Number(e.target.value) || 0.1)
                        })
                      }
                    />
                  </F>
                </>
              )}

              {step.type === 'if' && (
                <>
                  <p className='rounded bg-muted/60 px-2 py-1.5 text-[11px] text-muted-foreground'>
                    {tField('conditionJsonHint')}
                  </p>
                  <JsonTextarea
                    label='Condition JSON'
                    value={
                      step.condition ?? {
                        element_exists: { by: 'text', value: '' }
                      }
                    }
                    onCommit={(next) => update({ condition: next ?? {} })}
                  />
                </>
              )}

              {step.type === 'break_if' && (
                <>
                  <p className='rounded bg-muted/60 px-2 py-1.5 text-[11px] text-muted-foreground'>
                    {tField('breakLoopHint')}
                  </p>
                  <JsonTextarea
                    label='Condition JSON'
                    value={
                      step.condition ?? {
                        element_exists: { by: 'text', value: '' }
                      }
                    }
                    onCommit={(next) => update({ condition: next ?? {} })}
                  />
                </>
              )}

              {step.type === 'if_variable' && (
                <>
                  <F label={tIfVar('nameLabel')}>
                    <div className={valueInsertRowClassName()}>
                      <Input
                        className='h-9 min-w-0 flex-1 font-mono text-xs'
                        value={step.name ?? ''}
                        onChange={(e) => {
                          const name = e.target.value;
                          if (name === PLATFORM_SESSION_READY_VARIABLE) {
                            commitStep(
                              normalizeSystemVariableCondition({
                                ...stepRef.current,
                                name
                              })
                            );
                            return;
                          }
                          update({ name });
                        }}
                      />
                      <VariableNameSelect
                        availableVariables={availableVariables}
                        onSelect={(name) => update({ name })}
                      />
                    </div>
                    <IfVariableSourceHint name={step.name} t={variableInfoT} />
                  </F>
                  <F label={tIfVar('operatorLabel')}>
                    <select
                      className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                      disabled={step.name === PLATFORM_SESSION_READY_VARIABLE}
                      value={
                        step.name === PLATFORM_SESSION_READY_VARIABLE
                          ? 'equals'
                          : step.equals != null
                            ? 'equals'
                            : step.not_equals != null
                              ? 'not_equals'
                              : step.contains != null
                                ? 'contains'
                                : 'greater_than'
                      }
                      onChange={(e) => {
                        const val =
                          step.equals ??
                          step.not_equals ??
                          step.contains ??
                          step.greater_than ??
                          '';
                        const c: any = { ...step };
                        delete c.equals;
                        delete c.not_equals;
                        delete c.contains;
                        delete c.greater_than;
                        onChange({ ...c, [e.target.value]: val });
                      }}
                    >
                      <option value='equals'>{tIfVar('equals')}</option>
                      <option value='not_equals'>{tIfVar('notEquals')}</option>
                      <option value='contains'>{tIfVar('contains')}</option>
                      <option value='greater_than'>
                        {tIfVar('greaterThan')}
                      </option>
                    </select>
                  </F>
                  <F label={tIfVar('valueLabel')}>
                    {step.name === PLATFORM_SESSION_READY_VARIABLE ? (
                      <select
                        className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                        value={String(step.equals ?? true)}
                        onChange={(e) =>
                          update({ equals: e.target.value === 'true' })
                        }
                      >
                        <option value='true'>{tIfVar('true')}</option>
                        <option value='false'>{tIfVar('false')}</option>
                      </select>
                    ) : (
                      <div className={valueInsertRowClassName()}>
                        <Input
                          className='h-9 min-w-0 flex-1 text-xs'
                          value={
                            step.equals ??
                            step.not_equals ??
                            step.contains ??
                            step.greater_than ??
                            ''
                          }
                          onChange={(e) => {
                            const op =
                              step.equals != null
                                ? 'equals'
                                : step.not_equals != null
                                  ? 'not_equals'
                                  : step.contains != null
                                    ? 'contains'
                                    : 'greater_than';
                            update({ [op]: e.target.value });
                          }}
                        />
                        <VariableInsertSelect
                          availableVariables={availableVariables}
                          t={t}
                          onInsert={(token) => {
                            const op =
                              step.equals != null
                                ? 'equals'
                                : step.not_equals != null
                                  ? 'not_equals'
                                  : step.contains != null
                                    ? 'contains'
                                    : 'greater_than';
                            const current =
                              step.equals ??
                              step.not_equals ??
                              step.contains ??
                              step.greater_than ??
                              '';
                            update({
                              [op]: insertToken(String(current), token)
                            } as Partial<FlowStep>);
                          }}
                        />
                      </div>
                    )}
                  </F>
                </>
              )}

              {step.type === 'set_variable' && (
                <>
                  <F label={t('setVariable.varNameLabel')}>
                    <Input
                      className='h-9 font-mono text-sm'
                      value={step.name ?? ''}
                      onChange={(e) => update({ name: e.target.value })}
                      placeholder={t('setVariable.varNamePlaceholder')}
                    />
                  </F>
                  <F label={t('setVariable.valueLabel')}>
                    <div className={valueInsertRowClassName()}>
                      <Input
                        className='h-9 min-w-0 flex-1 font-mono text-sm'
                        value={step.value ?? ''}
                        onChange={(e) => update({ value: e.target.value })}
                        placeholder={t('setVariable.valuePlaceholder', {
                          varToken: SCENARIO_VAR_TOKENS.VAR
                        })}
                      />
                      <VariableInsertSelect
                        availableVariables={availableVariables}
                        t={t}
                        onInsert={(token) =>
                          update({
                            value: insertToken(step.value ?? '', token)
                          })
                        }
                      />
                    </div>
                  </F>
                  <F label={t('setVariable.randomListLabel')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-9 text-sm'
                      value={keywordInputValue(step.from_list)}
                      placeholder={t('setVariable.randomListPlaceholder')}
                      onValueChange={(value) =>
                        update({
                          from_list: isVarRef(value.trim())
                            ? value.trim()
                            : value
                                .split(',')
                                .map((s: string) => s.trim())
                                .filter(Boolean)
                        })
                      }
                    />
                  </F>
                  <div className='rounded-md border border-dashed border-border/70 bg-muted/25 px-2.5 py-2'>
                    <p className='mb-1.5 text-[11px] font-medium text-muted-foreground'>
                      {t('setVariable.builtinHint')}
                    </p>
                    <div className='flex flex-wrap gap-1'>
                      {BUILTIN_VARIABLE_TOKENS.map((token) => (
                        <code
                          key={token}
                          className='rounded bg-background/80 px-1.5 py-0.5 font-mono text-[10px] text-foreground shadow-sm ring-1 ring-border/60'
                        >
                          {token}
                        </code>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {step.type === 'set_var' && (
                <>
                  <F label='Key'>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.key ?? ''}
                      onChange={(e) => update({ key: e.target.value })}
                      placeholder='my_key'
                    />
                  </F>
                  <F label={tField('valueJsonOrText')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 font-mono text-xs'
                      value={
                        typeof step.value === 'string'
                          ? step.value
                          : JSON.stringify(step.value ?? '')
                      }
                      onValueChange={(raw) => {
                        try {
                          update({ value: JSON.parse(raw) });
                        } catch {
                          update({ value: raw });
                        }
                      }}
                    />
                  </F>
                </>
              )}

              {step.type === 'double_tap' && (
                <>
                  <F label={tField('coordinateSystem')}>
                    <select
                      className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={doubleTapCoordMode}
                      onChange={(e) => {
                        const mode = e.target.value;
                        if (mode === 'ratio')
                          update({
                            rx: step.rx ?? 0.5,
                            ry: step.ry ?? 0.5,
                            x: undefined,
                            y: undefined
                          });
                        else
                          update({
                            x: step.x ?? 500,
                            y: step.y ?? 900,
                            rx: undefined,
                            ry: undefined
                          });
                      }}
                    >
                      <option value='ratio'>Ratio (0-1)</option>
                      <option value='absolute'>Absolute px</option>
                    </select>
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    {doubleTapCoordMode === 'ratio' ? (
                      <>
                        <F label='X (0-1)'>
                          <Input
                            type='number'
                            min={0}
                            max={1}
                            step={0.01}
                            className='h-8 text-xs'
                            value={step.rx ?? 0.5}
                            onChange={(e) =>
                              update({
                                rx: parseFloat(e.target.value) || 0,
                                x: undefined
                              })
                            }
                          />
                        </F>
                        <F label='Y (0-1)'>
                          <Input
                            type='number'
                            min={0}
                            max={1}
                            step={0.01}
                            className='h-8 text-xs'
                            value={step.ry ?? 0.5}
                            onChange={(e) =>
                              update({
                                ry: parseFloat(e.target.value) || 0,
                                y: undefined
                              })
                            }
                          />
                        </F>
                      </>
                    ) : (
                      <>
                        <F label='X (px)'>
                          <Input
                            type='number'
                            min={0}
                            step={1}
                            className='h-8 text-xs'
                            value={step.x ?? 500}
                            onChange={(e) =>
                              update({
                                x: Number(e.target.value) || 0,
                                rx: undefined
                              })
                            }
                          />
                        </F>
                        <F label='Y (px)'>
                          <Input
                            type='number'
                            min={0}
                            step={1}
                            className='h-8 text-xs'
                            value={step.y ?? 900}
                            onChange={(e) =>
                              update({
                                y: Number(e.target.value) || 0,
                                ry: undefined
                              })
                            }
                          />
                        </F>
                      </>
                    )}
                  </div>
                  <F label={tField('waitAfterDoubleTapSeconds')}>
                    <Input
                      type='number'
                      min={0}
                      step={0.1}
                      className='h-8 w-28 text-xs'
                      value={step.wait_after ?? 0.5}
                      onChange={(e) =>
                        update({ wait_after: Number(e.target.value) || 0 })
                      }
                    />
                  </F>
                </>
              )}

              {step.type === 'pinch' && (
                <>
                  <F label={tField('scaleRatio')}>
                    <Input
                      type='number'
                      min={0.1}
                      max={5}
                      step={0.1}
                      className='h-8 text-xs'
                      value={step.scale ?? 0.5}
                      onChange={(e) =>
                        update({ scale: parseFloat(e.target.value) || 0.5 })
                      }
                    />
                  </F>
                  <F label={tField('centerCoordinateSystem')}>
                    <select
                      className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={pinchCoordMode}
                      onChange={(e) => {
                        const mode = e.target.value;
                        if (mode === 'ratio')
                          update({
                            rx: step.rx ?? 0.5,
                            ry: step.ry ?? 0.5,
                            cx: undefined,
                            cy: undefined
                          });
                        else
                          update({
                            cx: step.cx ?? 500,
                            cy: step.cy ?? 900,
                            rx: undefined,
                            ry: undefined
                          });
                      }}
                    >
                      <option value='ratio'>Ratio (0-1)</option>
                      <option value='absolute'>Absolute px</option>
                    </select>
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    {pinchCoordMode === 'ratio' ? (
                      <>
                        <F label={tField('centerX01')}>
                          <Input
                            type='number'
                            min={0}
                            max={1}
                            step={0.01}
                            className='h-8 text-xs'
                            value={step.rx ?? 0.5}
                            onChange={(e) =>
                              update({
                                rx: parseFloat(e.target.value) || 0.5,
                                cx: undefined
                              })
                            }
                          />
                        </F>
                        <F label={tField('centerY01')}>
                          <Input
                            type='number'
                            min={0}
                            max={1}
                            step={0.01}
                            className='h-8 text-xs'
                            value={step.ry ?? 0.5}
                            onChange={(e) =>
                              update({
                                ry: parseFloat(e.target.value) || 0.5,
                                cy: undefined
                              })
                            }
                          />
                        </F>
                      </>
                    ) : (
                      <>
                        <F label={tField('centerXPx')}>
                          <Input
                            type='number'
                            min={0}
                            step={1}
                            className='h-8 text-xs'
                            value={step.cx ?? 500}
                            onChange={(e) =>
                              update({
                                cx: Number(e.target.value) || 0,
                                rx: undefined
                              })
                            }
                          />
                        </F>
                        <F label={tField('centerYPx')}>
                          <Input
                            type='number'
                            min={0}
                            step={1}
                            className='h-8 text-xs'
                            value={step.cy ?? 900}
                            onChange={(e) =>
                              update({
                                cy: Number(e.target.value) || 0,
                                ry: undefined
                              })
                            }
                          />
                        </F>
                      </>
                    )}
                  </div>
                  <F label={tField('pinchMs')}>
                    <Input
                      type='number'
                      min={50}
                      className='h-8 w-28 text-xs'
                      value={step.duration_ms ?? 400}
                      onChange={(e) =>
                        update({ duration_ms: Number(e.target.value) || 400 })
                      }
                    />
                  </F>
                </>
              )}

              {step.type === 'drag' && (
                <>
                  <F label={tField('coordinateSystem')}>
                    <select
                      className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={dragCoordMode}
                      onChange={(e) => {
                        const mode = e.target.value;
                        if (mode === 'ratio') {
                          update({
                            rx1: step.rx1 ?? 0.5,
                            ry1: step.ry1 ?? 0.3,
                            rx2: step.rx2 ?? 0.5,
                            ry2: step.ry2 ?? 0.7,
                            x1: undefined,
                            y1: undefined,
                            x2: undefined,
                            y2: undefined
                          });
                        } else {
                          update({
                            x1: step.x1 ?? 500,
                            y1: step.y1 ?? 700,
                            x2: step.x2 ?? 500,
                            y2: step.y2 ?? 1300,
                            rx1: undefined,
                            ry1: undefined,
                            rx2: undefined,
                            ry2: undefined
                          });
                        }
                      }}
                    >
                      <option value='ratio'>Ratio (0-1)</option>
                      <option value='absolute'>Absolute px</option>
                    </select>
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    {dragCoordMode === 'ratio' ? (
                      <>
                        <F label={tField('fromX01')}>
                          <Input
                            type='number'
                            min={0}
                            max={1}
                            step={0.01}
                            className='h-8 text-xs'
                            value={step.rx1 ?? 0.5}
                            onChange={(e) =>
                              update({
                                rx1: parseFloat(e.target.value) || 0,
                                x1: undefined
                              })
                            }
                          />
                        </F>
                        <F label={tField('fromY01')}>
                          <Input
                            type='number'
                            min={0}
                            max={1}
                            step={0.01}
                            className='h-8 text-xs'
                            value={step.ry1 ?? 0.3}
                            onChange={(e) =>
                              update({
                                ry1: parseFloat(e.target.value) || 0,
                                y1: undefined
                              })
                            }
                          />
                        </F>
                        <F label={tField('toX01')}>
                          <Input
                            type='number'
                            min={0}
                            max={1}
                            step={0.01}
                            className='h-8 text-xs'
                            value={step.rx2 ?? 0.5}
                            onChange={(e) =>
                              update({
                                rx2: parseFloat(e.target.value) || 0,
                                x2: undefined
                              })
                            }
                          />
                        </F>
                        <F label={tField('toY01')}>
                          <Input
                            type='number'
                            min={0}
                            max={1}
                            step={0.01}
                            className='h-8 text-xs'
                            value={step.ry2 ?? 0.7}
                            onChange={(e) =>
                              update({
                                ry2: parseFloat(e.target.value) || 0,
                                y2: undefined
                              })
                            }
                          />
                        </F>
                      </>
                    ) : (
                      <>
                        <F label={tField('fromXPx')}>
                          <Input
                            type='number'
                            min={0}
                            step={1}
                            className='h-8 text-xs'
                            value={step.x1 ?? 500}
                            onChange={(e) =>
                              update({
                                x1: Number(e.target.value) || 0,
                                rx1: undefined
                              })
                            }
                          />
                        </F>
                        <F label={tField('fromYPx')}>
                          <Input
                            type='number'
                            min={0}
                            step={1}
                            className='h-8 text-xs'
                            value={step.y1 ?? 700}
                            onChange={(e) =>
                              update({
                                y1: Number(e.target.value) || 0,
                                ry1: undefined
                              })
                            }
                          />
                        </F>
                        <F label={tField('toXPx')}>
                          <Input
                            type='number'
                            min={0}
                            step={1}
                            className='h-8 text-xs'
                            value={step.x2 ?? 500}
                            onChange={(e) =>
                              update({
                                x2: Number(e.target.value) || 0,
                                rx2: undefined
                              })
                            }
                          />
                        </F>
                        <F label={tField('toYPx')}>
                          <Input
                            type='number'
                            min={0}
                            step={1}
                            className='h-8 text-xs'
                            value={step.y2 ?? 1300}
                            onChange={(e) =>
                              update({
                                y2: Number(e.target.value) || 0,
                                ry2: undefined
                              })
                            }
                          />
                        </F>
                      </>
                    )}
                  </div>
                  <F label={tField('durationMs')}>
                    <Input
                      type='number'
                      min={200}
                      className='h-8 w-28 text-xs'
                      value={step.duration_ms ?? 1000}
                      onChange={(e) =>
                        update({ duration_ms: Number(e.target.value) })
                      }
                    />
                  </F>
                </>
              )}

              {step.type === 'extract' && (
                <ExtractStepFields
                  step={step}
                  update={update}
                  onChange={commitStep}
                  view='screen'
                  availableVariables={availableVariables}
                />
              )}

              {step.type === 'extract_text_hierarchy' && (
                <>
                  <F label='save_as'>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.save_as ?? 'texts'}
                      onChange={(e) =>
                        update({ save_as: e.target.value || undefined })
                      }
                    />
                  </F>
                  <F label='format'>
                    <select
                      className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={step.format ?? 'text'}
                      onChange={(e) => update({ format: e.target.value })}
                    >
                      <option value='text'>text</option>
                      <option value='json'>json</option>
                    </select>
                  </F>
                  <F label='filter_class'>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.filter_class ?? ''}
                      onChange={(e) =>
                        update({ filter_class: e.target.value || undefined })
                      }
                    />
                  </F>
                  <StepPanelToggle
                    label='exclude_empty'
                    checked={step.exclude_empty ?? true}
                    onCheckedChange={(checked) =>
                      update({ exclude_empty: checked })
                    }
                  />
                </>
              )}

              {step.type === 'extract_text_ocr' && (
                <>
                  <StepPanelHint>{tOcr('hint')}</StepPanelHint>
                  <F label={tOcr('saveAs')}>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.save_as ?? 'ocr_text'}
                      placeholder='ocr_text'
                      onChange={(e) =>
                        update({ save_as: e.target.value || undefined })
                      }
                    />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tOcr('language')}>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.language ?? 'vie+eng'}
                        placeholder='vie+eng'
                        onChange={(e) =>
                          update({ language: e.target.value || 'vie+eng' })
                        }
                      />
                    </F>
                    <F label={tOcr('confidence')}>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.05}
                        className='h-8 text-xs'
                        value={step.confidence_threshold ?? 0.5}
                        onChange={(e) =>
                          update({
                            confidence_threshold: Math.min(
                              1,
                              Math.max(0, Number(e.target.value) || 0.5)
                            )
                          })
                        }
                      />
                    </F>
                  </div>
                  <OcrRegionField
                    region={step.region}
                    onChange={(next) => update({ region: next })}
                    onRequestPickRegion={onRequestPickRegion}
                  />
                </>
              )}

              {step.type === 'extract_text_ai' && (
                <>
                  <F label='save_as'>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.save_as ?? 'ai_text'}
                      onChange={(e) =>
                        update({ save_as: e.target.value || undefined })
                      }
                    />
                  </F>
                  <F label='prompt'>
                    <VariableTextarea
                      availableVariables={availableVariables}
                      t={t}
                      value={step.prompt ?? ''}
                      onValueChange={(value) => update({ prompt: value })}
                    />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label='provider'>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.provider ?? 'openai'}
                        onChange={(e) =>
                          update({ provider: e.target.value || 'openai' })
                        }
                      />
                    </F>
                    <F label='format'>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.format ?? 'json'}
                        onChange={(e) =>
                          update({ format: e.target.value || 'json' })
                        }
                      />
                    </F>
                    <F label='model'>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.model ?? ''}
                        onChange={(e) =>
                          update({ model: e.target.value || undefined })
                        }
                      />
                    </F>
                  </div>
                  <JsonTextarea
                    label='region (JSON)'
                    value={step.region}
                    onCommit={(next) => update({ region: next })}
                    placeholder='{"x":0,"y":0,"w":100,"h":100}'
                  />
                </>
              )}

              {step.type === 'extract_screen_data' && (
                <>
                  <F label='save_as'>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.save_as ?? 'screen_data'}
                      onChange={(e) =>
                        update({ save_as: e.target.value || undefined })
                      }
                    />
                  </F>
                  <F label='strategy'>
                    <select
                      className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={step.strategy ?? 'auto'}
                      onChange={(e) => update({ strategy: e.target.value })}
                    >
                      <option value='auto'>auto</option>
                      <option value='ocr'>ocr</option>
                      <option value='hierarchy'>hierarchy</option>
                      <option value='ai'>ai</option>
                    </select>
                  </F>
                  <JsonTextarea
                    label='schema (JSON)'
                    value={step.schema}
                    onCommit={(next) => update({ schema: next })}
                  />
                </>
              )}

              {step.type === 'save_extraction' && (
                <>
                  <F label={t('saveExtraction.dataVarLabel')}>
                    <Input
                      className='h-8 font-mono text-xs'
                      placeholder='comments | posts | text_nodes'
                      value={step.data_var ?? ''}
                      onChange={(e) => update({ data_var: e.target.value })}
                    />
                    <p className='mt-1 text-[10px] text-muted-foreground'>
                      {t('saveExtraction.dataVarHint')}
                    </p>
                  </F>
                  <F label={t('saveExtraction.collectionLabel')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 font-mono text-xs'
                      placeholder={tField('phCollection', {
                        token: '${SAVE_COLLECTION}'
                      })}
                      value={step.collection ?? ''}
                      onValueChange={(value) => update({ collection: value })}
                    />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={t('saveExtraction.platformLabel')}>
                      <Input
                        className='h-8 text-xs'
                        placeholder='facebook'
                        value={step.platform ?? ''}
                        onChange={(e) =>
                          update({ platform: e.target.value || undefined })
                        }
                      />
                    </F>
                    <F label={t('saveExtraction.contentTypeLabel')}>
                      <Input
                        className='h-8 text-xs'
                        placeholder='fb_post'
                        value={step.content_type ?? ''}
                        onChange={(e) =>
                          update({ content_type: e.target.value || undefined })
                        }
                      />
                    </F>
                  </div>
                  <F label={t('saveExtraction.dedupeFieldLabel')}>
                    <Input
                      className='h-8 font-mono text-xs'
                      placeholder='comment_key | post_key | text'
                      value={step.dedupe_field ?? ''}
                      onChange={(e) =>
                        update({ dedupe_field: e.target.value || undefined })
                      }
                    />
                    <p className='mt-1 text-[10px] text-muted-foreground'>
                      {t('saveExtraction.dedupeFieldHint')}
                    </p>
                  </F>
                  <F label={t('saveExtraction.tagsLabel')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      placeholder='group,crawl,${GROUP_NAME}'
                      value={step.tags ?? ''}
                      onValueChange={(value) =>
                        update({ tags: value || undefined })
                      }
                    />
                    <p className='mt-1 text-[10px] text-muted-foreground'>
                      {t('saveExtraction.tagsHint')}
                    </p>
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={t('saveExtraction.parentIdVarLabel')}>
                      <select
                        className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                        value={parentLinkMode}
                        onChange={(e) => {
                          const mode = e.target.value;
                          if (mode === 'auto') {
                            update({
                              parent_id_var: '_active_comment_parent_hash'
                            });
                          } else if (mode === 'none') {
                            update({ parent_id_var: undefined });
                          } else {
                            update({ parent_id_var: step.parent_id_var || '' });
                          }
                        }}
                      >
                        <option value='auto'>
                          {t('saveExtraction.parentLinkModeAuto')}
                        </option>
                        <option value='custom'>
                          {t('saveExtraction.parentLinkModeCustom')}
                        </option>
                        <option value='none'>
                          {t('saveExtraction.parentLinkModeNone')}
                        </option>
                      </select>
                      {parentLinkMode === 'custom' && (
                        <Input
                          className='mt-1 h-8 font-mono text-xs'
                          placeholder='_active_comment_parent_hash'
                          value={step.parent_id_var ?? ''}
                          onChange={(e) =>
                            update({
                              parent_id_var: e.target.value || undefined
                            })
                          }
                        />
                      )}
                      <p className='mt-1 text-[10px] text-muted-foreground'>
                        {t('saveExtraction.parentIdVarHint')}
                      </p>
                    </F>
                    <F label={t('saveExtraction.itemLevelLabel')}>
                      <select
                        className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                        value={String(step.item_level ?? 0)}
                        onChange={(e) =>
                          update({ item_level: Number(e.target.value) || 0 })
                        }
                      >
                        <option value='0'>
                          {t('saveExtraction.itemLevelPost')}
                        </option>
                        <option value='1'>
                          {t('saveExtraction.itemLevelComment')}
                        </option>
                        <option value='2'>
                          {t('saveExtraction.itemLevelReply')}
                        </option>
                      </select>
                    </F>
                  </div>
                </>
              )}

              {step.type === 'take_screenshot' && (
                <F label={tField('saveToPath')}>
                  <VariableTextInput
                    availableVariables={availableVariables}
                    t={t}
                    className='h-8 font-mono text-xs'
                    value={step.save_path ?? ''}
                    onValueChange={(value) =>
                      update({ save_path: value || undefined })
                    }
                    placeholder='/sdcard/screen.jpg'
                  />
                </F>
              )}

              {step.type === 'set_clipboard' && (
                <F label={tField('clipboardContent')}>
                  <VariableTextInput
                    availableVariables={availableVariables}
                    t={t}
                    className='h-8 text-xs'
                    value={step.text ?? ''}
                    onValueChange={(value) => update({ text: value })}
                    placeholder={tField('phTextToCopy')}
                  />
                </F>
              )}

              {step.type === 'use_source_pool' && (
                <div className='space-y-3'>
                  <StepPanelHint>{tField('targetTypeHint')}</StepPanelHint>
                  <div className='grid gap-3 sm:grid-cols-2'>
                    <F label='Platform'>
                      <Input
                        className='h-8 text-xs'
                        value={step.platform ?? 'facebook'}
                        onChange={(e) =>
                          update({ platform: e.target.value || 'facebook' })
                        }
                      />
                    </F>
                    <F label={tField('targetType')}>
                      <select
                        className='h-8 w-full rounded-md border border-input bg-background px-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring'
                        value={step.entity_type ?? 'group'}
                        onChange={(event) => {
                          const entityType = event.target.value;
                          const currentPrefix = String(
                            step.output_prefix || 'GROUP'
                          ).toUpperCase();
                          update({
                            entity_type: entityType,
                            output_prefix: [
                              'GROUP',
                              'PAGE',
                              'PROFILE'
                            ].includes(currentPrefix)
                              ? entityType.toUpperCase()
                              : step.output_prefix
                          });
                        }}
                      >
                        <option value='group'>Group</option>
                        <option value='page'>Page</option>
                        <option value='profile'>
                          {tField('targetTypeProfile')}
                        </option>
                      </select>
                    </F>
                  </div>
                  <F label={tField('filterByTargetName')}>
                    <VariableTextInput
                      availableVariables={availableVariables}
                      t={t}
                      className='h-8 text-xs'
                      value={step.search ?? ''}
                      onValueChange={(value) =>
                        update({ search: value || undefined })
                      }
                      placeholder={tField('phTargetName')}
                    />
                  </F>
                  <F label={tField('outputVarPrefix')}>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.output_prefix ?? 'GROUP'}
                      onChange={(e) =>
                        update({ output_prefix: e.target.value || undefined })
                      }
                      placeholder='GROUP'
                    />
                  </F>
                  <div className='rounded-md border bg-muted/30 p-2 font-mono text-[11px] leading-5 text-muted-foreground'>
                    {(() => {
                      const prefix =
                        String(step.output_prefix || 'GROUP')
                          .trim()
                          .toUpperCase() || 'GROUP';
                      const safePrefix =
                        prefix
                          .replace(/[^A-Z0-9_]/g, '_')
                          .replace(/^_+|_+$/g, '') || 'GROUP';
                      return `\${${safePrefix}_NAME} · \${${safePrefix}_URL} · \${${safePrefix}_SEARCH_QUERY} · \${${safePrefix}_SELECTOR_VALUE}`;
                    })()}
                  </div>
                </div>
              )}

              {step.type === 'lease_source_target' && (
                <div className='space-y-3'>
                  <StepPanelHint>{t('leaseTarget.sourceHint')}</StepPanelHint>
                  <div className='grid gap-3 sm:grid-cols-2'>
                    <F label={t('leaseTarget.platform')}>
                      <Input
                        className='h-8 text-xs'
                        value={step.platform ?? 'facebook'}
                        onChange={(event) =>
                          update({ platform: event.target.value || 'facebook' })
                        }
                      />
                    </F>
                    <F label={t('leaseTarget.entityType')}>
                      <select
                        className='h-8 w-full rounded-md border border-input bg-background px-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring'
                        value={step.entity_type ?? 'post'}
                        onChange={(event) =>
                          update({ entity_type: event.target.value })
                        }
                      >
                        <option value='post'>{t('leaseTarget.post')}</option>
                        <option value='page'>{t('leaseTarget.page')}</option>
                        <option value='profile'>
                          {t('leaseTarget.profile')}
                        </option>
                      </select>
                    </F>
                  </div>
                  <div className='grid gap-3 sm:grid-cols-2'>
                    <F label={t('leaseTarget.action')}>
                      <select
                        className='h-8 w-full rounded-md border border-input bg-background px-3 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring'
                        value={step.action ?? 'like'}
                        onChange={(event) =>
                          update({ action: event.target.value })
                        }
                      >
                        <option value='like'>{t('leaseTarget.like')}</option>
                        <option value='comment'>
                          {t('leaseTarget.comment')}
                        </option>
                        <option value='share'>{t('leaseTarget.share')}</option>
                      </select>
                    </F>
                    <F label={t('leaseTarget.keywords')}>
                      <VariableTextInput
                        availableVariables={availableVariables}
                        t={t}
                        className='h-8 text-xs'
                        value={keywordInputValue(step.keywords)}
                        onValueChange={(value) => update({ keywords: value })}
                        placeholder={t('leaseTarget.keywordPlaceholder')}
                      />
                    </F>
                  </div>
                  <div className='rounded-md border bg-muted/30 p-2 font-mono text-[11px] leading-5 text-muted-foreground'>
                    TARGET_AVAILABLE · TARGET_ACTION_ID · TARGET_ENTITY_ID ·
                    TARGET_NAME · TARGET_SEARCH_TEXT · TARGET_URL
                  </div>
                </div>
              )}

              {step.type === 'lease_connection_candidate' && (
                <div className='space-y-3'>
                  <StepPanelHint>
                    {t('leaseTarget.connectionHint')}
                  </StepPanelHint>
                  <div className='rounded-md border bg-muted/30 p-2 font-mono text-[11px] leading-5 text-muted-foreground'>
                    CANDIDATE_AVAILABLE · CANDIDATE_NAME · CANDIDATE_LEASE_TOKEN
                    · TARGET_ENTITY_ID
                  </div>
                </div>
              )}

              {step.type === 'run_scenario' && (
                <div className='space-y-3'>
                  <StepPanelHint>{t('runScenario.intro')}</StepPanelHint>
                  <RunScenarioFields
                    layout='panel'
                    step={step}
                    campaignScenarios={campaignScenarios}
                    availableVariables={availableVariables}
                    onPatch={(p) => {
                      const merged = { ...step } as Record<string, unknown>;
                      for (const [k, v] of Object.entries(p)) {
                        if (v === undefined) delete merged[k];
                        else merged[k] = v;
                      }
                      onChange(merged as FlowStep);
                    }}
                  />
                </div>
              )}
            </StepPanelSection>
          </TabsContent>

          {isExtractStep ? (
            <TabsContent value='data-save' className='mt-0 space-y-3'>
              <StepPanelSection title={t('tabs.dataSave')}>
                <ExtractStepFields
                  step={step}
                  update={update}
                  onChange={commitStep}
                  view='data-save'
                  availableVariables={availableVariables}
                />
              </StepPanelSection>
            </TabsContent>
          ) : null}

          <TabsContent value='settings' className='mt-0 space-y-3'>
            <StepErrorPolicySection step={step} update={update} />
            <StepRetryPolicySection step={step} update={update} />
          </TabsContent>
        </Tabs>
      </div>

      <div className='shrink-0 border-t border-border/70 bg-background/95 p-2.5 backdrop-blur'>
        <div className='space-y-2'>
          <p className='text-[10px] leading-snug text-muted-foreground'>
            {nextSetupTab ? tSetup('footerNextHint') : tSetup('footerDoneHint')}
          </p>
          <div
            className={cn(
              'grid gap-2',
              nextSetupTab ? 'grid-cols-2' : 'grid-cols-1'
            )}
          >
            {nextSetupTab ? (
              <Button
                type='button'
                variant='outline'
                size='sm'
                className='h-8 min-w-0 text-xs'
                onClick={() => setSetupTab(nextSetupTab.value)}
              >
                {tSetup('next')}
              </Button>
            ) : null}
            <Button
              type='button'
              size='sm'
              className='h-8 min-w-0 text-xs'
              onClick={handleDoneAndClose}
            >
              {tSetup('done')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
