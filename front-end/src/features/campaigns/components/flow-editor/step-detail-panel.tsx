'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { MousePointerClick, Move } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RepeatUntilFields } from '../scenario-steps/control-flow-editors';
import {
  RunScenarioFields,
  type RunScenarioCampaignOption
} from '../scenario-steps/run-scenario-editor';
import {
  createDefaultFbCommentThenSteps,
  type FlowStep
} from '../scenario-steps/types';
import { ExtractStepFields } from './extract-fields';
import { ScrollDownStepFields } from './scroll-down-fields';
import { FallbackRatioFields, SelectorFields } from './selector-fields';
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
  /** Other scenarios in the campaign — for run_scenario picker (templates always loaded inside RunScenarioFields). */
  campaignScenarios?: RunScenarioCampaignOption[];
}

/** Value field + variable insert: stacks on narrow widths so the select never squeezes the input. */
function valueInsertRowClassName() {
  return 'flex min-w-0 flex-col gap-2 sm:flex-row sm:items-stretch sm:gap-2';
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
  // Account rotation — injected when the scenario is bound to an account group.
  // Password is resolved at Temporal runtime from __ACCOUNT_ID__ so plaintext
  // never lands in the workflow event history.
  '${__ACCOUNT_ID__}',
  '${__ACCOUNT_USERNAME__}',
  '${__ACCOUNT_PASSWORD__}',
  '${__ACCOUNT_DISPLAY_NAME__}',
  '${__ACCOUNT_PLATFORM__}'
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
    </select>
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
  campaignScenarios = []
}: Props) {
  const t = useTranslations('campaignsFeature.stepEditor');
  const tApp = useTranslations('campaignsFeature.stepEditor.appLifecycle');
  const tSec = useTranslations('campaignsFeature.stepEditor.sections');
  const tSel = useTranslations('campaignsFeature.stepEditor.selector');
  const [step, setStep] = useState(stepProp);
  const pendingCommitRef = useRef<FlowStep | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    setStep(stepProp);
  }, [stepProp]);

  useEffect(() => {
    return () => {
      if (pendingCommitRef.current)
        onChangeRef.current(pendingCommitRef.current);
    };
  }, []);

  /** Persist edits without re-rendering this panel (text fields use StepPanelInput). */
  const commitStep = useCallback(
    (next: FlowStep) => {
      pendingCommitRef.current = next;
      onChange(next);
    },
    [onChange]
  );

  const update = useCallback(
    (fields: Partial<FlowStep>) => {
      setStep((prev) => {
        const next = { ...prev, ...fields } as FlowStep;
        pendingCommitRef.current = next;
        onChange(next);
        return next;
      });
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

  return (
    <div className='flex flex-col bg-card'>
      <StepPanelHeader step={step} />

      <div className='max-h-[70vh] space-y-4 overflow-y-auto p-3 sm:p-4'>
        <StepPanelMetaFields step={step} commitStep={commitStep} t={t} />

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
                        timeout: Math.max(0.1, Number(e.target.value) || 0.1)
                      })
                    }
                  />
                  <span className='text-[11px] text-muted-foreground'>
                    giây
                  </span>
                </div>
              </StepPanelField>
            </>
          )}

          {(step.type === 'launch_app' ||
            step.type === 'stop_app' ||
            step.type === 'clear_app' ||
            step.type === 'wait_app') && (
            <AppLifecycleStepFields step={step} update={update} tApp={tApp} />
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
              <F label='Package trình duyệt'>
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
              <StepPanelHint>{tApp('installApkHint')}</StepPanelHint>
            </>
          )}

          {step.type === 'wait' && (
            <F label='Thời gian (giây)'>
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
                          timeout: Math.max(0.1, Number(e.target.value) || 0.1)
                        })
                      }
                    />
                    <span className='text-[11px] text-muted-foreground'>
                      giây
                    </span>
                  </div>
                </StepPanelField>
              )}
              {(step.type === 'wait_element' ||
                step.type === 'assert_element') && (
                <F label='Poll interval (giây)'>
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
                  <F label='Hướng cuộn'>
                    <select
                      className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={step.direction ?? 'down'}
                      onChange={(e) => update({ direction: e.target.value })}
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
                <F label='Thời gian giữ (ms)'>
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
                  Chạm trên mirror để lấy tọa độ (CHẠM TỌA ĐỘ)
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
                  Vuốt trên mirror để lấy đoạn (đầu → cuối)
                </Button>
              )}
              <div className='grid grid-cols-2 gap-2'>
                <F label='Từ X'>
                  <Input
                    type='number'
                    min={0}
                    max={1}
                    step={0.01}
                    className='h-8 text-xs'
                    value={step.x1 ?? 0.5}
                    onChange={(e) => update({ x1: parseFloat(e.target.value) })}
                  />
                </F>
                <F label='Từ Y'>
                  <Input
                    type='number'
                    min={0}
                    max={1}
                    step={0.01}
                    className='h-8 text-xs'
                    value={step.y1 ?? 0.8}
                    onChange={(e) => update({ y1: parseFloat(e.target.value) })}
                  />
                </F>
                <F label='Tới X'>
                  <Input
                    type='number'
                    min={0}
                    max={1}
                    step={0.01}
                    className='h-8 text-xs'
                    value={step.x2 ?? 0.5}
                    onChange={(e) => update({ x2: parseFloat(e.target.value) })}
                  />
                </F>
                <F label='Tới Y'>
                  <Input
                    type='number'
                    min={0}
                    max={1}
                    step={0.01}
                    className='h-8 text-xs'
                    value={step.y2 ?? 0.2}
                    onChange={(e) => update({ y2: parseFloat(e.target.value) })}
                  />
                </F>
              </div>
              <F label='Thời gian vuốt (ms)'>
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

          {step.type === 'input_text' && (
            <>
              <F label='Nội dung nhập'>
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
              <F label='Cách nhập'>
                <select
                  className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                  value={step.via ?? 'u2'}
                  onChange={(e) => update({ via: e.target.value })}
                >
                  <option value='u2'>u2</option>
                  <option value='a11y_key'>a11y_key</option>
                </select>
              </F>
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
              <F label='Nội dung nhập'>
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
                label='Xoá nội dung cũ trước khi nhập'
                checked={step.clear_first ?? true}
                onCheckedChange={(checked) => update({ clear_first: checked })}
              />
            </>
          )}

          {step.type === 'key' && (
            <F label='Phím'>
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
              <F label='Timeout (giây)'>
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
              <F label='Ổn định trong (giây)'>
                <Input
                  type='number'
                  min={0.1}
                  step={0.1}
                  className='h-8 text-xs'
                  value={step.stable_duration ?? 0.4}
                  onChange={(e) =>
                    update({ stable_duration: Number(e.target.value) || 0.4 })
                  }
                />
              </F>
            </div>
          )}

          {step.type === 'verify_screen' && (
            <>
              <F label='screenshot (base64 hoặc URL/path)'>
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
                      update({ ssim_threshold: Number(e.target.value) || 0.75 })
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
                        timeout: Math.max(0.1, Number(e.target.value) || 0.1)
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
            </>
          )}

          {step.type === 'dismiss_popup' && (
            <F label='Số lần thử (retries)'>
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

          {(step.type === 'fb_tap_comment_button' ||
            step.type === 'tap_fb_comment_button') && (
            <>
              {/* ── Mô tả ── */}
              <div className='rounded-md border border-blue-400/40 bg-blue-50/60 px-3 py-2.5 text-[11px] leading-relaxed text-blue-950 dark:border-blue-500/30 dark:bg-blue-950/30 dark:text-blue-100'>
                <div className='mb-1 font-semibold'>
                  Bấm nút "Bình luận" (Facebook)
                </div>
                <div className='space-y-0.5'>
                  <div>
                    ① <b>Tìm</b> bài đầu tiên có nút Bình luận đang hiện trên
                    màn hình
                  </div>
                  <div>
                    ② <b>Ghi nhớ bài đó</b> — comment thu thập sau sẽ gắn đúng
                    bài này
                  </div>
                  <div>
                    ③ <b>Bấm nút</b> → sheet bình luận mở
                  </div>
                  <div>
                    ④ <b>Chọn bộ lọc</b> trong sheet 3 option (tùy chọn)
                  </div>
                  <div>
                    ⑤ Chạy nhánh <b>Khi bấm được</b> hoặc <b>Không thấy nút</b>
                  </div>
                </div>
                <div className='mt-2 rounded bg-amber-50 px-2 py-1.5 text-[10px] text-amber-900 dark:bg-amber-950/40 dark:text-amber-200'>
                  <b>Bước này không tự thu thập comment.</b> Để lấy comment, đặt
                  bước
                  <code className='mx-1 rounded bg-amber-100 px-1 dark:bg-amber-900/50'>
                    extract fb_comments
                  </code>
                  vào nhánh <b>Khi bấm được</b> — lúc đó comment sẽ tự động gắn
                  đúng bài vừa bấm.
                </div>
                {(!Array.isArray(step.then) || step.then.length === 0) && (
                  <div className='mt-2 flex flex-wrap items-center gap-2 rounded bg-background/70 px-2 py-1.5'>
                    <span className='text-[10px] text-muted-foreground'>
                      Nhánh Khi bấm được đang trống.
                    </span>
                    <Button
                      type='button'
                      size='sm'
                      variant='outline'
                      className='h-7 px-2 text-[10px]'
                      onClick={() =>
                        update({ then: createDefaultFbCommentThenSteps() })
                      }
                    >
                      Thêm 5 bước lấy bình luận
                    </Button>
                  </div>
                )}
              </div>

              {/* ── Phase 1: Tìm nút ── */}
              <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                ① Tìm nút Bình luận
              </div>
              <div className='rounded border border-border/50 bg-muted/30 px-2.5 py-2 text-[11px] text-muted-foreground'>
                Tìm node <code className='rounded bg-muted px-1'>Button</code>{' '}
                có text / content-desc là{' '}
                <code className='rounded bg-muted px-1'>"Bình luận"</code> hoặc{' '}
                <code className='rounded bg-muted px-1'>"Comment"</code>. Nếu
                không thấy Button, tự động fallback sang node{' '}
                <code className='rounded bg-muted px-1'>clickable=true</code>{' '}
                cùng text. Không tìm thấy → chạy nhánh <b>Không thấy nút</b>.
              </div>

              <StepPanelToggle
                label='Cuộn nhẹ trước khi tìm'
                description='Hé lộ hàng Thích / Bình luận khi bài viết dài (thay cho bước scroll_down riêng trước bước này).'
                checked={!!step.pre_scroll}
                onCheckedChange={(checked) => update({ pre_scroll: checked })}
              />

              {step.pre_scroll && (
                <F label='Khoảng cách cuộn (0–1, tỉ lệ màn hình)'>
                  <Input
                    type='number'
                    min={0.05}
                    max={0.6}
                    step={0.01}
                    className='h-8 w-28 text-xs'
                    value={step.pre_scroll_distance ?? 0.24}
                    onChange={(e) =>
                      update({
                        pre_scroll_distance: Math.min(
                          0.6,
                          Math.max(0.05, Number(e.target.value) || 0.24)
                        )
                      })
                    }
                  />
                </F>
              )}

              <div className='grid grid-cols-2 gap-2'>
                <F label='Chờ nút tối đa (giây)'>
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
                <F label='Tần suất kiểm tra (giây)'>
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

              {/* ── Phase 2: Sau khi tap ── */}
              <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                ② Sau khi bấm
              </div>
              <F label='Chờ sheet bình luận mở (giây)'>
                <Input
                  type='number'
                  min={0}
                  step={0.1}
                  className='h-8 w-28 text-xs'
                  value={step.post_tap_wait_s ?? 0.8}
                  onChange={(e) =>
                    update({
                      post_tap_wait_s: Math.max(
                        0,
                        Number(e.target.value) || 0.8
                      )
                    })
                  }
                />
              </F>

              {/* ── Phase 3: Bộ lọc ── */}
              <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                ③ Bộ lọc bình luận
              </div>
              <F label='Sắp xếp bình luận sau khi mở sheet'>
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
                    Không đổi — giữ mặc định Facebook
                  </option>
                  <option value='most_relevant'>Phù hợp nhất</option>
                  <option value='newest'>Mới nhất</option>
                  <option value='all_comments'>Tất cả bình luận</option>
                </select>
              </F>
              <p className='text-[10px] leading-relaxed text-muted-foreground'>
                Mở sheet bằng hàng &quot;Nhấn để thay đổi bộ lọc&quot;, rồi tap
                đúng một trong ba dòng tiêu đề (không tap dòng mô tả spam bên
                dưới).
              </p>

              {/* ── Phase 4: Nhận diện bài ── */}
              <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                ④ Nhận diện bài viết
              </div>
              <F label='Trường hash bài (giữ mặc định nếu không rõ)'>
                <Input
                  className='h-8 font-mono text-xs'
                  value={step.dedupe_field ?? 'post_key'}
                  onChange={(e) =>
                    update({ dedupe_field: e.target.value || 'post_key' })
                  }
                  placeholder='post_key'
                />
              </F>

              {/* ── Khi lỗi ── */}
              <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                ⑤ Khi không tìm thấy nút
              </div>
              <StepPanelToggle
                label='Bỏ qua khi không thấy nút'
                description='Khuyến nghị bật — không có nút Bình luận không bị tính là lỗi. Bỏ tick để dừng kịch bản khi không tìm thấy nút.'
                checked={step.ignore_error !== false}
                onCheckedChange={(checked) => update({ ignore_error: checked })}
              />
            </>
          )}

          {step.type === 'tap_position' && (
            <F label='Vị trí'>
              <select
                className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                value={step.pos ?? 'middle_center'}
                onChange={(e) => update({ pos: e.target.value })}
              >
                <option value='top_left'>Góc trên trái</option>
                <option value='top_center'>Giữa trên</option>
                <option value='search_bar'>Thanh tìm kiếm</option>
                <option value='top_right'>Góc trên phải</option>
                <option value='middle_left'>Giữa trái</option>
                <option value='middle_center'>Chính giữa</option>
                <option value='middle_right'>Giữa phải</option>
                <option value='bottom_left'>Góc dưới trái</option>
                <option value='bottom_center'>Giữa dưới</option>
                <option value='bottom_right'>Góc dưới phải</option>
              </select>
            </F>
          )}

          {step.type === 'loop' && (
            <>
              <F label='Số vòng lặp (hỗ trợ biến)'>
                <Input
                  className='h-8 font-mono text-xs'
                  placeholder='10 hoặc ${MAX_SCROLLS}'
                  value={step.count ?? '10'}
                  onChange={(e) => update({ count: e.target.value })}
                />
                <p className='mt-1 text-[10px] text-muted-foreground'>
                  Chạy đúng N lần. Có thể dừng sớm bằng break_if hoặc extract stop_if_no_new.
                </p>
              </F>
              <JsonTextarea
                label='while condition (JSON, optional)'
                value={step.while}
                onCommit={(next) => update({ while: next })}
              />
              {step.while != null &&
                typeof step.while === 'object' &&
                Object.keys(step.while).length > 0 && (
                  <F label='max_iterations (giới hạn khi dùng while)'>
                    <Input
                      type='number'
                      min={1}
                      className='h-8 w-28 text-xs'
                      value={step.max_iterations ?? 100}
                      onChange={(e) =>
                        update({ max_iterations: Number(e.target.value) || 100 })
                      }
                    />
                    <p className='mt-1 text-[10px] text-muted-foreground'>
                      Chỉ áp dụng khi không có count và dùng while condition.
                    </p>
                  </F>
                )}
            </>
          )}

          {step.type === 'repeat' && (
            <>
              <F label='Số lần lặp'>
                <Input
                  type='number'
                  min={1}
                  className='h-8 w-24 text-xs'
                  value={step.count ?? 3}
                  onChange={(e) => update({ count: Number(e.target.value) })}
                />
              </F>
              <F label='Delay giữa các lần (giây)'>
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
            <F label='Điều kiện dừng'>
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
              <F label='Timeout (giây)'>
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
                Điều kiện tổng quát theo backend (`condition`) — hỗ trợ
                element_exists / element_not_exists / variable_equals...
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
                Nếu condition đúng thì break vòng lặp hiện tại.
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
              <F label='Tên biến'>
                <Input
                  className='h-8 font-mono text-xs'
                  value={step.name ?? ''}
                  onChange={(e) => update({ name: e.target.value })}
                />
              </F>
              <F label='Điều kiện'>
                <select
                  className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                  value={
                    step.equals != null
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
                  <option value='equals'>Bằng (==)</option>
                  <option value='not_equals'>Khác (!=)</option>
                  <option value='contains'>Chứa</option>
                  <option value='greater_than'>Lớn hơn (&gt;)</option>
                </select>
              </F>
              <F label='Giá trị'>
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
                    placeholder={t('setVariable.valuePlaceholder')}
                  />
                  <VariableInsertSelect
                    availableVariables={availableVariables}
                    t={t}
                    onInsert={(token) =>
                      update({ value: insertToken(step.value ?? '', token) })
                    }
                  />
                </div>
              </F>
              <F label={t('setVariable.randomListLabel')}>
                <Input
                  className='h-9 text-sm'
                  value={(step.from_list ?? []).join(', ')}
                  placeholder={t('setVariable.randomListPlaceholder')}
                  onChange={(e) =>
                    update({
                      from_list: e.target.value
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
              <F label='Value (JSON hoặc text)'>
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
              <F label='Hệ tọa độ'>
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
              <F label='Wait sau double tap (giây)'>
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
              <F label='Tỉ lệ scale (2.0 = zoom in, 0.5 = zoom out)'>
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
              <F label='Hệ tọa độ tâm'>
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
                    <F label='Tâm X (0-1)'>
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
                    <F label='Tâm Y (0-1)'>
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
                    <F label='Tâm X (px)'>
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
                    <F label='Tâm Y (px)'>
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
              <F label='Thời gian pinch (ms)'>
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
              <F label='Hệ tọa độ'>
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
                    <F label='Từ X (0-1)'>
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
                    <F label='Từ Y (0-1)'>
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
                    <F label='Tới X (0-1)'>
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
                    <F label='Tới Y (0-1)'>
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
                    <F label='Từ X (px)'>
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
                    <F label='Từ Y (px)'>
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
                    <F label='Tới X (px)'>
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
                    <F label='Tới Y (px)'>
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
              <F label='Thời gian (ms)'>
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
              <F label='save_as'>
                <Input
                  className='h-8 font-mono text-xs'
                  value={step.save_as ?? 'ocr_text'}
                  onChange={(e) =>
                    update({ save_as: e.target.value || undefined })
                  }
                />
              </F>
              <div className='grid grid-cols-2 gap-2'>
                <F label='language'>
                  <Input
                    className='h-8 font-mono text-xs'
                    value={step.language ?? 'eng'}
                    onChange={(e) =>
                      update({ language: e.target.value || 'eng' })
                    }
                  />
                </F>
                <F label='psm'>
                  <Input
                    type='number'
                    min={1}
                    className='h-8 text-xs'
                    value={step.psm ?? 11}
                    onChange={(e) =>
                      update({ psm: Number(e.target.value) || 11 })
                    }
                  />
                </F>
                <F label='scale_factor'>
                  <Input
                    type='number'
                    min={0.1}
                    step={0.1}
                    className='h-8 text-xs'
                    value={step.scale_factor ?? 2.0}
                    onChange={(e) =>
                      update({ scale_factor: Number(e.target.value) || 2.0 })
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
              <StepPanelToggle
                label='preprocess'
                checked={step.preprocess ?? true}
                onCheckedChange={(checked) => update({ preprocess: checked })}
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
                  placeholder='default hoặc ${SAVE_COLLECTION}'
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
                        update({ parent_id_var: e.target.value || undefined })
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
            <F label='Lưu vào đường dẫn (tuỳ chọn)'>
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
            <F label='Nội dung clipboard'>
              <Input
                className='h-8 text-xs'
                value={step.text ?? ''}
                onChange={(e) => update({ text: e.target.value })}
                placeholder='Văn bản cần copy'
              />
            </F>
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

        <StepErrorPolicySection step={step} update={update} />
        <StepRetryPolicySection step={step} update={update} />
      </div>
    </div>
  );
}
