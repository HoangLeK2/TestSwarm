'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Popover,
  PopoverTrigger,
  PopoverContent
} from '@/components/ui/popover';
import { Progress } from '@/components/ui/progress';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import {
  Play,
  Square,
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Loader2,
  Info,
  StepForward,
  ListRestart,
  Circle,
  Braces
} from 'lucide-react';
import {
  useCampaigns,
  useScenarios
} from '@/features/campaigns/hooks/use-campaigns';
import {
  cancelPreviewStream,
  interruptDevice,
  previewScenarioStream,
  type PreviewStepResult
} from '../../services/api';
import { accountGroupsApi } from '@/features/account-groups/services/api';
import { useAccountGroups } from '@/features/account-groups/hooks/use-account-groups';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { toast } from 'sonner';
import type { ScenarioOut } from '@/features/campaigns/types';
import {
  getStepTypeName,
  getStepSummary,
  getStepDisplay,
  STEP_COLORS
} from '@/features/campaigns/components/flow-editor/constants';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';

type ScenarioPlayerT = ReturnType<typeof useTranslations>;

function conditionKeysPreview(condition: unknown, max = 8): string {
  if (!condition || typeof condition !== 'object') return '';
  return Object.keys(condition as object)
    .slice(0, max)
    .join(', ');
}

/** Extra lines for if / loop / random_pick so preview list is not a flat mystery. */
function ScenarioControlFlowExtra({
  step,
  t
}: {
  step: FlowStep;
  t: ScenarioPlayerT;
}) {
  const type = step.type;

  if (type === 'if_element' || type === 'if_variable' || type === 'if') {
    const thenN = Array.isArray(step.then) ? step.then.length : 0;
    const elseN = Array.isArray(step.else) ? step.else.length : 0;
    const keys = type === 'if' ? conditionKeysPreview(step.condition) : '';
    return (
      <div className='mt-2 space-y-1 border-t border-border/50 pt-2 text-[10px] leading-relaxed text-muted-foreground'>
        <div className='flex gap-1.5'>
          <span
            className='shrink-0 text-emerald-600 dark:text-emerald-400'
            aria-hidden
          >
            {'\u2713'}
          </span>
          <span>{t('thenSteps', { count: thenN })}</span>
        </div>
        <div className='flex gap-1.5'>
          <span className='shrink-0 text-red-500/80' aria-hidden>
            {'\u2717'}
          </span>
          <span>{t('elseSteps', { count: elseN })}</span>
        </div>
        {keys ? (
          <p className='pl-4 font-mono text-[9px] text-muted-foreground/90'>
            {t('ifConditionHint', { keys })}
          </p>
        ) : null}
      </div>
    );
  }

  if (type === 'loop' || type === 'repeat' || type === 'repeat_until') {
    const n = Array.isArray(step.steps) ? step.steps.length : 0;
    const countVal = step.count ?? '?';
    return (
      <div className='mt-2 space-y-1 border-t border-border/50 pt-2 text-[10px] leading-relaxed text-muted-foreground'>
        {type === 'repeat' ? (
          <div>{t('repeatTimes', { count: countVal })}</div>
        ) : null}
        {type === 'loop' ? (
          <div>{t('loopTimes', { count: countVal })}</div>
        ) : null}
        {type === 'repeat_until' ? (
          <div>{t('repeatUntilMax', { max: step.max_iterations ?? '?' })}</div>
        ) : null}
        <div>{t('bodySteps', { count: n })}</div>
      </div>
    );
  }

  if (type === 'random_pick' && Array.isArray(step.branches)) {
    return (
      <div className='mt-2 space-y-0.5 border-t border-border/50 pt-2 text-[10px] leading-relaxed text-muted-foreground'>
        {(step.branches as Array<{ steps?: FlowStep[]; weight?: number }>).map(
          (br, bi) => (
            <div key={bi}>
              {t('randomBranch', {
                letter: String.fromCharCode(65 + bi),
                count: Array.isArray(br?.steps) ? br.steps.length : 0,
                weight: br?.weight ?? 1
              })}
            </div>
          )
        )}
      </div>
    );
  }

  if (type === 'break_if') {
    const keys = conditionKeysPreview(step.condition);
    if (!keys) return null;
    return (
      <p className='mt-2 border-t border-border/50 pt-2 text-[10px] text-muted-foreground'>
        {t('breakIfHint', { keys })}
      </p>
    );
  }

  return null;
}

