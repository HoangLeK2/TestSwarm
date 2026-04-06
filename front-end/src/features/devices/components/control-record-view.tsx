'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { DeviceTile } from './device-tile';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Circle,
  Square,
  Copy,
  Plus,
  Save,
  ArrowLeft,
  Play,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Video,
  Clapperboard,
  Crosshair,
  HelpCircle,
  SlidersHorizontal,
  MousePointerClick,
  Timer,
  Keyboard,
  CheckSquare,
  PackagePlus,
  Code2,
  GitBranch,
  List,
} from 'lucide-react';
import dynamic from 'next/dynamic';

// Dynamic import để tránh lỗi InversifyJS "Ambiguous FlowRendererRegistry" khi SSR
const FlowgramCanvas = dynamic(
  () => import('@/features/scenario-templates/components/scenario-flow-editor/canvas').then((m) => m.FlowgramCanvas),
  { ssr: false, loading: () => <div className='flex flex-1 items-center justify-center text-xs text-muted-foreground'>Đang tải canvas…</div> },
);
import { VariableEditor } from '@/components/variable-editor';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useControlRecord } from '../hooks/use-control-record';
import { XmlTreeViewer } from './control-record/xml-tree-viewer';
import { ScenarioPlayer } from './control-record/scenario-player';
import { FlowEditor } from '@/features/campaigns/components/flow-editor';
import {
  applySelectorToSteps,
  type SelectorPickTarget,
} from '@/features/campaigns/components/flow-editor';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { findSelectorInXml } from '../utils/control-record-xml';
import { parseHierarchyTree, findNodeIdAtRatio } from '../utils/hierarchy-tree';
import { previewScenarioStream } from '../services/api';
import { useTranslations } from 'next-intl';

/**
 * Template variables are stored as metadata dicts:
 *   {"GROUP_NAME": {"type": "string", "default": "foo", "description": "..."}}
 * Flatten them to plain values so they can be used at runtime:
 *   {"GROUP_NAME": "foo"}
 */
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

type Props = { initialSerial?: string | null; initialCampaignId?: string | null; initialScenarioId?: string | null };

