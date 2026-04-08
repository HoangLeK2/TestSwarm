'use client';

import React, { useCallback, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover';
import { Play, Square, ArrowLeft, CheckCircle2, XCircle, Loader2, Info, StepForward, ListRestart } from 'lucide-react';
import { useCampaigns, useScenarios } from '@/features/campaigns/hooks/use-campaigns';
import { previewScenarioStream, type PreviewStepResult } from '../../services/api';
import type { ScenarioOut } from '@/features/campaigns/types';
import { getStepTypeName, getStepSummary } from '@/features/campaigns/components/flow-editor/constants';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

function flattenVarDefs(vars: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(vars)) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v) && 'type' in v && 'default' in v) {
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
}

export function ScenarioPlayer({ serial, onClose, onPlayingChange, preloadedSteps, preloadedName, preloadedVariables }: ScenarioPlayerProps) {
  const { data: campaigns = [] } = useCampaigns();
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const { data: scenarios = [] } = useScenarios(selectedCampaignId ?? '');
  const [selectedScenario, setSelectedScenario] = useState<ScenarioOut | null>(null);

  const [playing, setPlaying] = useState(false);
  const [results, setResults] = useState<PreviewStepResult[]>([]);
  const [currentStepIndex, setCurrentStepIndex] = useState(-1);
  const [loopCount, setLoopCount] = useState(1);
  const [currentLoop, setCurrentLoop] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  // Step-by-step mode
  const [stepByStep, setStepByStep] = useState(false);
  const [stepCursor, setStepCursor] = useState(0); // next step to run

  const activeSteps = preloadedSteps ?? (selectedScenario?.steps as Array<Record<string, any>> | undefined);
  const activeVariables: Record<string, any> = flattenVarDefs(
    preloadedVariables ?? (selectedScenario?.variables as Record<string, any> | undefined) ?? {}
  );

  const handlePlay = useCallback(async () => {
    if (!activeSteps?.length || !serial) return;
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
              setCurrentStepIndex(0);
            } else if (event.event === 'step_done') {
              const result: PreviewStepResult = {
                index: event.index,
                type: event.type,
                ok: event.ok,
                message: event.message,
              };
              setResults((prev) => [...prev, result]);
              setCurrentStepIndex(event.index + 1);
            }
            // 'done' and 'error' events handled by promise completion
          },
          ctrl.signal,
          activeVariables,
        );
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setResults((prev) => [...prev, { index: currentStepIndex, ok: false, message: String(e) }]);
      }
    } finally {
      setPlaying(false);
      onPlayingChange?.(false);
      setCurrentStepIndex(-1);
      abortRef.current = null;
    }
  }, [activeSteps, activeVariables, serial, loopCount, currentStepIndex]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    setPlaying(false);
  }, []);

  const handleRunOneStep = useCallback(async () => {
    if (!activeSteps?.length || !serial || playing) return;
    const idx = stepCursor;
    if (idx >= activeSteps.length) return;
    const step = activeSteps[idx];
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
          if (event.event === 'step_done') {
            setResults((prev) => {
              const next = prev.filter((r) => r.index !== idx);
              return [...next, { index: idx, type: event.type, ok: event.ok, message: event.message }];
            });
          }
        },
        ctrl.signal,
        activeVariables,
      );
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setResults((prev) => [...prev.filter((r) => r.index !== idx), { index: idx, ok: false, message: String(e) }]);
      }
    } finally {
      setPlaying(false);
      setCurrentStepIndex(-1);
      abortRef.current = null;
      if (!ctrl.signal.aborted) setStepCursor(idx + 1);
    }
  }, [activeSteps, serial, playing, stepCursor]);

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
          <p className='text-xs text-muted-foreground py-4 text-center'>No campaigns found</p>
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
          <Button size='sm' variant='ghost' onClick={() => setSelectedCampaignId(null)}>
            <ArrowLeft className='mr-1 size-3.5' />
            Campaigns
          </Button>
          <span className='text-sm font-medium'>Select Scenario</span>
        </div>
        {scenarios.length === 0 ? (
          <p className='text-xs text-muted-foreground py-4 text-center'>No scenarios in this campaign</p>
        ) : (
          <div className='space-y-1'>
            {scenarios.map((s) => (
              <Button
                key={s.id}
                variant='outline'
                size='sm'
                className='w-full justify-start text-xs flex-col items-start h-auto py-2'
                onClick={() => setSelectedScenario(s)}
              >
                <span className='font-medium'>{s.name}</span>
                <span className='text-[10px] text-muted-foreground'>{s.steps.length} steps</span>
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

  return (
    <div className='space-y-3'>
      <div className='flex items-center gap-2'>
        <Button size='sm' variant='ghost' onClick={preloadedSteps ? onClose : () => { setSelectedScenario(null); setResults([]); }}>
          <ArrowLeft className='mr-1 size-3.5' />
          {preloadedSteps ? 'Đóng' : 'Scenarios'}
        </Button>
        <span className='truncate text-sm font-medium'>{displayName || 'Kịch bản hiện tại'}</span>
        <div className='flex-1' />
        {/* Mode toggle */}
        <Button
          size='sm'
          variant={stepByStep ? 'secondary' : 'outline'}
          className='h-7 gap-1 px-2 text-[11px]'
          onClick={() => { setStepByStep(!stepByStep); setResults([]); setStepCursor(0); }}
          disabled={playing}
          title={stepByStep ? 'Chuyển sang chạy toàn bộ' : 'Chuyển sang chạy từng bước'}
        >
          <StepForward className='size-3.5' />
          {stepByStep ? 'Từng bước' : 'Tất cả'}
        </Button>

        {stepByStep ? (
          <>
            <Button
              size='sm'
              variant='outline'
              className='h-7 gap-1 px-2 text-[11px]'
              onClick={() => { setResults([]); setStepCursor(0); }}
              disabled={playing}
              title='Reset về bước đầu'
            >
              <ListRestart className='size-3.5' />
            </Button>
            {playing ? (
              <Button size='sm' variant='destructive' onClick={handleStop} className='h-7 px-3 text-xs'>
                <Square className='mr-1 size-3.5' />
                Stop
              </Button>
            ) : (
              <Button
                size='sm'
                onClick={handleRunOneStep}
                disabled={!activeSteps?.length || stepCursor >= (activeSteps?.length ?? 0)}
                className='h-7 gap-1 px-3 text-xs'
              >
                <StepForward className='size-3.5' />
                Bước {stepCursor + 1}/{activeSteps?.length ?? 0}
              </Button>
            )}
          </>
        ) : (
          <>
            {/* Loop count */}
            <div className='flex items-center gap-1'>
              <label className='text-[10px] text-muted-foreground'>Loop</label>
              <input
                type='number'
                min={1}
                max={100}
                value={loopCount}
                onChange={(e) => setLoopCount(Math.max(1, Math.min(100, +e.target.value || 1)))}
                disabled={playing}
                className='w-12 rounded border bg-background px-1.5 py-0.5 text-xs text-center'
              />
            </div>
            {playing ? (
              <Button size='sm' variant='destructive' onClick={handleStop}>
                <Square className='mr-1 size-3.5' />
                Stop
              </Button>
            ) : (
              <Button size='sm' onClick={handlePlay}>
                <Play className='mr-1 size-3.5' />
                Play
              </Button>
            )}
          </>
        )}
      </div>

      {/* Loop progress */}
      {playing && loopCount > 1 && (
        <div className='text-[11px] text-muted-foreground'>
          Run {currentLoop}/{loopCount}
        </div>
      )}

      {/* Step list with results */}
      <div className='max-h-[400px] space-y-1 overflow-y-auto rounded border border-border/60 bg-muted/30 p-2'>
        {steps.map((step, i) => {
          const result = results.find((r) => r.index === i);
          const isRunning = playing && i === currentStepIndex;
          const isCursor = stepByStep && !playing && i === stepCursor && !result;
          const isPending = playing && i > currentStepIndex && !result;
          return (
            <div
              key={i}
              className={`flex items-center gap-2 rounded px-2 py-1.5 text-xs transition-colors ${
                isRunning ? 'bg-primary/10 ring-1 ring-primary/30' :
                isCursor ? 'bg-amber-500/10 ring-1 ring-amber-400/40' :
                result?.ok ? 'bg-emerald-500/10' :
                result && !result.ok ? 'bg-red-500/10' :
                'bg-background'
              }`}
            >
              {/* Status icon */}
              <span className='flex-shrink-0'>
                {isRunning ? (
                  <Loader2 className='size-3.5 animate-spin text-primary' />
                ) : result?.ok ? (
                  <CheckCircle2 className='size-3.5 text-emerald-500' />
                ) : result && !result.ok ? (
                  <XCircle className='size-3.5 text-red-500' />
                ) : isPending ? (
                  <span className='text-muted-foreground/50 text-[10px]'>{i + 1}</span>
                ) : (
                  <span className='text-muted-foreground text-[10px]'>{i + 1}</span>
                )}
              </span>

              {/* Step description */}
              <span className='min-w-0 flex-1 overflow-hidden'>
                <span className='block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground leading-tight'>
                  {getStepTypeName(step.type)}
                </span>
                {(() => {
                  const summary = getStepSummary(step as unknown as FlowStep);
                  return summary ? (
                    <span className='block truncate text-xs font-mono leading-tight' title={summary}>
                      {summary}
                    </span>
                  ) : null;
                })()}
              </span>

              {/* Fallback badge */}
              {result?.ok && (result as any).method === 'fallback_position' && (
                <span className='flex-shrink-0 rounded bg-amber-500/15 px-1 py-0.5 text-[9px] text-amber-600 dark:text-amber-400'>
                  fallback
                </span>
              )}

              {/* Info popover for step result details */}
              {result && result.message && (
                <Popover>
                  <PopoverTrigger asChild>
                    <button className={`flex-shrink-0 rounded p-0.5 hover:bg-accent ${
                      result.ok ? 'text-emerald-500' : 'text-red-500'
                    }`}>
                      <Info className='size-3.5' />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent side='left' align='start' className='w-80 p-3'>
                    <div className='space-y-1.5'>
                      <div className='flex items-center gap-1.5 text-xs font-medium'>
                        {result.ok ? (
                          <CheckCircle2 className='size-3.5 text-emerald-500' />
                        ) : (
                          <XCircle className='size-3.5 text-red-500' />
                        )}
                        Step {i + 1}: {step.type}
                      </div>
                      <p className={`text-[11px] break-words ${result.ok ? 'text-muted-foreground' : 'text-red-500'}`}>
                        {result.message}
                      </p>
                    </div>
                  </PopoverContent>
                </Popover>
              )}
            </div>
          );
        })}
      </div>

      {/* Summary */}
      {results.length > 0 && !playing && (
        <div className='text-xs text-muted-foreground'>
          {results.filter((r) => r.ok).length}/{steps.length} steps passed
          {loopCount > 1 && ` (${currentLoop} loops completed)`}
        </div>
      )}
    </div>
  );
}