function flattenVarDefs(vars: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(vars)) {
    if (
      v !== null &&
      typeof v === 'object' &&
      !Array.isArray(v) &&
      'type' in v &&
      'default' in v
    ) {
      out[k] = v.default;
    } else {
      out[k] = v;
    }
  }
  return out;
}

interface ScenarioPlayerProps {
  serial: string;
  onClose: () => void;
  onPlayingChange?: (playing: boolean) => void;
  /** When provided, skip campaign/scenario selection and play these steps directly. */
  preloadedSteps?: Array<Record<string, any>>;
  preloadedName?: string;
  /** Variables for template substitution (e.g. APP_PACKAGE) when using preloadedSteps. */
  preloadedVariables?: Record<string, any>;
  /** When set, server loads fresh campaign/scenario/device vars from DB. */
  preloadedScenarioId?: string | null;
  /** Per-device overrides for the active scenario (unsaved draft or post-save). */
  preloadedScenarioDeviceVars?: Record<string, any> | null;
  /** Optional account group to rotate accounts from on each preview run. */
  preloadedAccountGroupId?: string | null;
  /** When true, device is running a campaign — block preview start. */
  deviceBusy?: boolean;
  /** Parent registers a stop handle so it can abort the preview from outside
   *  (e.g. Farm back button, device switch). Called with the stop fn on mount
   *  and with null on unmount. */
  registerStop?: (fn: (() => void) | null) => void;
}