export function ControlRecordView({ initialSerial, initialCampaignId, initialScenarioId }: Props = {}) {
  const t = useTranslations('devicesControlRecord.view');
  const { error, device, record, steps, save, hierarchy, selector } = useControlRecord(initialSerial, initialCampaignId, initialScenarioId);
  const { setSkipTapRecordingWhilePick } = record;

  const [highlightBounds, setHighlightBounds] = useState<[number, number, number, number] | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [playerMode, setPlayerMode] = useState(false);
  const [selectorPickTarget, setSelectorPickTarget] = useState<SelectorPickTarget | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [flowMode, setFlowMode] = useState(false);
  // Track steps updated from the flowgram canvas (used for saving in flow mode)
  const flowStepsRef = useRef<typeof steps.items>(steps.items);
  const [varDialogOpen, setVarDialogOpen] = useState(false);
  const [installDialogOpen, setInstallDialogOpen] = useState(false);
  const [installUrl, setInstallUrl] = useState('');
  const [jsonDialogOpen, setJsonDialogOpen] = useState(false);

  // Inline step runner (step-by-step without entering player mode)
  const [stepRunStates, setStepRunStates] = useState<Record<number, 'idle' | 'running' | 'ok' | 'error'>>({});
  const stepRunAbortRef = useRef<AbortController | null>(null);

  // Variables for step execution (synced from loaded scenario, editable inline)
  const [scenarioVariables, setScenarioVariables] = useState<Record<string, any>>(
    () => flattenVarDefs(save.editingContext?.variables ?? {})
  );
  useEffect(() => {
    if (save.editingContext?.variables) {
      setScenarioVariables(flattenVarDefs(save.editingContext.variables));
    }
  }, [save.editingContext]);

  const handleRunStep = useCallback(
    async (step: FlowStep, index: number) => {
      if (!device.selectedDevice) { toast.warning('Chưa chọn thiết bị'); return; }
      if (stepRunStates[index] === 'running') return;
      stepRunAbortRef.current?.abort();
      const ctrl = new AbortController();
      stepRunAbortRef.current = ctrl;
      setStepRunStates((s) => ({ ...s, [index]: 'running' }));
      try {
        await previewScenarioStream(
          device.selectedDevice.serial,
          [step as Record<string, any>],
          (event) => {
            if (event.event === 'step_done') {
              setStepRunStates((s) => ({ ...s, [index]: event.ok ? 'ok' : 'error' }));
              if (!event.ok) toast.error(`Bước ${index + 1}: ${event.message ?? 'Lỗi'}`);
            }
          },
          ctrl.signal,
          scenarioVariables,
        );
      } catch (e) {
        if (!ctrl.signal.aborted) {
          setStepRunStates((s) => ({ ...s, [index]: 'error' }));
          toast.error(`Bước ${index + 1}: ${String(e)}`);
        }
      } finally {
        if (!ctrl.signal.aborted) {
          // Reset to idle after 3s so indicator fades
          setTimeout(() => setStepRunStates((s) => {
            const n = { ...s };
            if (n[index] !== 'running') delete n[index];
            return n;
          }), 3000);
        }
      }
    },
    [device.selectedDevice, stepRunStates, scenarioVariables],
  );

  const addStepFromSelector = useCallback(
    (stepType: 'tap_selector' | 'long_tap_selector' | 'wait_element' | 'assert_element' | 'input_selector') => {
      const by = selector.by as string;
      const value = selector.value;
      if (!value) return;
      const newStep: FlowStep = stepType === 'tap_selector'
        ? { type: 'tap_selector', by, value }
        : stepType === 'long_tap_selector'
        ? { type: 'long_tap_selector', by, value, duration_ms: 800 }
        : stepType === 'wait_element'
        ? { type: 'wait_element', by, value, timeout: 10 }
        : stepType === 'assert_element'
        ? { type: 'assert_element', by, value, timeout: 5 }
        : { type: 'input_selector', by, value, text: '', clear_first: true };
      const id = `step-${Date.now()}-${steps.items.length}`;
      steps.setItems([...(steps.items as any[]), { ...newStep, _id: id }] as any);
      toast.success(`Đã thêm bước ${stepType}`);
    },
    [selector.by, selector.value, steps],
  );

  useEffect(() => {
    setSkipTapRecordingWhilePick(selectorPickTarget != null);
    return () => setSkipTapRecordingWhilePick(false);
  }, [selectorPickTarget, setSkipTapRecordingWhilePick]);

  const applySelectorPick = useCallback(
    (by: string, value: string) => {
      if (!selectorPickTarget) return;
      const raw = steps.items as FlowStep[];
      const next = applySelectorToSteps(raw, selectorPickTarget, by, value);
      if (next === raw) {
        toast.warning(t('pickSelectorNoElement'));
        return;
      }
      steps.setItems(
        next.map((s: FlowStep, i: number) => ({
          ...s,
          _id: (s as { _id?: string })._id || `step-${Date.now()}-${i}`,
        })) as any,
      );
      selector.setBy(by as typeof selector.by);
      selector.setValue(value);
      setSelectorPickTarget(null);
      toast.success(t('pickSelectorApplied', { by, value: value.slice(0, 48) }));
    },
    [selectorPickTarget, steps, selector, t],
  );

  // When user taps the phone screen → hierarchy highlight + optional selector pick
  const handleScreenTap = useCallback(
    (rx: number, ry: number) => {
      const tree = parseHierarchyTree(hierarchy.xml);
      if (tree) {
        const nodeId = findNodeIdAtRatio(tree, rx, ry);
        setSelectedNodeId(nodeId);
      }

      if (selectorPickTarget) {
        const sel = findSelectorInXml(hierarchy.xml, rx, ry);
        if (sel?.value) {
          applySelectorPick(sel.by, sel.value);
        } else {
          toast.warning(t('pickSelectorNoElement'));
        }
        return;
      }
    },
    [hierarchy.xml, selectorPickTarget, applySelectorPick, t],
  );

  // ── Error / empty states ─────────────────────────────────────────────────
  if (error) {
    return (
      <div className='rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive'>
        {error}
      </div>
    );
  }

  if (device.connectedDevices.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-20 text-center'>
        <Video className='mb-3 size-10 text-muted-foreground/40' />
        <p className='mb-1 text-base font-medium'>{t('noDeviceConnected')}</p>
        <p className='mb-4 text-sm text-muted-foreground'>Kết nối thiết bị Android qua USB hoặc Wi-Fi để bắt đầu</p>
        <Button asChild size='sm' variant='outline'>
          <Link href={ROUTES.DEVICES.MANAGE}>
            <ArrowLeft className='mr-1.5 size-4' />
            {t('addDevice')}
          </Link>
        </Button>
      </div>
    );
  }

  const { selectedDevice } = device;

  return (
    <div className='flex h-[calc(100vh-80px)] flex-col overflow-hidden bg-background'>

      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div className='flex shrink-0 items-center gap-3 border-b bg-background px-3 py-2'>
        {/* Back */}
        <Button asChild variant='ghost' size='sm' className='-ml-1 shrink-0 gap-1.5 text-muted-foreground hover:text-foreground'>
          <Link href={ROUTES.DEVICES.ROOT}>
            <ArrowLeft className='size-3.5' />
            Farm
          </Link>
        </Button>

        <div className='h-5 w-px bg-border' />

        {/* Title */}
        <div className='min-w-0 flex-1'>
          <p className='truncate text-sm font-semibold leading-tight'>
            {save.editingContext ? save.editingContext.name : t('pageTitle')}
          </p>
          <p className='text-[10px] text-muted-foreground'>{t('pageEyebrow')}</p>
        </div>

        {save.editingContext && (
          <span className='shrink-0 inline-flex items-center rounded-full border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-300'>
            Đang chỉnh sửa
          </span>
        )}

        {/* Device selector */}
        <Select
          value={device.selectedSerial ?? ''}
          onValueChange={(v) => device.setSelectedSerial(v || null)}
        >
          <SelectTrigger className='h-8 w-[220px] shrink-0 text-xs'>
            <SelectValue placeholder={t('selectPhonePlaceholder')} />
          </SelectTrigger>
          <SelectContent>
            {device.connectedDevices.map((d) => (
              <SelectItem key={d.serial} value={d.serial} className='text-xs'>
                {d.brand} {d.model} — {d.serial.slice(0, 10)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* WS status dot */}
        <span className={cn(
          'shrink-0 inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[11px] font-medium',
          device.wsConnected
            ? 'border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-400'
            : 'border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-400',
        )}>
          <span className={cn('size-1.5 rounded-full', device.wsConnected ? 'bg-green-500' : 'bg-red-500')} />
          {device.wsConnected ? 'Online' : 'Offline'}
        </span>

        <div className='h-5 w-px bg-border' />

        {/* Flow / List mode toggle */}
        <Button
          size='sm'
          variant={flowMode ? 'default' : 'outline'}
          className='h-8 gap-1.5 shrink-0 text-xs'
          onClick={() => {
            if (!flowMode) {
              // Entering flow mode — sync current steps into ref
              flowStepsRef.current = steps.items;
            } else {
              // Leaving flow mode — write canvas steps back to list
              steps.setItems(flowStepsRef.current);
            }
            setFlowMode((v) => !v);
          }}
          title={flowMode ? 'Chuyển về danh sách bước' : 'Chuyển sang Flow Editor trực quan'}
        >
          {flowMode ? <List className='size-3.5' /> : <GitBranch className='size-3.5' />}
          {flowMode ? 'Danh sách' : 'Flow'}
        </Button>
      </div>

      {/* ── Flow Mode: Left=canvas, Right=phone ─────────────────────────── */}
      {flowMode && (
        <div className='flex flex-1 overflow-hidden'>
          {/* Canvas — needs `relative` so flowgram layers (position:absolute) are clipped */}
          <div className='relative flex flex-1 flex-col overflow-hidden border-r border-border/60'>
            <FlowgramCanvas
              key={`flow-${steps.items.length > 0 ? 'has-steps' : 'empty'}`}
              steps={steps.items as any}
              onStepsChange={(newSteps) => {
                flowStepsRef.current = newSteps as any;
              }}
            />
          </div>
          {/* Phone */}
          <div className='flex w-[320px] shrink-0 flex-col items-center bg-muted/20 overflow-y-auto'>
            {selectedDevice ? (
              <>
                <div className='flex w-full shrink-0 items-center gap-2 border-b border-border/40 bg-background/60 px-3 py-1.5'>
                  <span className={cn('size-2 rounded-full shrink-0', device.wsConnected ? 'bg-green-500' : 'bg-muted-foreground/40')} />
                  <span className='truncate text-[11px] font-medium'>
                    {selectedDevice.brand} {selectedDevice.model}
                  </span>
                  <span className='ml-auto font-mono text-[10px] text-muted-foreground'>
                    {selectedDevice.serial.slice(0, 10)}
                  </span>
                </div>
                <div className='p-3 w-full'>
                  <DeviceTile
                    device={selectedDevice}
                    logLines={device.logs[selectedDevice.serial] ?? []}
                    mode={device.mode}
                    wsSend={record.sendAndRecord}
                    onToggleMode={record.handleToggleMode}
                    onRestart={record.handleRestart}
                    onTap={handleScreenTap}
                    highlightBounds={highlightBounds}
                  />
                </div>
              </>
            ) : (
              <div className='flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center'>
                <Video className='size-8 text-muted-foreground/30' strokeWidth={1.25} />
                <p className='text-xs text-muted-foreground'>Chọn thiết bị từ thanh trên</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 3-column main layout (list mode) ────────────────────────────── */}
      {!flowMode && <div className='flex flex-1 overflow-hidden'>

        {/* ── COL 1: UI Hierarchy tree ──────────────────────────────────── */}
        <div className={cn(
          'flex shrink-0 flex-col border-r border-border/60 bg-muted/10 transition-all duration-200',
          leftCollapsed ? 'w-0 overflow-hidden' : 'w-[272px]',
        )}>
          {/* Tree */}
          <div className='min-h-0 flex-1 overflow-hidden'>
            <XmlTreeViewer
              xml={hierarchy.xml}
              loading={hierarchy.loading}
              onNodeSelect={({ bounds, by, value, nodeId }) => {
                setHighlightBounds(bounds);
                if (nodeId != null) setSelectedNodeId(nodeId);
                if (selectorPickTarget) {
                  if (value?.trim()) applySelectorPick(by, value.trim());
                  else toast.warning(t('pickSelectorNoElement'));
                  return;
                }
                selector.setBy(by as typeof selector.by);
                selector.setValue(value);
              }}
              selectedNodeId={selectedNodeId}
              onRefresh={() => selectedDevice && hierarchy.refresh()}
              autoRefresh={hierarchy.autoRefresh}
              onAutoRefreshChange={hierarchy.setAutoRefresh}
            />
          </div>

          {/* Selector bar */}
          <div className={cn(
            'shrink-0 border-t border-border/60 px-2.5 py-2',
            selector.value ? 'bg-primary/5' : 'bg-muted/30',
          )}>
            {selector.value ? (
              <>
                <div className='flex items-center gap-1.5 pb-1.5'>
                  <span className='min-w-0 flex-1 truncate font-mono text-[10px] text-muted-foreground'>
                    <span className='font-bold text-primary'>[{selector.by}]</span> {selector.value}
                  </span>
                  <Button size='sm' variant='secondary' className='h-5 shrink-0 px-1.5 text-[9px]' onClick={selector.tap} disabled={!selectedDevice}>
                    Tap
                  </Button>
                </div>
                <div className='flex flex-wrap gap-1'>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => addStepFromSelector('tap_selector')}
                        className='flex items-center gap-0.5 rounded bg-blue-500/10 px-1.5 py-0.5 text-[9px] font-medium text-blue-700 hover:bg-blue-500/20 dark:text-blue-400'
                      >
                        <MousePointerClick className='size-2.5' /> Tap
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>Thêm bước tap_selector</TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => addStepFromSelector('long_tap_selector')}
                        className='flex items-center gap-0.5 rounded bg-purple-500/10 px-1.5 py-0.5 text-[9px] font-medium text-purple-700 hover:bg-purple-500/20 dark:text-purple-400'
                      >
                        <MousePointerClick className='size-2.5' /> Long
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>Thêm bước long_tap_selector</TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => addStepFromSelector('wait_element')}
                        className='flex items-center gap-0.5 rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-medium text-amber-700 hover:bg-amber-500/20 dark:text-amber-400'
                      >
                        <Timer className='size-2.5' /> Wait
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>Thêm bước wait_element</TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => addStepFromSelector('assert_element')}
                        className='flex items-center gap-0.5 rounded bg-green-500/10 px-1.5 py-0.5 text-[9px] font-medium text-green-700 hover:bg-green-500/20 dark:text-green-400'
                      >
                        <CheckSquare className='size-2.5' /> Assert
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>Thêm bước assert_element</TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => addStepFromSelector('input_selector')}
                        className='flex items-center gap-0.5 rounded bg-orange-500/10 px-1.5 py-0.5 text-[9px] font-medium text-orange-700 hover:bg-orange-500/20 dark:text-orange-400'
                      >
                        <Keyboard className='size-2.5' /> Input
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-[10px]'>Thêm bước input_selector</TooltipContent>
                  </Tooltip>
                </div>
              </>
            ) : (
              <p className='text-[10px] text-muted-foreground'>{t('selectorBarHint')}</p>
            )}
          </div>
        </div>

        {/* Collapse toggle button */}
        <button
          type='button'
          onClick={() => setLeftCollapsed(!leftCollapsed)}
          className='relative z-10 flex w-4 shrink-0 items-center justify-center border-r border-border/40 bg-muted/20 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground'
          title={leftCollapsed ? 'Mở cây giao diện' : 'Thu cây giao diện'}
        >
          {leftCollapsed ? <ChevronRight className='size-3' /> : <ChevronLeft className='size-3' />}
        </button>

        {/* ── COL 2: Phone screen ───────────────────────────────────────── */}
        <div className='flex w-[320px] shrink-0 flex-col items-center border-r border-border/60 bg-muted/20 overflow-y-auto'>
          {selectedDevice ? (
            <>
              {/* Device label */}
              <div className='flex w-full shrink-0 items-center gap-2 border-b border-border/40 bg-background/60 px-3 py-1.5'>
                <span className={cn('size-2 rounded-full shrink-0', device.wsConnected ? 'bg-green-500' : 'bg-muted-foreground/40')} />
                <span className='truncate text-[11px] font-medium text-foreground'>
                  {selectedDevice.brand} {selectedDevice.model}
                </span>
                <span className='ml-auto font-mono text-[10px] text-muted-foreground'>
                  {selectedDevice.serial.slice(0, 10)}
                </span>
              </div>
              <div className='p-3 w-full'>
                <DeviceTile
                  device={selectedDevice}
                  logLines={device.logs[selectedDevice.serial] ?? []}
                  mode={device.mode}
                  wsSend={record.sendAndRecord}
                  onToggleMode={record.handleToggleMode}
                  onRestart={record.handleRestart}
                  onTap={handleScreenTap}
                  highlightBounds={highlightBounds}
                />
              </div>
            </>
          ) : (
            <div className='flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center'>
              <Video className='size-8 text-muted-foreground/30' strokeWidth={1.25} />
              <p className='text-xs text-muted-foreground'>Chọn thiết bị từ thanh trên</p>
            </div>
          )}
        </div>

        {/* ── COL 3: Recording / scenario editor ───────────────────────── */}
        <div className='flex flex-1 flex-col overflow-hidden'>

          {playerMode && selectedDevice ? (
            /* Player mode */
            <div className='flex flex-1 flex-col overflow-auto p-4'>
              <ScenarioPlayer
                serial={selectedDevice.serial}
                onClose={() => setPlayerMode(false)}
                onPlayingChange={hierarchy.setPaused}
                preloadedSteps={steps.items.length > 0 ? (steps.items as any[]) : undefined}
                preloadedName={save.editingContext?.name}
                preloadedVariables={scenarioVariables}
              />
            </div>
          ) : (
            <>
              {/* Recording bar */}
              {record.recording ? (
                <div className='flex shrink-0 items-center gap-3 border-b border-red-200/60 bg-red-50/80 px-4 py-2.5 dark:border-red-900/30 dark:bg-red-950/20'>
                  <span className='relative flex size-2.5 shrink-0'>
                    <span className='absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75' />
                    <span className='relative inline-flex size-2.5 rounded-full bg-red-500' />
                  </span>
                  <span className='text-xs font-semibold text-red-800 dark:text-red-300'>{t('recordingActive')}</span>
                  {steps.items.length > 0 && (
                    <span className='rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-700 dark:bg-red-900/40 dark:text-red-300'>
                      {steps.items.length} bước
                    </span>
                  )}
                  {record.pollingXml && (
                    <RefreshCw size={11} className='animate-spin text-red-500/70' />
                  )}
                  <Button
                    size='sm'
                    variant='destructive'
                    className='ml-auto h-7 gap-1.5 px-3 text-xs'
                    onClick={() => void record.toggleRecording()}
                  >
                    <Square className='size-3' />
                    {t('stopRecording')}
                  </Button>
                </div>
              ) : (
                <div className='flex shrink-0 items-center gap-2 border-b border-border/60 bg-background px-4 py-2'>
                  <div className='min-w-0 flex-1'>
                    <p className='text-[11px] font-semibold text-foreground'>{t('recordingIdleTitle')}</p>
                    <p className='text-[10px] text-muted-foreground'>{t.rich('recordingIdleSubtitle', { strong: (c) => <strong>{c}</strong> })}</p>
                  </div>
                  <Button
                    size='sm'
                    variant='default'
                    className='h-8 shrink-0 gap-1.5 text-xs'
                    onClick={() => void record.toggleRecording()}
                    disabled={!selectedDevice}
                  >
                    <Circle className='size-3 fill-current' />
                    {t('startRecording')}
                  </Button>
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-8 shrink-0 gap-1.5 text-xs'
                    onClick={() => setPlayerMode(true)}
                    disabled={!selectedDevice}
                  >
                    <Play className='size-3' />
                    {t('tryRun')}
                  </Button>
                </div>
              )}

              {/* Selector pick banner */}
              {selectorPickTarget && (
                <div className='flex shrink-0 items-center gap-2 border-b border-amber-400/30 bg-amber-50/80 px-4 py-2 dark:bg-amber-950/20'>
                  <Crosshair className='size-3.5 shrink-0 text-amber-600' />
                  <p className='flex-1 text-[11px] text-amber-800 dark:text-amber-300'>{t('pickSelectorBanner')}</p>
                  <button
                    type='button'
                    className='text-[10px] text-amber-700 underline underline-offset-2 hover:no-underline dark:text-amber-400'
                    onClick={() => setSelectorPickTarget(null)}
                  >
                    Huỷ
                  </button>
                </div>
              )}

              {/* Section header */}
              <div className='flex shrink-0 items-center gap-2 border-b border-border/40 bg-muted/20 px-4 py-1.5'>
                <Clapperboard className='size-3.5 shrink-0 text-muted-foreground' />
                <span className='text-[11px] font-semibold text-foreground'>
                  {t('editorSectionTitle')}
                </span>
                {steps.items.length > 0 && (
                  <span className='rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary'>
                    {steps.items.length} bước
                  </span>
                )}
                <div className='flex-1' />
                {/* Workflow breadcrumb */}
                <div className='hidden items-center gap-1 sm:flex'>
                  {[
                    { label: '① Ghi', done: steps.items.length > 0 },
                    { label: '② Chỉnh', done: false },
                    { label: '③ Lưu', done: false },
                  ].map(({ label, done }) => (
                    <span key={label} className={`text-[9px] font-medium ${done ? 'text-primary' : 'text-muted-foreground/50'}`}>
                      {label}
                    </span>
                  ))}
                </div>
                {/* Variables editor button */}
                <Tooltip delayDuration={400}>
                  <TooltipTrigger asChild>
                    <button
                      type='button'
                      onClick={() => setVarDialogOpen(true)}
                      className={cn(
                        'flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors',
                        Object.keys(scenarioVariables).length > 0
                          ? 'bg-primary/10 text-primary hover:bg-primary/20'
                          : 'text-muted-foreground hover:bg-muted',
                      )}
                    >
                      <SlidersHorizontal className='size-3' />
                      Biến
                      {Object.keys(scenarioVariables).length > 0 && (
                        <span className='rounded-full bg-primary/20 px-1 text-[9px] font-bold'>
                          {Object.keys(scenarioVariables).length}
                        </span>
                      )}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side='bottom' className='text-xs'>
                    Chỉnh biến — giá trị thay thế cho {'${VAR}'} khi chạy thử bước
                  </TooltipContent>
                </Tooltip>

                <Tooltip delayDuration={400}>
                  <TooltipTrigger asChild>
                    <button type='button' className='rounded-full p-0.5 text-muted-foreground hover:bg-muted'>
                      <HelpCircle className='size-3.5' />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side='bottom' className='max-w-xs text-xs'>{t('tooltipScenarioSection')}</TooltipContent>
                </Tooltip>
              </div>

              {/* Flow editor */}
              <div className='min-h-0 flex-1 overflow-hidden px-3 pb-2'>
                {steps.items.length === 0 ? (
                  <div className='flex h-full flex-col justify-center gap-4 overflow-y-auto rounded-xl border border-dashed border-border/50 bg-muted/10 px-5 py-6'>
                    {/* Guide header */}
                    <div className='text-center'>
                      <p className='text-sm font-semibold text-foreground'>Cách tạo kịch bản</p>
                      <p className='mt-0.5 text-[11px] text-muted-foreground'>Làm theo 3 bước đơn giản dưới đây</p>
                    </div>

                    {/* Steps */}
                    <ol className='space-y-3'>
                      {[
                        {
                          n: '1',
                          icon: <Circle className='size-4 fill-current text-primary' />,
                          title: 'Bắt đầu ghi',
                          desc: 'Nhấn nút "Bắt đầu ghi" phía trên, rồi thao tác trên màn hình điện thoại.',
                          active: !record.recording,
                        },
                        {
                          n: '2',
                          icon: <Square className='size-4 text-red-500' />,
                          title: 'Dừng ghi',
                          desc: 'Nhấn "Dừng ghi" khi đã thực hiện đủ các thao tác cần kịch bản.',
                          active: record.recording,
                        },
                        {
                          n: '3',
                          icon: <Save className='size-4 text-emerald-600' />,
                          title: 'Lưu kịch bản',
                          desc: 'Kiểm tra lại danh sách bước, chỉnh sửa nếu cần rồi nhấn "Lưu kịch bản".',
                          active: false,
                        },
                      ].map(({ n, icon, title, desc, active }) => (
                        <li key={n} className={`flex gap-3 rounded-lg px-3 py-2.5 transition-colors ${active ? 'bg-primary/8 ring-1 ring-primary/20' : 'bg-background/60'}`}>
                          <div className={`flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${active ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'}`}>
                            {n}
                          </div>
                          <div className='min-w-0'>
                            <div className='flex items-center gap-1.5'>
                              {icon}
                              <span className='text-[12px] font-semibold text-foreground'>{title}</span>
                              {active && <span className='rounded-full bg-primary/15 px-1.5 py-px text-[9px] font-bold text-primary'>Bước hiện tại</span>}
                            </div>
                            <p className='mt-0.5 text-[11px] leading-relaxed text-muted-foreground'>{desc}</p>
                          </div>
                        </li>
                      ))}
                    </ol>

                    <Button
                      size='sm'
                      className='mx-auto gap-1.5'
                      onClick={() => void record.toggleRecording()}
                      disabled={!selectedDevice}
                    >
                      <Circle className='size-3 fill-current' />
                      {t('startRecording')}
                    </Button>
                  </div>
                ) : (
                  <div className='h-full overflow-hidden rounded-lg border border-border/50 bg-background'>
                    <FlowEditor
                      steps={steps.items as FlowStep[]}
                      onChange={(newSteps) =>
                        steps.setItems(
                          newSteps.map((s: FlowStep, i: number) => ({
                            ...s,
                            _id: (s as any)._id || `step-${Date.now()}-${i}`,
                          })) as any
                        )
                      }
                      maxHeight='calc(100vh - 300px)'
                      selectorPickTarget={selectorPickTarget}
                      onSelectorPickTargetChange={setSelectorPickTarget}
                      onRunStep={selectedDevice ? handleRunStep : undefined}
                      stepRunStates={stepRunStates}
                    />
                  </div>
                )}
              </div>

              {/* Action bar */}
              <div className='flex shrink-0 items-center gap-1.5 border-t border-border/60 bg-background/80 px-3 py-2.5'>
                {/* Install APK */}
                <Tooltip delayDuration={300}>
                  <TooltipTrigger asChild>
                    <Button
                      size='sm'
                      variant='outline'
                      className='h-7 gap-1 text-xs'
                      onClick={() => setInstallDialogOpen(true)}
                      disabled={!selectedDevice}
                    >
                      <PackagePlus className='size-3' />
                      Cài APK
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side='top' className='text-xs'>Cài APK từ URL lên thiết bị</TooltipContent>
                </Tooltip>

                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size='sm' variant='outline' className='h-7 gap-1 text-xs'>
                      <Plus className='size-3' />
                      Luồng
                      <ChevronDown className='size-3' />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align='start' className='w-56'>
                    <DropdownMenuLabel className='pb-0.5 pt-2'>
                      <span className='block text-[11px] font-bold text-foreground'>Chờ / Delay</span>
                    </DropdownMenuLabel>
                    <DropdownMenuItem className='gap-2 text-xs' onClick={steps.addWait}>
                      <StepIcon type='wait' size={13} /> Chờ (giây)
                    </DropdownMenuItem>
                    <DropdownMenuItem className='gap-2 text-xs' onClick={() => steps.addFlow('wait_element')}>
                      <StepIcon type='wait_element' size={13} /> Chờ phần tử xuất hiện
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel className='pb-0.5 pt-1'>
                      <span className='block text-[11px] font-bold text-foreground'>Điều kiện</span>
                    </DropdownMenuLabel>
                    <DropdownMenuItem className='gap-2 text-xs' onClick={() => steps.addFlow('if_element')}>
                      <StepIcon type='if_element' size={13} /> Nếu phần tử tồn tại
                    </DropdownMenuItem>
                    <DropdownMenuItem className='gap-2 text-xs' onClick={() => steps.addFlow('if_variable')}>
                      <StepIcon type='if_variable' size={13} /> Nếu biến thỏa điều kiện
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel className='pb-0.5 pt-1'>
                      <span className='block text-[11px] font-bold text-foreground'>Lặp lại</span>
                    </DropdownMenuLabel>
                    <DropdownMenuItem className='gap-2 text-xs' onClick={() => steps.addFlow('repeat')}>
                      <StepIcon type='repeat' size={13} /> Lặp N lần
                    </DropdownMenuItem>
                    <DropdownMenuItem className='gap-2 text-xs' onClick={() => steps.addFlow('repeat_until')}>
                      <StepIcon type='repeat_until' size={13} /> Lặp cho đến khi
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>

                <div className='ml-auto flex items-center gap-1.5'>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <Button size='sm' variant='ghost' className='h-7 w-7 p-0' onClick={() => setJsonDialogOpen(true)} disabled={steps.items.length === 0}>
                        <Code2 className='size-3.5' />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-xs'>Xem JSON</TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <Button size='sm' variant='ghost' className='h-7 w-7 p-0' onClick={steps.copyJson} disabled={steps.items.length === 0}>
                        <Copy className='size-3.5' />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side='top' className='text-xs'>Copy JSON</TooltipContent>
                  </Tooltip>
                  <Button
                    size='sm'
                    variant='default'
                    className='h-7 gap-1.5 px-3 text-xs'
                    onClick={steps.openSave}
                    disabled={steps.items.length === 0}
                  >
                    <Save className='size-3' />
                    Lưu kịch bản
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>}

      {/* ── Install APK dialog ──────────────────────────────────────────────── */}
      <Dialog open={installDialogOpen} onOpenChange={setInstallDialogOpen}>
        <DialogContent className='max-w-md'>
          <DialogHeader>
            <DialogTitle className='flex items-center gap-2 text-base'>
              <PackagePlus className='size-4' />
              Cài APK từ URL
            </DialogTitle>
          </DialogHeader>
          <p className='text-[12px] text-muted-foreground -mt-1'>
            Nhập URL APK công khai. atx-agent trên thiết bị sẽ tải và cài đặt tự động.
          </p>
          <div className='flex gap-2'>
            <Input
              placeholder='https://example.com/app.apk'
              value={installUrl}
              onChange={(e) => setInstallUrl(e.target.value)}
              className='h-8 text-xs font-mono'
            />
            <Button
              size='sm'
              className='h-8 shrink-0'
              disabled={!installUrl.trim() || !selectedDevice}
              onClick={() => {
                if (!selectedDevice || !installUrl.trim()) return;
                record.wsSend({ type: 'install', serial: selectedDevice.serial, url: installUrl.trim() });
                toast.info(`Đang cài APK lên ${selectedDevice.serial}…`);
                setInstallDialogOpen(false);
                setInstallUrl('');
              }}
            >
              Cài
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Variables dialog ────────────────────────────────────────────────── */}
      <Dialog open={varDialogOpen} onOpenChange={setVarDialogOpen}>
        <DialogContent className='max-w-xl'>
          <DialogHeader>
            <DialogTitle className='flex items-center gap-2 text-base'>
              <SlidersHorizontal className='size-4' />
              Biến kịch bản
            </DialogTitle>
          </DialogHeader>
          <p className='text-[12px] text-muted-foreground -mt-1'>
            Đặt giá trị cho biến như <code className='rounded bg-muted px-1 font-mono'>{'${GROUP_NAME}'}</code>.
            Khi chạy thử bước, giá trị này sẽ thay thế tên biến.
          </p>
          <VariableEditor
            variables={scenarioVariables}
            onChange={setScenarioVariables}
          />
        </DialogContent>
      </Dialog>

      {/* ── JSON viewer dialog ──────────────────────────────────────────────── */}
      <Dialog open={jsonDialogOpen} onOpenChange={setJsonDialogOpen}>
        <DialogContent className='max-w-2xl'>
          <DialogHeader>
            <DialogTitle className='flex items-center gap-2 text-base'>
              <Code2 className='size-4' />
              JSON kịch bản
              {steps.items.length > 0 && (
                <span className='rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary'>
                  {steps.items.length} bước
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          <div className='relative'>
            <Button
              size='sm'
              variant='outline'
              className='absolute right-2 top-2 z-10 h-6 gap-1 px-2 text-[10px]'
              onClick={steps.copyJson}
            >
              <Copy className='size-3' /> Copy
            </Button>
            <pre className='max-h-[60vh] overflow-auto rounded-md border border-border bg-muted/40 p-3 text-[11px] font-mono leading-relaxed'>
              {JSON.stringify(
                steps.items.map((s: any) => {
                  const { _id, ...rest } = s;
                  void _id;
                  return rest;
                }),
                null,
                2,
              )}
            </pre>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Save dialog ─────────────────────────────────────────────────────── */}
      <Dialog
        open={save.dialogOpen}
        onOpenChange={(o) => {
          save.setDialogOpen(o);
          if (!o) save.setSelectedCampaignId(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {save.selectedCampaignId
                ? t('chooseScenarioTitle', { name: save.campaigns.find((c) => c.id === save.selectedCampaignId)?.name ?? '' })
                : t('saveScenarioTitle')}
            </DialogTitle>
          </DialogHeader>

          {!save.selectedCampaignId && !save.editingContext ? (
            <div className='space-y-2'>
              <p className='text-xs text-muted-foreground'>{t('stepsRecorded', { count: steps.items.length })}</p>
              {save.campaigns.length === 0 ? (
                <p className='text-sm text-muted-foreground'>{t('noCampaign')}</p>
              ) : (
                save.campaigns.map((c) => (
                  <Button
                    key={c.id}
                    variant='outline'
                    className='w-full justify-start'
                    onClick={() => save.pickCampaign(c.id)}
                    disabled={save.saving !== null}
                  >
                    {c.name}
                  </Button>
                ))
              )}
            </div>
          ) : (
            <div className='space-y-2'>
              {!save.editingContext && (
                <Button
                  variant='ghost'
                  size='sm'
                  className='text-xs text-muted-foreground'
                  onClick={() => save.setSelectedCampaignId(null)}
                >
                  {t('chooseCampaignAgain')}
                </Button>
              )}
              <Button
                variant='default'
                className='w-full justify-start gap-2'
                onClick={() => save.saveAsNew(save.selectedCampaignId!)}
                disabled={save.saving !== null}
              >
                <Plus size={13} />
                {save.saving === 'new' ? t('creating') : t('createNewScenario')}
              </Button>
              {save.campaignScenarios.length > 0 && (
                <>
                  <p className='pt-1 text-xs text-muted-foreground'>{t('overwriteExisting')}</p>
                  {save.campaignScenarios.map((s) => (
                    <Button
                      key={s.id}
                      variant='outline'
                      className='h-auto w-full flex-col items-start justify-start py-2 text-left'
                      onClick={() => save.saveTo(save.selectedCampaignId!, s.id)}
                      disabled={save.saving !== null}
                    >
                      <span className='font-medium'>
                        {save.saving === s.id ? t('saving') : s.name}
                      </span>
                      <span className='text-[11px] font-normal text-muted-foreground'>
                        {t('currentSteps', { count: s.steps.length })}
                      </span>
                    </Button>
                  ))}
                </>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
