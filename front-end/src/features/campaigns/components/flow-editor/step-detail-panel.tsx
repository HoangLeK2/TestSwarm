'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Crop as CropIcon,
  Monitor,
  MousePointerClick,
  Move,
  ShieldCheck
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
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

/** Value field + variable insert: stacks on narrow widths so the select never squeezes the input. */
function valueInsertRowClassName() {
  return 'flex min-w-0 flex-col gap-2 sm:flex-row sm:items-stretch sm:gap-2';
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
  const [selection, setSelection] = useState('');
  return (
    <select
      className='h-9 w-full shrink-0 rounded-md border border-input bg-background px-2 py-1.5 text-xs shadow-sm sm:w-[13rem]'
      value={selection}
      onChange={(e) => {
        const token = e.target.value;
        if (!token) return;
        onInsert(token);
        setSelection('');
      }}
    >
      <option value=''>{t('variableInsert.placeholder')}</option>
      {availableVariables.length > 0 && (
        <optgroup label={t('variableInsert.availableVariables')}>
          {availableVariables.map((name) => {
            const token = `\${${name}}`;
            return (
              <option key={name} value={token}>
                {token}
              </option>
            );
          })}
        </optgroup>
      )}
      <optgroup label={t('variableInsert.builtinVariables')}>
        {BUILTIN_VARIABLE_TOKENS.map((token) => (
          <option key={token} value={token}>
            {token}
          </option>
        ))}
      </optgroup>
      <optgroup label={t('variableInsert.sourcePoolVariables')}>
        {SOURCE_POOL_VARIABLE_TOKENS.map((token) => (
          <option key={token} value={token}>
            {token}
          </option>
        ))}
      </optgroup>
    </select>
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

export function StepDetailPanel({
  step: stepProp,
  onChange,
  onClose: _onClose,
  availableVariables = [],
  onRequestPickSelector,
  onRequestPickTapCoords,
  onRequestPickSwipeCoords,
  onRequestCropImage,
  onRequestPickRegion,
  campaignScenarios = [],
  runtimeContext
}: Props) {
  const t = useTranslations('campaignsFeature.stepEditor');
  const tField = useTranslations('campaignsFeature.stepEditor.stepFields');
  const tApp = useTranslations('campaignsFeature.stepEditor.appLifecycle');
  const tSec = useTranslations('campaignsFeature.stepEditor.sections');
  const tSel = useTranslations('campaignsFeature.stepEditor.selector');
  const tIfVar = useTranslations('campaignsFeature.stepEditor.ifVariable');
  const tTarget = useTranslations('campaignsFeature.stepEditor.selectTarget');
  const tOcr = useTranslations('campaignsFeature.stepEditor.ocr');
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
  return (
    <div className='flex flex-col bg-card'>
      <StepPanelHeader step={step} />

      <div className='max-h-[70vh] space-y-4 overflow-y-auto p-3 sm:p-4'>
        <StepPanelMetaFields step={step} commitStep={commitStep} t={t} />

        <Tabs
          defaultValue={isExtractStep ? 'screen' : 'action'}
          className='space-y-3'
        >
          <TabsList
            className={
              isExtractStep
                ? 'grid h-9 w-full grid-cols-3'
                : 'grid h-9 w-full grid-cols-2'
            }
          >
            <TabsTrigger
              value={isExtractStep ? 'screen' : 'action'}
              className='text-xs'
            >
              {isExtractStep ? t('tabs.screen') : t('tabs.action')}
            </TabsTrigger>
            {isExtractStep ? (
              <TabsTrigger value='data-save' className='text-xs'>
                {t('tabs.dataSave')}
              </TabsTrigger>
            ) : null}
            <TabsTrigger value='settings' className='text-xs'>
              {t('tabs.settings')}
            </TabsTrigger>
          </TabsList>

          <TabsContent
            value={isExtractStep ? 'screen' : 'action'}
            className='mt-0 space-y-3'
          >
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
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.local_path ?? ''}
                      onChange={(e) => update({ local_path: e.target.value })}
                      placeholder={tApp('placeholderLocal')}
                    />
                  </F>
                  <F
                    label={
                      step.type === 'push_file'
                        ? tApp('remotePathPush')
                        : tApp('remotePathPull')
                    }
                  >
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.remote_path ?? ''}
                      onChange={(e) => update({ remote_path: e.target.value })}
                      placeholder={tApp('placeholderRemote')}
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
                    <div className='flex items-center gap-2'>
                      <Input
                        className='h-8 text-xs'
                        value={step.text ?? ''}
                        onChange={(e) => update({ text: e.target.value })}
                      />
                      <VariableInsertSelect
                        availableVariables={availableVariables}
                        t={t}
                        onInsert={(token) =>
                          update({ text: insertToken(step.text ?? '', token) })
                        }
                      />
                    </div>
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
                    <div className='flex items-center gap-2'>
                      <Input
                        className='h-8 text-xs'
                        value={step.text ?? ''}
                        onChange={(e) => update({ text: e.target.value })}
                      />
                      <VariableInsertSelect
                        availableVariables={availableVariables}
                        t={t}
                        onInsert={(token) =>
                          update({ text: insertToken(step.text ?? '', token) })
                        }
                      />
                    </div>
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
                <>
                  <F label={tField('screenshotInput')}>
                    <textarea
                      className='min-h-[92px] w-full rounded border bg-background px-2 py-1.5 font-mono text-xs'
                      value={step.screenshot ?? ''}
                      onChange={(e) => update({ screenshot: e.target.value })}
                    />
                  </F>
                  <div className='grid grid-cols-3 gap-2'>
                    <F label='ssim_threshold'>
                      <Input
                        type='number'
                        min={0}
                        max={1}
                        step={0.01}
                        className='h-8 text-xs'
                        value={step.ssim_threshold ?? 0.75}
                        onChange={(e) =>
                          update({
                            ssim_threshold: Number(e.target.value) || 0.75
                          })
                        }
                      />
                    </F>
                    <F label='timeout'>
                      <Input
                        type='number'
                        min={0.1}
                        step={0.1}
                        className='h-8 text-xs'
                        value={step.timeout ?? 8}
                        onChange={(e) =>
                          update({
                            timeout: Math.max(
                              0.1,
                              Number(e.target.value) || 0.1
                            )
                          })
                        }
                      />
                    </F>
                    <F label='poll'>
                      <Input
                        type='number'
                        min={0.1}
                        step={0.1}
                        className='h-8 text-xs'
                        value={step.poll ?? 0.5}
                        onChange={(e) =>
                          update({
                            poll: Math.max(0.1, Number(e.target.value) || 0.1)
                          })
                        }
                      />
                    </F>
                  </div>
                  <F label={tField('openedProfileVar')}>
                    <Input
                      className='h-8 font-mono text-xs'
                      value={step.save_opened_as ?? 'AUTHOR_PROFILE_OPENED'}
                      onChange={(e) =>
                        update({
                          save_opened_as:
                            e.target.value || 'AUTHOR_PROFILE_OPENED'
                        })
                      }
                    />
                  </F>
                </>
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
                    <Input
                      className='h-8 text-xs'
                      value={step.search ?? ''}
                      placeholder={
                        step.target_type === 'post'
                          ? '${POST_SEARCH}'
                          : '${PEOPLE_SEARCH}'
                      }
                      onChange={(e) =>
                        update({ search: e.target.value || undefined })
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
                    <Input
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
                      onChange={(e) =>
                        update(
                          step.target_type === 'post'
                            ? { display_text: e.target.value || undefined }
                            : { display_name: e.target.value || undefined }
                        )
                      }
                    />
                  </F>
                  <F label={tField('requiredKeywords')}>
                    <Input
                      className='h-8 text-xs'
                      value={keywordInputValue(step.required_keywords)}
                      placeholder='Hoang Le, OpenAI'
                      onChange={(e) =>
                        update({
                          required_keywords: keywordListFromInput(
                            e.target.value
                          )
                        })
                      }
                    />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tField('bonusKeywords')}>
                      <Input
                        className='h-8 text-xs'
                        value={keywordInputValue(step.optional_keywords)}
                        placeholder='company, city'
                        onChange={(e) =>
                          update({
                            optional_keywords: keywordListFromInput(
                              e.target.value
                            )
                          })
                        }
                      />
                    </F>
                    <F label={tField('blockedKeywords')}>
                      <Input
                        className='h-8 text-xs'
                        value={keywordInputValue(step.forbidden_keywords)}
                        placeholder='fake, page'
                        onChange={(e) =>
                          update({
                            forbidden_keywords: keywordListFromInput(
                              e.target.value
                            )
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
                    <Input
                      className='h-8 text-xs'
                      value={keywordInputValue(step.common_keywords)}
                      placeholder={tField('phMutualKeywords')}
                      onChange={(e) =>
                        update({
                          common_keywords: keywordListFromInput(e.target.value)
                        })
                      }
                    />
                  </F>
                  <F label={tField('blockedKeywords')}>
                    <Input
                      className='h-8 text-xs'
                      value={keywordInputValue(step.forbidden_keywords)}
                      placeholder='trang, page, sponsored, anonymous'
                      onChange={(e) =>
                        update({
                          forbidden_keywords: keywordListFromInput(
                            e.target.value
                          )
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
                    <Input
                      className='h-8 text-xs'
                      value={keywordInputValue(step.keywords)}
                      placeholder={tField('phPostKeywords')}
                      onChange={(e) =>
                        update({
                          keywords: keywordListFromInput(e.target.value)
                        })
                      }
                    />
                  </F>
                  <F label='Comment'>
                    <Input
                      className='h-8 text-xs'
                      value={step.comment_text ?? ''}
                      placeholder='${COMMENT_TEXT}'
                      onChange={(e) =>
                        update({ comment_text: e.target.value || undefined })
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
                  <StepPanelHint>
                    {step.type === 'social_open_commenter_from_post_match'
                      ? tField('adapterHintCommenter')
                      : tField('adapterHintAuthor')}
                  </StepPanelHint>
                  <div className='grid grid-cols-3 gap-2'>
                    <F label={tField('scanVar')}>
                      <Input
                        className='h-8 font-mono text-xs'
                        value={step.source_var ?? '_post_scan'}
                        onChange={(e) =>
                          update({ source_var: e.target.value || '_post_scan' })
                        }
                      />
                    </F>
                    <F label='Action index'>
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
                  <F label={tField('requiredProfileKeywords')}>
                    <Input
                      className='h-8 text-xs'
                      value={keywordInputValue(step.required_keywords)}
                      placeholder={tField('phProfileKeywords')}
                      onChange={(e) =>
                        update({
                          required_keywords: keywordListFromInput(
                            e.target.value
                          )
                        })
                      }
                    />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={tField('bonusKeywords')}>
                      <Input
                        className='h-8 text-xs'
                        value={keywordInputValue(step.optional_keywords)}
                        placeholder={tField('phBonusKeywords')}
                        onChange={(e) =>
                          update({
                            optional_keywords: keywordListFromInput(
                              e.target.value
                            )
                          })
                        }
                      />
                    </F>
                    <F label={tField('blockedKeywords')}>
                      <Input
                        className='h-8 text-xs'
                        value={keywordInputValue(step.forbidden_keywords)}
                        placeholder='page, group, anonymous'
                        onChange={(e) =>
                          update({
                            forbidden_keywords: keywordListFromInput(
                              e.target.value
                            )
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
                    <F label='Timeout'>
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
                        value={step.save_as ?? '_people_target'}
                        onChange={(e) =>
                          update({
                            save_as: e.target.value || '_people_target'
                          })
                        }
                      />
                    </F>
                  </div>
                </>
              )}

              {[
                'content_interaction',
                'connection_request',
                'community_membership'
              ].includes(step.type) && (
                <>
                  <StepPanelHint>{tField('connectHint')}</StepPanelHint>
                  <F label={tField('action')}>
                    <select
                      className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={step.action ?? defaultSocialAction(step.type)}
                      onChange={(e) => update({ action: e.target.value })}
                    >
                      {getSocialActionOptions(step.type).map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </F>
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
                            timeout: Math.max(0.1, Number(e.target.value) || 6)
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
                            poll: Math.max(0.05, Number(e.target.value) || 0.4)
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
                  <LoopConfigFields step={step} onUpdate={update} />
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
                    <Input
                      className='h-8 font-mono text-xs'
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
                    <Input
                      className='h-9 text-sm'
                      value={keywordInputValue(step.from_list)}
                      placeholder={t('setVariable.randomListPlaceholder')}
                      onChange={(e) =>
                        update({
                          from_list: isVarRef(e.target.value.trim())
                            ? e.target.value.trim()
                            : e.target.value
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
                    <Input
                      className='h-8 font-mono text-xs'
                      value={
                        typeof step.value === 'string'
                          ? step.value
                          : JSON.stringify(step.value ?? '')
                      }
                      onChange={(e) => {
                        const raw = e.target.value;
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
                    <textarea
                      className='min-h-[92px] w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={step.prompt ?? ''}
                      onChange={(e) => update({ prompt: e.target.value })}
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
                    <Input
                      className='h-8 font-mono text-xs'
                      placeholder={tField('phCollection', {
                        token: '${SAVE_COLLECTION}'
                      })}
                      value={step.collection ?? ''}
                      onChange={(e) => update({ collection: e.target.value })}
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
                    <Input
                      className='h-8 text-xs'
                      placeholder='group,crawl,${GROUP_NAME}'
                      value={step.tags ?? ''}
                      onChange={(e) =>
                        update({ tags: e.target.value || undefined })
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
                  <Input
                    className='h-8 font-mono text-xs'
                    value={step.save_path ?? ''}
                    onChange={(e) =>
                      update({ save_path: e.target.value || undefined })
                    }
                    placeholder='/sdcard/screen.jpg'
                  />
                </F>
              )}

              {step.type === 'set_clipboard' && (
                <F label={tField('clipboardContent')}>
                  <Input
                    className='h-8 text-xs'
                    value={step.text ?? ''}
                    onChange={(e) => update({ text: e.target.value })}
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
                    <Input
                      className='h-8 text-xs'
                      value={step.search ?? ''}
                      onChange={(e) =>
                        update({ search: e.target.value || undefined })
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
                      <Input
                        className='h-8 text-xs'
                        value={keywordInputValue(step.keywords)}
                        onChange={(event) =>
                          update({ keywords: event.target.value })
                        }
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
    </div>
  );
}