export function ScenarioPlayer({
  serial,
  onClose,
  onPlayingChange,
  preloadedSteps,
  preloadedName,
  preloadedVariables,
  preloadedScenarioId,
  preloadedScenarioDeviceVars,
  preloadedAccountGroupId,
  deviceBusy = false,
  registerStop
}: ScenarioPlayerProps) {
  const t = useTranslations('devicesControlRecord.scenarioPlayer');
  const { data: campaigns = [] } = useCampaigns();
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(
    null
  );
  const { data: scenarios = [] } = useScenarios(selectedCampaignId ?? '');
  const [selectedScenario, setSelectedScenario] = useState<ScenarioOut | null>(
    null
  );

  const [playing, setPlaying] = useState(false);
  const [results, setResults] = useState<PreviewStepResult[]>([]);
  const [currentStepIndex, setCurrentStepIndex] = useState(-1);
  const [loopCount, setLoopCount] = useState(1);
  const [currentLoop, setCurrentLoop] = useState(0);
  const [exitConfirm, setExitConfirm] = useState<null | (() => void)>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Current trace id from the in-flight preview stream. Captured from the
  // server's 'start' SSE event so Stop + unmount can hit the explicit cancel
  // endpoint instead of waiting for SSE disconnect detection.
  const activePreviewRef = useRef<{ serial: string; traceId: string } | null>(
    null
  );

  const hardStop = useCallback(() => {
    abortRef.current?.abort();
    const active = activePreviewRef.current;
    if (active) {
      cancelPreviewStream(active.serial, active.traceId).catch(() => undefined);
      interruptDevice(active.serial).catch(() => undefined);
      activePreviewRef.current = null;
    } else if (serial?.trim()) {
      interruptDevice(serial.trim()).catch(() => undefined);
    }
  }, [serial]);

  // Unmount cleanup: browser navigation away, Next.js route change, and tab
  // close (pagehide). Scenario stops at next step boundary on the server.
  useEffect(() => {
    const onPageHide = () => hardStop();
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      hardStop();
    };
  }, [hardStop]);

  // Expose stop to parent so Farm back button / device switch can abort.
  useEffect(() => {
    registerStop?.(hardStop);
    return () => registerStop?.(null);
  }, [hardStop, registerStop]);

  // While a scenario is running, warn before browser close / reload /
  // hard-navigation. Native beforeunload dialog — cannot be customized.
  useEffect(() => {
    if (!playing) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = t('exitBeforeUnload');
      return e.returnValue;
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [playing, t]);

  // Guard wrapper — if a scenario is playing, queue the exit action behind a
  // confirm dialog. Otherwise run immediately.
  const guardExit = useCallback(
    (exitAction: () => void) => {
      if (playing) {
        setExitConfirm(() => exitAction);
      } else {
        exitAction();
      }
    },
    [playing]
  );

  // Step-by-step mode
  const [stepByStep, setStepByStep] = useState(false);
  const [stepCursor, setStepCursor] = useState(0); // next step to run

  const activeSteps =
    preloadedSteps ??
    (selectedScenario?.steps as Array<Record<string, any>> | undefined);
  const baseActiveVariables: Record<string, any> = flattenVarDefs(
    preloadedVariables ??
      (selectedScenario?.variables as Record<string, any> | undefined) ??
      {}
  );
  // Let the Player mode override the account group without going back to the
  // save dialog. Precedence: inline pick > caller preload > saved scenario.
  const [overrideAccountGroupId, setOverrideAccountGroupId] = useState<
    string | null
  >(null);
  const activeAccountGroupId: string | null =
    overrideAccountGroupId ??
    preloadedAccountGroupId ??
    selectedScenario?.account_group_id ??
    null;

  const { data: accountGroupsList = [] } = useAccountGroups();
  const resolvedAccountGroup =
    accountGroupsList.find((g) => g.id === activeAccountGroupId) ?? null;

  // Session-scoped account vars — resolved once on first play so that running
  // the scenario step-by-step (or multiple loops) uses the SAME account for
  // every step. Without this, each preview call would advance the rotation
  // cursor and step 2 (username) + step 3 (password) would be satisfied from
  // two different accounts → login failure.
  const [sessionAccountVars, setSessionAccountVars] = useState<Record<
    string,
    any
  > | null>(null);
  const resolvingAccountRef = useRef(false);

  const ensureAccountVars = useCallback(async (): Promise<Record<
    string,
    any
  > | null> => {
    if (sessionAccountVars) return sessionAccountVars;
    if (!activeAccountGroupId) return null;
    if (resolvingAccountRef.current) return null;
    resolvingAccountRef.current = true;
    try {
      const res = await accountGroupsApi.resolve(activeAccountGroupId);
      const vars = res.variables ?? {};
      setSessionAccountVars(vars);
      return vars;
    } catch (e: any) {
      const msg =
        e?.response?.data?.detail || e?.message || 'Không lấy được tài khoản';
      toast.error(String(msg));
      return null;
    } finally {
      resolvingAccountRef.current = false;
    }
  }, [sessionAccountVars, activeAccountGroupId]);

  // Clear the cached account when the user switches scenarios or swaps the
  // active account group — next play picks a fresh one.
  useEffect(() => {
    setSessionAccountVars(null);
  }, [activeAccountGroupId, selectedScenario?.id]);

  const buildVariables = useCallback(
    (accountVars: Record<string, any> | null): Record<string, any> => {
      if (!accountVars) return baseActiveVariables;
      return { ...accountVars, ...baseActiveVariables };
    },
    [baseActiveVariables]
  );

  const handlePlay = useCallback(async () => {
    if (!activeSteps?.length || !serial) return;
    if (deviceBusy) return;
    // Resolve the account once for this session; reuse across loops + steps.
    const acctVars = await ensureAccountVars();
    const mergedVars = buildVariables(acctVars);
    setPlaying(true);
    onPlayingChange?.(true);
    setResults([]);
    setCurrentStepIndex(-1);
    setCurrentLoop(0);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      for (let loop = 0; loop < loopCount; loop++) {
        if (ctrl.signal.aborted) break;
        setCurrentLoop(loop + 1);
        if (loop > 0) {
          setResults([]);
          setCurrentStepIndex(-1);
        }

        await previewScenarioStream(
          serial,
          activeSteps,
          (event) => {
            if (ctrl.signal.aborted) return;
            if (event.event === 'start') {
              if (typeof event.trace_id === 'string') {
                activePreviewRef.current = { serial, traceId: event.trace_id };
              }
              setCurrentStepIndex(0);
            } else if (event.event === 'done' || event.event === 'error') {
              activePreviewRef.current = null;
            } else if (event.event === 'step_done') {
              const result: PreviewStepResult = {
                index: event.index,
                type: event.type,
                ok: event.ok,
                message: event.message
              };
              setResults((prev) => [...prev, result]);
              setCurrentStepIndex(event.index + 1);
            }
            // 'done' and 'error' events handled by promise completion
          },
          ctrl.signal,
          // Session vars already include resolved __ACCOUNT_* (if any), so
          // skip sending account_group_id to avoid a second cursor-advance
          // on the server.
          mergedVars,
          null,
          preloadedScenarioId ?? null,
          preloadedScenarioDeviceVars ?? null
        );
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setResults((prev) => [
          ...prev,
          { index: currentStepIndex, ok: false, message: String(e) }
        ]);
      }
    } finally {
      setPlaying(false);
      onPlayingChange?.(false);
      setCurrentStepIndex(-1);
      abortRef.current = null;
      activePreviewRef.current = null;
    }
  }, [
    activeSteps,
    baseActiveVariables,
    serial,
    loopCount,
    currentStepIndex,
    deviceBusy,
    ensureAccountVars,
    buildVariables,
    preloadedScenarioId,
    preloadedScenarioDeviceVars
  ]);

  const handleStop = useCallback(() => {
    // Three-pronged stop: abort SSE fetch, hit explicit cancel route with
    // trace id (zero polling lag server-side), flip local state.
    hardStop();
    setPlaying(false);
  }, [hardStop]);

  const handleRunOneStep = useCallback(async () => {
    if (!activeSteps?.length || !serial || playing) return;
    if (deviceBusy) return;
    const idx = stepCursor;
    if (idx >= activeSteps.length) return;
    const step = activeSteps[idx];
    // Same-session account reuse: first run-one-step in this session resolves
    // the account, subsequent runs receive the cached vars so every step in
    // the session targets the same pool member.
    const acctVars = await ensureAccountVars();
    const mergedVars = buildVariables(acctVars);
    setPlaying(true);
    setCurrentStepIndex(idx);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await previewScenarioStream(
        serial,
        [step],
        (event) => {
          if (ctrl.signal.aborted) return;
          if (event.event === 'start' && typeof event.trace_id === 'string') {
            activePreviewRef.current = { serial, traceId: event.trace_id };
          } else if (event.event === 'done' || event.event === 'error') {
            activePreviewRef.current = null;
          }
          if (event.event === 'step_done') {
            setResults((prev) => {
              const next = prev.filter((r) => r.index !== idx);
              return [
                ...next,
                {
                  index: idx,
                  type: event.type,
                  ok: event.ok,
                  message: event.message
                }
              ];
            });
          }
        },
        ctrl.signal,
        mergedVars,
        null,
        preloadedScenarioId ?? null,
        preloadedScenarioDeviceVars ?? null
      );
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setResults((prev) => [
          ...prev.filter((r) => r.index !== idx),
          { index: idx, ok: false, message: String(e) }
        ]);
      }
    } finally {
      setPlaying(false);
      setCurrentStepIndex(-1);
      abortRef.current = null;
      activePreviewRef.current = null;
      if (!ctrl.signal.aborted) setStepCursor(idx + 1);
    }
  }, [
    activeSteps,
    serial,
    playing,
    stepCursor,
    deviceBusy,
    ensureAccountVars,
    buildVariables,
    preloadedScenarioId,
    preloadedScenarioDeviceVars
  ]);

  // Step 1: Select campaign (skip if preloaded)
  if (!preloadedSteps && !selectedCampaignId) {
    return (
      <div className='space-y-3'>
        <div className='flex items-center gap-2'>
          <Button size='sm' variant='ghost' onClick={onClose}>
            <ArrowLeft className='mr-1 size-3.5' />
            Back
          </Button>
          <span className='text-sm font-medium'>Select Campaign</span>
        </div>
        {campaigns.length === 0 ? (
          <p className='py-4 text-center text-xs text-muted-foreground'>
            No campaigns found
          </p>
        ) : (
          <div className='space-y-1'>
            {campaigns.map((c) => (
              <Button
                key={c.id}
                variant='outline'
                size='sm'
                className='w-full justify-start text-xs'
                onClick={() => setSelectedCampaignId(c.id)}
              >
                {c.name}
              </Button>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Step 2: Select scenario (skip if preloaded)
  if (!preloadedSteps && !selectedScenario) {
    return (
      <div className='space-y-3'>
        <div className='flex items-center gap-2'>
          <Button
            size='sm'
            variant='ghost'
            onClick={() => setSelectedCampaignId(null)}
          >
            <ArrowLeft className='mr-1 size-3.5' />
            {t('campaignsNav')}
          </Button>
          <span className='text-sm font-medium'>{t('selectScenario')}</span>
        </div>
        {scenarios.length === 0 ? (
          <p className='py-4 text-center text-xs text-muted-foreground'>
            {t('noScenarios')}
          </p>
        ) : (
          <div className='space-y-1'>
            {scenarios.map((s) => (
              <Button
                key={s.id}
                variant='outline'
                size='sm'
                className='h-auto w-full flex-col items-start justify-start py-2 text-xs'
                onClick={() => setSelectedScenario(s)}
              >
                <span className='font-medium'>{s.name}</span>
                <span className='text-[10px] text-muted-foreground'>
                  {t('stepsInScenario', { count: s.steps.length })}
                </span>
              </Button>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Step 3: Play scenario
  const steps = activeSteps ?? [];
  const displayName = preloadedName ?? selectedScenario?.name ?? '';

  const progressPct =
    steps.length > 0
      ? Math.round(
          ((stepByStep
            ? stepCursor
            : playing
              ? Math.min(Math.max(currentStepIndex, 0) + 1, steps.length)
              : results.length) /
            steps.length) *
            100
        )
      : 0;

  return (
    <div className='flex min-h-0 flex-1 flex-col gap-3'>
      <div className='flex shrink-0 flex-wrap items-center gap-2 border-b border-border/60 pb-3'>
        <Button
          size='sm'
          variant='ghost'
          onClick={() => {
            const doExit = () => {
              hardStop();
              if (preloadedSteps) {
                onClose();
              } else {
                setSelectedScenario(null);
                setResults([]);
              }
            };
            guardExit(doExit);
          }}
        >
          <ArrowLeft className='mr-1 size-3.5' />
          {preloadedSteps ? t('close') : t('scenarios')}
        </Button>
        <span className='truncate text-sm font-medium'>
          {displayName || t('currentScenarioFallback')}
        </span>
        <div className='flex-1' />
        {/* Mode toggle */}
        <Button
          size='sm'
          variant={stepByStep ? 'secondary' : 'outline'}
          className='h-7 gap-1 px-2 text-[11px]'
          onClick={() => {
            setStepByStep(!stepByStep);
            setResults([]);
            setStepCursor(0);
          }}
          disabled={playing}
          title={
            stepByStep ? t('modeToggleRunAllTitle') : t('modeToggleStepTitle')
          }
        >
          <StepForward className='size-3.5' />
          {stepByStep ? t('modeStepByStep') : t('modeAll')}
        </Button>

        {stepByStep ? (
          <>
            <Button
              size='sm'
              variant='outline'
              className='h-7 gap-1 px-2 text-[11px]'
              onClick={() => {
                setResults([]);
                setStepCursor(0);
              }}
              disabled={playing}
              title={t('resetFirstTitle')}
            >
              <ListRestart className='size-3.5' />
            </Button>
            {playing ? (
              <Button
                size='sm'
                variant='destructive'
                onClick={handleStop}
                className='h-7 px-3 text-xs'
              >
                <Square className='mr-1 size-3.5' />
                {t('stop')}
              </Button>
            ) : (
              <Button
                size='sm'
                onClick={handleRunOneStep}
                disabled={
                  !activeSteps?.length ||
                  stepCursor >= (activeSteps?.length ?? 0) ||
                  deviceBusy
                }
                title={deviceBusy ? t('deviceBusyTitle') : undefined}
                className='h-7 gap-1 px-3 text-xs'
              >
                <StepForward className='size-3.5' />
                {t('stepRunLabel', {
                  current: stepCursor + 1,
                  total: activeSteps?.length ?? 0
                })}
              </Button>
            )}
          </>
        ) : (
          <>
            {/* Loop count */}
            <div className='flex items-center gap-1'>
              <label className='text-[10px] text-muted-foreground'>
                {t('loopLabel')}
              </label>
              <input
                type='number'
                min={1}
                max={100}
                value={loopCount}
                onChange={(e) =>
                  setLoopCount(Math.max(1, Math.min(100, +e.target.value || 1)))
                }
                disabled={playing}
                className='w-12 rounded border bg-background px-1.5 py-0.5 text-center text-xs'
              />
            </div>
            {playing ? (
              <Button size='sm' variant='destructive' onClick={handleStop}>
                <Square className='mr-1 size-3.5' />
                {t('stop')}
              </Button>
            ) : (
              <Button
                size='sm'
                onClick={handlePlay}
                disabled={deviceBusy}
                title={deviceBusy ? t('deviceBusyTitle') : undefined}
              >
                <Play className='mr-1 size-3.5' />
                {t('play')}
              </Button>
            )}
          </>
        )}
      </div>

      {/* Account group picker — visible in Player mode so the user can pick a
          pool without going back to the save dialog. Picking resets any
          cached session account so the next Play/Step resolves a fresh one. */}
      <div className='flex items-center gap-2 border-b border-border/60 px-3 py-1.5 text-[11px]'>
        <span className='shrink-0 text-muted-foreground'>Nhóm tài khoản:</span>
        <Select
          value={activeAccountGroupId ?? '_none'}
          onValueChange={(v) => {
            const next = v === '_none' ? null : v;
            setOverrideAccountGroupId(next);
            setSessionAccountVars(null); // force re-resolve with the new pick
          }}
          disabled={playing}
        >
          <SelectTrigger className='h-7 min-w-[200px] text-[11px]'>
            <SelectValue placeholder='— Không dùng —' />
          </SelectTrigger>
          <SelectContent className='z-[10010]'>
            <SelectItem value='_none' className='text-xs'>
              — Không dùng —
            </SelectItem>
            {accountGroupsList.map((g) => (
              <SelectItem key={g.id} value={g.id} className='text-xs'>
                {g.name} · {g.platform} · {g.member_count}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {resolvedAccountGroup && sessionAccountVars?.__ACCOUNT_USERNAME__ && (
          <span className='truncate rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200/60'>
            acc: {String(sessionAccountVars.__ACCOUNT_USERNAME__)}
          </span>
        )}
        {resolvedAccountGroup && !sessionAccountVars && (
          <span className='text-[10px] text-muted-foreground'>
            chưa resolve · click Play/Step
          </span>
        )}
      </div>

      {deviceBusy && !playing && (
        <div className='shrink-0 rounded-md border border-amber-400/40 bg-amber-50/80 px-3 py-2 text-[11px] text-amber-800 dark:bg-amber-950/20 dark:text-amber-300'>
          {t('deviceBusyBanner')}
        </div>
      )}

      {/* Loop progress */}
      {playing && loopCount > 1 && (
        <div className='shrink-0 text-[11px] text-muted-foreground'>
          {t('runLoop', { current: currentLoop, total: loopCount })}
        </div>
      )}

      {/* Progress — helps user see where the run is in the script */}
      {steps.length > 0 && (
        <div className='shrink-0 space-y-1.5'>
          <div className='flex items-center justify-between gap-2 text-[11px] text-muted-foreground'>
            <span>
              {stepByStep
                ? t('progressNext', {
                    current: Math.min(stepCursor + 1, steps.length),
                    total: steps.length
                  })
                : playing
                  ? t('progressRunning', {
                      current: Math.min(
                        Math.max(currentStepIndex, 0) + 1,
                        steps.length
                      ),
                      total: steps.length
                    })
                  : results.length > 0
                    ? t('progressDone', {
                        done: results.length,
                        total: steps.length
                      })
                    : t('progressOverview', { count: steps.length })}
            </span>
            <span className='font-medium tabular-nums text-foreground'>
              {progressPct}%
            </span>
          </div>
          <Progress value={progressPct} className='h-1.5' />
        </div>
      )}

      {/* Step list — tall scroll region inside column 3 */}
      <div className='min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-y-contain rounded-lg border border-border/50 bg-muted/20 p-2.5'>
        {steps.map((step, i) => {
          const flowStep = step as unknown as FlowStep;
          const result = results.find((r) => r.index === i);
          const isRunning = playing && i === currentStepIndex;
          const isCursor =
            stepByStep && !playing && i === stepCursor && !result;
          const display = getStepDisplay(flowStep);
          const fallback = getStepSummary(flowStep);
          const detail = (display.target || fallback).trim();
          const colorCls = STEP_COLORS[step.type] ?? 'border-l-slate-400';
          const hasVar = /\$\{[^}]+\}/.test(detail);

          return (
            <div
              key={i}
              className={cn(
                'overflow-hidden rounded-lg border border-border/60 bg-card text-xs shadow-sm transition-[box-shadow,background-color]',
                'border-l-[3px]',
                colorCls,
                isRunning && 'bg-primary/5 ring-2 ring-primary/25',
                isCursor && 'bg-amber-500/5 ring-2 ring-amber-400/35',
                result?.ok && !isRunning && 'bg-emerald-500/5',
                result && !result.ok && !isRunning && 'bg-red-500/5',
                !isRunning && !isCursor && !result && 'opacity-90'
              )}
            >
              <div className='flex items-start gap-2.5 px-2.5 py-2'>
                {/* Status */}
                <div className='mt-0.5 flex w-5 shrink-0 flex-col items-center gap-1'>
                  {isRunning ? (
                    <Loader2 className='size-4 animate-spin text-primary' />
                  ) : result?.ok ? (
                    <CheckCircle2 className='size-4 text-emerald-500' />
                  ) : result && !result.ok ? (
                    <XCircle className='size-4 text-red-500' />
                  ) : (
                    <Circle
                      className={cn(
                        'size-4 text-muted-foreground/35',
                        playing &&
                          i > currentStepIndex &&
                          !result &&
                          'text-muted-foreground/20'
                      )}
                      strokeWidth={1.5}
                    />
                  )}
                  <span className='text-[9px] font-semibold tabular-nums text-muted-foreground'>
                    {i + 1}
                  </span>
                </div>

                {/* Step type icon */}
                <div
                  className={cn(
                    'mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md border border-border/50 bg-muted/40',
                    isRunning && 'border-primary/30 bg-primary/5'
                  )}
                >
                  <StepIcon type={step.type} size={16} />
                </div>

                {/* Text */}
                <div className='min-w-0 flex-1'>
                  <div className='flex flex-wrap items-center gap-1.5 gap-y-0.5'>
                    <span className='text-[10px] font-bold uppercase tracking-wide text-muted-foreground'>
                      {getStepTypeName(step.type)}
                    </span>
                    {display.selectorBadge ? (
                      <Badge
                        variant='secondary'
                        className='h-5 px-1.5 py-0 text-[9px] font-medium'
                      >
                        {display.selectorBadge}
                      </Badge>
                    ) : null}
                    {hasVar ? (
                      <span
                        className='inline-flex items-center gap-0.5 text-[9px] text-muted-foreground'
                        title={t('variablesTooltip')}
                      >
                        <Braces className='size-3' />
                        {t('variablesBadge')}
                      </span>
                    ) : null}
                  </div>
                  {detail ? (
                    <p
                      className='mt-1 line-clamp-4 text-[13px] leading-snug text-foreground'
                      title={detail}
                    >
                      {detail}
                    </p>
                  ) : (
                    <p className='mt-1 text-[11px] italic text-muted-foreground'>
                      {t('noExtraDescription')}
                    </p>
                  )}
                  <ScenarioControlFlowExtra step={flowStep} t={t} />
                </div>

                <div className='flex shrink-0 flex-col items-end gap-1'>
                  {result?.ok &&
                    (result as any).method === 'fallback_position' && (
                      <Badge
                        variant='secondary'
                        className='text-[9px] font-normal text-amber-800 dark:text-amber-200'
                      >
                        {t('fallbackBadge')}
                      </Badge>
                    )}
                  {result && result.message ? (
                    <Popover>
                      <PopoverTrigger asChild>
                        <button
                          type='button'
                          className={cn(
                            'rounded-md p-1 hover:bg-accent',
                            result.ok ? 'text-emerald-600' : 'text-red-600'
                          )}
                          aria-label={t('stepResultDetailsAria')}
                        >
                          <Info className='size-4' />
                        </button>
                      </PopoverTrigger>
                      <PopoverContent
                        side='left'
                        align='start'
                        className='w-80 p-3'
                      >
                        <div className='space-y-1.5'>
                          <div className='flex items-center gap-1.5 text-xs font-medium'>
                            {result.ok ? (
                              <CheckCircle2 className='size-3.5 text-emerald-500' />
                            ) : (
                              <XCircle className='size-3.5 text-red-500' />
                            )}
                            {t('popoverStepTitle', {
                              n: i + 1,
                              typeName: getStepTypeName(step.type)
                            })}
                          </div>
                          <p
                            className={cn(
                              'break-words text-[11px]',
                              result.ok
                                ? 'text-muted-foreground'
                                : 'text-red-600'
                            )}
                          >
                            {result.message}
                          </p>
                          {(() => {
                            const debugParts: string[] = [];
                            const parentSrc = (result as any)
                              .parent_hash_source;
                            const scanPasses = (result as any)
                              .comment_scan_passes;
                            const reasonCode = (result as any).reason_code;
                            if (parentSrc)
                              debugParts.push(`parent=${String(parentSrc)}`);
                            if (typeof scanPasses === 'number')
                              debugParts.push(`scan_passes=${scanPasses}`);
                            if (reasonCode)
                              debugParts.push(`reason=${String(reasonCode)}`);
                            if (debugParts.length === 0) return null;
                            return (
                              <p className='text-[10px] text-muted-foreground'>
                                {debugParts.join(' · ')}
                              </p>
                            );
                          })()}
                        </div>
                      </PopoverContent>
                    </Popover>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary */}
      {results.length > 0 && !playing && (
        <div className='shrink-0 text-xs text-muted-foreground'>
          {t('summaryPassed', {
            passed: results.filter((r) => r.ok).length,
            total: steps.length
          })}
          {loopCount > 1 ? ` ${t('summaryLoops', { loops: currentLoop })}` : ''}
        </div>
      )}

      <AlertDialog
        open={exitConfirm !== null}
        onOpenChange={(o) => {
          if (!o) setExitConfirm(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('exitConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('exitConfirmDesc')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('exitConfirmCancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const action = exitConfirm;
                setExitConfirm(null);
                if (action) action();
              }}
            >
              {t('exitConfirmConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
