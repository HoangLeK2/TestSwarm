'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { DeviceTile } from './device-tile';
import { SafeModeBanner } from '@/features/core/components/safe-mode-banner';
import { useSafeMode } from '@/features/core/services/use-safe-mode';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
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
  Move,
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
  applyTapPointToSteps,
  applySwipeSegmentToSteps,
  type SelectorPickTarget,
  type CoordinatePickTarget,
} from '@/features/campaigns/components/flow-editor';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { findSelectorInXml } from '../utils/control-record-xml';
import { parseHierarchyTree, findNodeIdAtRatio } from '../utils/hierarchy-tree';
import { previewScenarioStream, cancelPreviewStream } from '../services/api';
import { useTranslations } from 'next-intl';
import type { FixedLayoutPluginContext } from '@flowgram.ai/fixed-layout-editor';
import { StepDetailPanel } from '@/features/campaigns/components/flow-editor/step-detail-panel';
import {
  findStepByFlowgramId,
  mergeSelectorByFlowgramId,
  mergeStepByFlowgramId,
  patchStepByFlowgramId,
} from '@/features/scenario-templates/components/scenario-flow-editor/patch-step-tree';
import { isSelectorPickableStep } from '@/features/campaigns/components/flow-editor/selector-pick';
import { applyStepsToFlowgramDocument } from '@/features/scenario-templates/components/scenario-flow-editor/flow-doc-sync';
import type { FlowgramRunState } from '@/features/scenario-templates/components/scenario-flow-editor/flowgram-scenario-context';

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

const ENABLE_FLOWGRAM_CONTROL_UI = false;  // UI flowgram disabled 

export function ControlRecordView({ initialSerial, initialCampaignId, initialScenarioId }: Props = {}) {
  const t = useTranslations('devicesControlRecord.view');
  const { error, device, record, steps, save, hierarchy, selector } = useControlRecord(initialSerial, initialCampaignId, initialScenarioId);
  const { setSkipTapRecordingWhilePick } = record;
  const { read_only: safeReadOnly, stream_hierarchy: safeHierarchy } = useSafeMode();

  const [highlightBounds, setHighlightBounds] = useState<[number, number, number, number] | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [playerMode, setPlayerMode] = useState(false);
  const [selectorPickTarget, setSelectorPickTarget] = useState<SelectorPickTarget | null>(null);
  const [coordinatePickTarget, setCoordinatePickTarget] = useState<CoordinatePickTarget | null>(null);
  const mirrorColRef = useRef<HTMLDivElement>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [flowMode, setFlowMode] = useState(false);
  useEffect(() => {
    if (!ENABLE_FLOWGRAM_CONTROL_UI) setFlowMode(false);
  }, []);
  const showFlowUi = ENABLE_FLOWGRAM_CONTROL_UI && flowMode;
  // Track steps updated from the flowgram canvas (used for saving in flow mode)
  const flowStepsRef = useRef<typeof steps.items>(steps.items);
  const [flowCanvasKey, setFlowCanvasKey] = useState(0);
  const [flowSelectedFgId, setFlowSelectedFgId] = useState<string | null>(null);
  const [flowDetailStep, setFlowDetailStep] = useState<FlowStep | null>(null);
  const [flowRunStates, setFlowRunStates] = useState<Record<string, FlowgramRunState>>({});
  const [flowCoordPick, setFlowCoordPick] = useState<null | { fgId: string; kind: 'tap' | 'swipe' }>(null);
  /** Flow mode: chọn selector từ mirror cho node đang chọn (giống pick trên danh sách). */
  const [flowSelectorPickFgId, setFlowSelectorPickFgId] = useState<string | null>(null);
  const flowCtxRef = useRef<FixedLayoutPluginContext | null>(null);
  const stepsItemsRef = useRef(steps.items);
  const flowSelectedFgIdRef = useRef<string | null>(null);
  const flowDetailDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flowRunLeafAbortRef = useRef<AbortController | null>(null);
  const flowRunningFgIdsRef = useRef<Set<string>>(new Set());
  const [varDialogOpen, setVarDialogOpen] = useState(false);
  const [installDialogOpen, setInstallDialogOpen] = useState(false);
  const [installUrl, setInstallUrl] = useState('');
  const [jsonDialogOpen, setJsonDialogOpen] = useState(false);

  // Scenario-player running state + stop handle. Used by the Farm back button
  // and device-switch guard to confirm+abort before leaving.
  const router = useRouter();
  const [playerPlaying, setPlayerPlaying] = useState(false);
  const stopPlayerRef = useRef<(() => void) | null>(null);
  const [exitConfirm, setExitConfirm] = useState<null | (() => void)>(null);
  const guardWhilePlaying = useCallback(
    (action: () => void) => {
      if (playerPlaying) {
        setExitConfirm(() => action);
      } else {
        action();
      }
    },
    [playerPlaying],
  );

  // Global guard: while preview is running, intercept ANY <a> click on the
  // page (sidebar, header nav, …) and show the exit confirm. Without this,
  // Next.js client-side navigation skips the local Farm-button guard.
  useEffect(() => {
    if (!playerPlaying) return;
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented) return;
      if (e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      const anchor = target?.closest('a');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (!href || href.startsWith('#') || anchor.target === '_blank') return;
      e.preventDefault();
      e.stopPropagation();
      setExitConfirm(() => () => router.push(href));
    };
    document.addEventListener('click', onClick, true);
    const onBeforeUnload = (ev: BeforeUnloadEvent) => {
      ev.preventDefault();
      ev.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => {
      document.removeEventListener('click', onClick, true);
      window.removeEventListener('beforeunload', onBeforeUnload);
    };
  }, [playerPlaying, router]);

  const setCoordinatePickTargetSafe = useCallback(
    (next: CoordinatePickTarget | null) => {
      if (next != null && record.recording) {
        toast.warning('Tắt chế độ ghi trước khi lấy tọa độ từ mirror.');
        return;
      }
      setCoordinatePickTarget(next);
    },
    [record.recording],
  );

  useEffect(() => {
    if (coordinatePickTarget || flowCoordPick || flowSelectorPickFgId) {
      queueMicrotask(() =>
        mirrorColRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }),
      );
    }
  }, [coordinatePickTarget, flowCoordPick, flowSelectorPickFgId]);

  // Hierarchy changed => stale node bounds/highlight must be cleared.
  useEffect(() => {
    setHighlightBounds(null);
    setSelectedNodeId(null);
  }, [hierarchy.xml]);

  // Inline step runner (step-by-step without entering player mode)
  const [stepRunStates, setStepRunStates] = useState<Record<string, 'idle' | 'running' | 'ok' | 'error'>>({});
  const stepRunAbortRef = useRef<AbortController | null>(null);
  // Track active SSE preview trace so unmount (navigation away) can both
  // abort the fetch AND hit the server's explicit cancel endpoint — the SSE
  // disconnect check on the server can lag a cycle on slow networks, and
  // the user expected the scenario to stop the moment they leave the page.
  const activePreviewRef = useRef<{ serial: string; traceId: string } | null>(null);

  // Hard stop on unmount: abort both in-flight previews and POST the explicit
  // cancel route so the server drops the scenario even if it hasn't yet
  // noticed the TCP close. Also fire on pagehide (tab close / back-forward).
  useEffect(() => {
    const hardStop = () => {
      stepRunAbortRef.current?.abort();
      flowRunLeafAbortRef.current?.abort();
      const active = activePreviewRef.current;
      if (active) {
        // Fire-and-forget — we're unmounting, no point awaiting.
        cancelPreviewStream(active.serial, active.traceId).catch(() => undefined);
        activePreviewRef.current = null;
      }
    };
    const onPageHide = () => hardStop();
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      hardStop();
    };
  }, []);

  const handleStopInlineRun = useCallback(() => {
    // Three-pronged stop so the scenario exits quickly regardless of where
    // the executor is stuck:
    //   1) abort() closes the SSE fetch → server notices disconnect (~100ms)
    //   2) explicit cancel route sets cancel_event immediately (no polling lag)
    //   3) also stop any flow-leaf run that may be active
    stepRunAbortRef.current?.abort();
    flowRunLeafAbortRef.current?.abort();
    const active = activePreviewRef.current;
    if (active) {
      cancelPreviewStream(active.serial, active.traceId).catch(() => undefined);
      activePreviewRef.current = null;
    }
    setStepRunStates((s) => {
      const hadRunning = Object.values(s).some((st) => st === 'running');
      if (!hadRunning) return s;
      const n = { ...s };
      for (const k of Object.keys(n)) {
        if (n[k] === 'running') delete n[k];
      }
      queueMicrotask(() => toast.info('Đã dừng chạy thử'));
      return n;
    });
  }, []);

  // Variables for step execution (synced from loaded scenario, editable inline)
  const [scenarioVariables, setScenarioVariables] = useState<Record<string, any>>(
    () => flattenVarDefs(save.editingContext?.variables ?? {})
  );
  useEffect(() => {
    if (save.editingContext?.variables) {
      setScenarioVariables(flattenVarDefs(save.editingContext.variables));
    }
  }, [save.editingContext]);

  useEffect(() => {
    stepsItemsRef.current = steps.items;
  }, [steps.items]);

  useEffect(() => {
    flowSelectedFgIdRef.current = flowSelectedFgId;
  }, [flowSelectedFgId]);

  useEffect(() => {
    if (!showFlowUi) {
      setFlowSelectedFgId(null);
      setFlowDetailStep(null);
      setFlowCoordPick(null);
      setFlowSelectorPickFgId(null);
      setFlowRunStates({});
    }
  }, [showFlowUi]);

  useEffect(() => {
    if (!flowSelectedFgId) {
      setFlowDetailStep(null);
      return;
    }
    const found = findStepByFlowgramId(steps.items as FlowStep[], flowSelectedFgId);
    setFlowDetailStep(found ? (JSON.parse(JSON.stringify(found)) as FlowStep) : null);
  }, [flowSelectedFgId, steps.items]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showFlowUi) {
        setFlowCoordPick(null);
        setFlowSelectorPickFgId(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showFlowUi]);

  const handleFlowRunLeaf = useCallback(
    async (fgId: string, step: FlowStep) => {
      const serial = device.selectedDevice?.serial?.trim();
      if (!serial) {
        toast.warning('Chưa chọn thiết bị');
        return;
      }
      if (flowRunningFgIdsRef.current.has(fgId)) return;
      flowRunningFgIdsRef.current.add(fgId);
      setFlowRunStates((s) => ({ ...s, [fgId]: 'running' }));
      flowRunLeafAbortRef.current?.abort();
      const ctrl = new AbortController();
      flowRunLeafAbortRef.current = ctrl;
      const payload = JSON.parse(JSON.stringify(step)) as Record<string, unknown>;
      delete payload._fgId;
      try {
        await previewScenarioStream(
          serial,
          [payload],
          (ev) => {
            if (ev.event === 'start' && typeof ev.trace_id === 'string') {
              activePreviewRef.current = { serial, traceId: ev.trace_id };
            } else if (ev.event === 'done' || ev.event === 'error') {
              activePreviewRef.current = null;
            }
            if (ev.event === 'step_done') {
              setFlowRunStates((s) => ({ ...s, [fgId]: ev.ok ? 'ok' : 'error' }));
              if (!ev.ok) toast.error(String(ev.message ?? 'Step lỗi'));
            }
          },
          ctrl.signal,
          scenarioVariables,
        );
      } catch (e) {
        if (!ctrl.signal.aborted) {
          setFlowRunStates((s) => ({ ...s, [fgId]: 'error' }));
          toast.error(String(e));
        }
      } finally {
        activePreviewRef.current = null;
        flowRunningFgIdsRef.current.delete(fgId);
        setTimeout(() => {
          setFlowRunStates((s) => {
            const n = { ...s };
            if (n[fgId] !== 'running') delete n[fgId];
            return n;
          });
        }, 2800);
      }
    },
    [device.selectedDevice, scenarioVariables],
  );

  const handleFlowDetailChange = useCallback(
    (next: FlowStep) => {
      setFlowDetailStep(JSON.parse(JSON.stringify(next)) as FlowStep);
      if (flowDetailDebounceRef.current) clearTimeout(flowDetailDebounceRef.current);
      flowDetailDebounceRef.current = setTimeout(() => {
        const fgId = flowSelectedFgIdRef.current;
        const ctx = flowCtxRef.current;
        if (!fgId || !ctx) return;
        const patched = patchStepByFlowgramId(stepsItemsRef.current as FlowStep[], fgId, next);
        try {
          const synced = applyStepsToFlowgramDocument(ctx, patched);
          flowStepsRef.current = synced as typeof steps.items;
          steps.setItems(synced as typeof steps.items);
        } catch (e) {
          toast.error(`Không áp dụng được lên canvas: ${String(e)}`);
        }
      }, 240);
    },
    [steps],
  );

  const flowWorkbench = useMemo(
    () => ({
      deviceSerial: device.selectedDevice?.serial ?? null,
      selectedFgId: flowSelectedFgId,
      setSelectedFgId: setFlowSelectedFgId,
      runStates: flowRunStates,
      onRunLeafStep: handleFlowRunLeaf,
    }),
    [device.selectedDevice, flowSelectedFgId, flowRunStates, handleFlowRunLeaf],
  );

  const handleRunStep = useCallback(
    async (step: FlowStep, runKey: string) => {
      if (!device.selectedDevice) { toast.warning('Chưa chọn thiết bị'); return; }
      if (stepRunStates[runKey] === 'running') return;
      stepRunAbortRef.current?.abort();
      const ctrl = new AbortController();
      stepRunAbortRef.current = ctrl;
      const label = /^\d+$/.test(runKey) ? `Bước ${Number(runKey) + 1}` : 'Bước';
      setStepRunStates((s) => ({ ...s, [runKey]: 'running' }));
      const serial = device.selectedDevice.serial;
      try {
        await previewScenarioStream(
          serial,
          [step as Record<string, any>],
          (event) => {
            if (event.event === 'start' && typeof event.trace_id === 'string') {
              activePreviewRef.current = { serial, traceId: event.trace_id };
            } else if (event.event === 'done' || event.event === 'error') {
              activePreviewRef.current = null;
            }
            if (event.event === 'step_done') {
              setStepRunStates((s) => ({ ...s, [runKey]: event.ok ? 'ok' : 'error' }));
              if (!event.ok) toast.error(`${label}: ${event.message ?? 'Lỗi'}`);
            }
          },
          ctrl.signal,
          scenarioVariables,
        );
      } catch (e) {
        if (ctrl.signal.aborted) {
          setStepRunStates((s) => {
            const n = { ...s };
            delete n[runKey];
            return n;
          });
        } else {
          setStepRunStates((s) => ({ ...s, [runKey]: 'error' }));
          toast.error(`${label}: ${String(e)}`);
        }
      } finally {
        activePreviewRef.current = null;
        if (!ctrl.signal.aborted) {
          setTimeout(() => setStepRunStates((s) => {
            const n = { ...s };
            if (n[runKey] !== 'running') delete n[runKey];
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
    setSkipTapRecordingWhilePick(
      selectorPickTarget != null ||
        coordinatePickTarget != null ||
        flowCoordPick != null ||
        flowSelectorPickFgId != null,
    );
    return () => setSkipTapRecordingWhilePick(false);
  }, [
    selectorPickTarget,
    coordinatePickTarget,
    flowCoordPick,
    flowSelectorPickFgId,
    setSkipTapRecordingWhilePick,
  ]);

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

  const handleScreenSwipe = useCallback(
    (rx1: number, ry1: number, rx2: number, ry2: number, durationMs: number) => {
      const x1 = parseFloat(rx1.toFixed(3));
      const y1 = parseFloat(ry1.toFixed(3));
      const x2 = parseFloat(rx2.toFixed(3));
      const y2 = parseFloat(ry2.toFixed(3));
      const duration_ms = Math.round(Math.max(100, Math.min(durationMs, 2000)));

      if (showFlowUi && flowCoordPick?.kind === 'swipe' && flowCtxRef.current && flowCoordPick.fgId) {
        const ctx = flowCtxRef.current;
        const fgId = flowCoordPick.fgId;
        const merged = mergeStepByFlowgramId(steps.items as FlowStep[], fgId, (prev) => {
          if (prev.type === 'swipe_ratio') {
            return { ...prev, x1, y1, x2, y2, duration_ms } as FlowStep;
          }
          return prev;
        });
        try {
          const synced = applyStepsToFlowgramDocument(ctx, merged);
          flowStepsRef.current = synced as typeof steps.items;
          steps.setItems(synced as typeof steps.items);
        } catch (e) {
          toast.error(`Canvas: ${String(e)}`);
        }
        setFlowCoordPick(null);
        toast.success('Đã gán swipe_ratio cho node', { duration: 2000 });
        return;
      }

      if (coordinatePickTarget?.mode !== 'swipe_segment') return;
      const raw = steps.items as FlowStep[];
      const next = applySwipeSegmentToSteps(raw, coordinatePickTarget, rx1, ry1, rx2, ry2, durationMs);
      if (next === raw) {
        toast.warning('Bước đích phải là swipe_ratio.');
      } else {
        steps.setItems(
          next.map((s: FlowStep, i: number) => ({
            ...s,
            _id: (s as { _id?: string })._id || `step-${Date.now()}-${i}`,
          })) as any,
        );
        setCoordinatePickTarget(null);
        toast.success('Đã cập nhật đoạn vuốt');
      }
    },
    [coordinatePickTarget, showFlowUi, flowCoordPick, steps, device.selectedDevice, hierarchy],
  );

  // When user taps the phone screen → hierarchy highlight + optional selector pick
  const handleScreenTap = useCallback(
    (rx: number, ry: number) => {
      const tree = parseHierarchyTree(hierarchy.xml);
      if (tree) {
        const nodeId = findNodeIdAtRatio(tree, rx, ry);
        setSelectedNodeId(nodeId);
      }

      const rx3 = parseFloat(rx.toFixed(3));
      const ry3 = parseFloat(ry.toFixed(3));

      if (showFlowUi && flowCoordPick?.kind === 'tap' && flowCtxRef.current && flowCoordPick.fgId) {
        const ctx = flowCtxRef.current;
        const fgId = flowCoordPick.fgId;
        const merged = mergeStepByFlowgramId(steps.items as FlowStep[], fgId, (prev) => {
          if (prev.type === 'tap_ratio') return { ...prev, x: rx3, y: ry3 } as FlowStep;
          if (prev.type === 'tap') {
            const t = prev as FlowStep & { fallback?: { rx?: number; ry?: number } };
            return {
              ...t,
              fallback: { ...(t.fallback ?? {}), rx: rx3, ry: ry3 },
            } as FlowStep;
          }
          if (prev.type === 'swipe_ratio') return { ...prev, x1: rx3, y1: ry3 } as FlowStep;
          return prev;
        });
        try {
          const synced = applyStepsToFlowgramDocument(ctx, merged);
          flowStepsRef.current = synced as typeof steps.items;
          steps.setItems(synced as typeof steps.items);
        } catch (e) {
          toast.error(`Canvas: ${String(e)}`);
        }
        setFlowCoordPick(null);
        toast.success(`Đã gán tọa độ (${rx3}, ${ry3}) cho node`, { duration: 2000 });
        return;
      }

      if (showFlowUi && flowSelectorPickFgId && flowCtxRef.current) {
        const sel = findSelectorInXml(hierarchy.xml, rx, ry);
        if (!sel?.value?.trim()) {
          toast.warning(t('pickSelectorNoElement'));
          return;
        }
        const ctx = flowCtxRef.current;
        const fgId = flowSelectorPickFgId;
        const before = findStepByFlowgramId(steps.items as FlowStep[], fgId);
        if (!before || !isSelectorPickableStep(before)) {
          toast.warning('Bước này không dùng selector từ màn hình.');
          setFlowSelectorPickFgId(null);
          return;
        }
        const merged = mergeSelectorByFlowgramId(steps.items as FlowStep[], fgId, sel.by, sel.value.trim());
        try {
          const synced = applyStepsToFlowgramDocument(ctx, merged);
          flowStepsRef.current = synced as typeof steps.items;
          steps.setItems(synced as typeof steps.items);
        } catch (e) {
          toast.error(`Canvas: ${String(e)}`);
          return;
        }
        setFlowSelectorPickFgId(null);
        selector.setBy(sel.by as typeof selector.by);
        selector.setValue(sel.value.trim());
        toast.success(t('pickSelectorApplied', { by: sel.by, value: sel.value.trim().slice(0, 48) }));
        return;
      }

      if (coordinatePickTarget?.mode === 'tap_point') {
        const raw = steps.items as FlowStep[];
        const next = applyTapPointToSteps(raw, coordinatePickTarget, rx, ry);
        if (next === raw) {
          toast.warning('Bước đích phải là tap_ratio hoặc tap (tọa độ dự phòng).');
        } else {
          steps.setItems(
            next.map((s: FlowStep, i: number) => ({
              ...s,
              _id: (s as { _id?: string })._id || `step-${Date.now()}-${i}`,
            })) as any,
          );
          setCoordinatePickTarget(null);
          toast.success('Đã cập nhật tọa độ chạm');
        }
        return;
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
    [
      hierarchy,
      selectorPickTarget,
      coordinatePickTarget,
      applySelectorPick,
      steps,
      t,
      showFlowUi,
      flowCoordPick,
      flowSelectorPickFgId,
      device.selectedDevice,
      selector,
    ],
  );

  // ── Error / empty states ─────────────────────────────────────────────────
  if (error) {
    return (
      <div className='rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive'>
        {error}
      </div>
    );
  }

  // When NOT editing and no device → keep original empty placeholder.
  // When editing (campaignId+scenarioId in URL) → render the 3-column layout
  // anyway so user sees XML / mirror / scenario columns. Phone column shows
  // the existing "Chọn thiết bị từ thanh trên" placeholder when selectedDevice
  // is null.
  if (device.connectedDevices.length === 0 && !save.editingContext) {
    return (
      <div className='flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-20 text-center'>
        <Video className='mb-3 size-10 text-muted-foreground/40' />
        <p className='mb-1 text-base font-medium'>{t('noDeviceConnected')}</p>
        <p className='mb-4 text-sm text-muted-foreground'>{t('noDeviceConnectMessage')}</p>
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

      <SafeModeBanner className='mx-3 mt-2' />

      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div className='flex shrink-0 items-center gap-3 border-b bg-background px-3 py-2'>
        {/* Back */}
        <Button
          variant='ghost'
          size='sm'
          className='-ml-1 shrink-0 gap-1.5 text-muted-foreground hover:text-foreground'
          onClick={() => guardWhilePlaying(() => router.push(ROUTES.DEVICES.ROOT))}
        >
          <ArrowLeft className='size-3.5' />
          Farm
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
          onValueChange={(v) => guardWhilePlaying(() => device.setSelectedSerial(v || null))}
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

        {/* Flow / List — ẩn khi ENABLE_FLOWGRAM_CONTROL_UI = false (tạm tắt Flowgram) */}
        {ENABLE_FLOWGRAM_CONTROL_UI && (
          <Button
            size='sm'
            variant={flowMode ? 'default' : 'outline'}
            className='h-8 gap-1.5 shrink-0 text-xs'
            onClick={() => {
              if (!flowMode) {
                flowStepsRef.current = steps.items;
                setFlowCanvasKey((k) => k + 1);
              } else {
                steps.setItems(flowStepsRef.current);
              }
              setFlowMode((v) => !v);
            }}
            title={flowMode ? 'Chuyển về danh sách bước' : 'Chuyển sang Flow Editor trực quan'}
          >
            {flowMode ? <List className='size-3.5' /> : <GitBranch className='size-3.5' />}
            {flowMode ? 'Danh sách' : 'Flow'}
          </Button>
        )}
      </div>

      {/* ── Main: cây XML + mirror + editor (Danh sách hoặc Flow cùng khung) ── */}
      <div className='flex flex-1 overflow-hidden'>

        {/* ── COL 1: UI Hierarchy tree ──────────────────────────────────── */}
        <div className={cn(
          'flex shrink-0 flex-col border-r border-border/60 bg-muted/10 transition-all duration-200',
          leftCollapsed || !safeHierarchy ? 'w-0 overflow-hidden' : 'w-[320px]',
        )}>
          {/* Tree */}
          <div className='min-h-0 flex-1 overflow-hidden'>
            {!safeHierarchy ? (
              <div className='p-3 text-[11px] text-muted-foreground'>
                Safe mode: không stream cây giao diện.
              </div>
            ) : (
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
            )}
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
                  <Button
                    size='sm'
                    variant='secondary'
                    className='h-5 shrink-0 px-1.5 text-[9px]'
                    onClick={selector.tap}
                    disabled={!selectedDevice || safeReadOnly}
                    title={safeReadOnly ? 'Safe mode: read-only' : undefined}
                  >
                    Tap
                  </Button>
                </div>
                {safeReadOnly ? (
                  <p className='text-[10px] italic text-muted-foreground'>
                    Safe mode: không cho điều khiển / thêm bước.
                  </p>
                ) : (
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
                )}
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

        {/* ── COL 2: Phone screen (centered) ───────────────────────────── */}
        <div
          ref={mirrorColRef}
          className='flex w-[clamp(360px,34vw,520px)] shrink-0 flex-col items-center border-r border-border/60 bg-muted/20 overflow-y-auto'
        >
          {selectedDevice ? (
            <>
              <div className='w-full max-w-[460px] p-3'>
                <DeviceTile
                  device={selectedDevice}
                  logLines={device.logs[selectedDevice.serial] ?? []}
                  mode={device.mode}
                  wsSend={record.sendAndRecord}
                  onToggleMode={record.handleToggleMode}
                  onRestart={record.handleRestart}
                  onTap={handleScreenTap}
                  hideHeader
                  hideStepMonitor
                  onSwipe={
                    coordinatePickTarget?.mode === 'swipe_segment' ||
                    (showFlowUi && flowCoordPick?.kind === 'swipe')
                      ? handleScreenSwipe
                      : undefined
                  }
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
        <div className='flex min-w-0 flex-1 flex-col overflow-hidden'>

          {playerMode && selectedDevice ? (
            /* Player mode — fill column; list scrolls inside ScenarioPlayer */
            <div className='flex min-h-0 flex-1 flex-col overflow-hidden p-4'>
              <ScenarioPlayer
                serial={selectedDevice.serial}
                onClose={() => guardWhilePlaying(() => setPlayerMode(false))}
                onPlayingChange={(p) => { hierarchy.setPaused(p); setPlayerPlaying(p); }}
                registerStop={(fn) => { stopPlayerRef.current = fn; }}
                preloadedSteps={steps.items.length > 0 ? (steps.items as any[]) : undefined}
                preloadedName={save.editingContext?.name}
                preloadedVariables={scenarioVariables}
                deviceBusy={(selectedDevice.state || '').replace('DeviceState.', '') === 'BUSY'}
              />
            </div>
          ) : (
            <>
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

              {coordinatePickTarget?.mode === 'tap_point' && (
                <div className='flex shrink-0 items-center gap-2 border-b border-sky-400/35 bg-sky-50/90 px-4 py-2 dark:bg-sky-950/25'>
                  <MousePointerClick className='size-3.5 shrink-0 text-sky-700 dark:text-sky-400' />
                  <p className='flex-1 text-[11px] text-sky-900 dark:text-sky-200'>
                    CHẠM TỌA ĐỘ — chạm một điểm trên mirror (cột điện thoại). Esc hoặc Huỷ để thoát.
                  </p>
                  <button
                    type='button'
                    className='text-[10px] text-sky-800 underline underline-offset-2 hover:no-underline dark:text-sky-300'
                    onClick={() => setCoordinatePickTarget(null)}
                  >
                    Huỷ
                  </button>
                </div>
              )}

              {coordinatePickTarget?.mode === 'swipe_segment' && (
                <div className='flex shrink-0 items-center gap-2 border-b border-sky-400/35 bg-sky-50/90 px-4 py-2 dark:bg-sky-950/25'>
                  <Move className='size-3.5 shrink-0 text-sky-700 dark:text-sky-400' />
                  <p className='flex-1 text-[11px] text-sky-900 dark:text-sky-200'>
                    Vuốt trên mirror để lấy đoạn (điểm đầu → cuối). Esc hoặc Huỷ để thoát.
                  </p>
                  <button
                    type='button'
                    className='text-[10px] text-sky-800 underline underline-offset-2 hover:no-underline dark:text-sky-300'
                    onClick={() => setCoordinatePickTarget(null)}
                  >
                    Huỷ
                  </button>
                </div>
              )}

              {showFlowUi && flowCoordPick && (
                <div className='flex shrink-0 items-center gap-2 border-b border-sky-400/35 bg-sky-50/90 px-4 py-2 dark:bg-sky-950/25'>
                  <MousePointerClick className='size-3.5 shrink-0 text-sky-700 dark:text-sky-400' />
                  <p className='flex-1 text-[11px] text-sky-900 dark:text-sky-200'>
                    {flowCoordPick.kind === 'tap'
                      ? 'FLOW — chạm mirror để gán tọa độ cho node đang chọn. Esc để hủy.'
                      : 'FLOW — vuốt mirror để gán swipe_ratio. Esc để hủy.'}
                  </p>
                  <button
                    type='button'
                    className='text-[10px] text-sky-800 underline underline-offset-2 hover:no-underline dark:text-sky-300'
                    onClick={() => setFlowCoordPick(null)}
                  >
                    Huỷ
                  </button>
                </div>
              )}

              {showFlowUi && flowSelectorPickFgId && (
                <div className='flex shrink-0 items-center gap-2 border-b border-amber-400/30 bg-amber-50/80 px-4 py-2 dark:bg-amber-950/20'>
                  <Crosshair className='size-3.5 shrink-0 text-amber-600' />
                  <p className='flex-1 text-[11px] text-amber-800 dark:text-amber-300'>
                    FLOW — chạm phần tử trên mirror để gán selector cho node đang chọn (cần XML cây bên trái). Esc để hủy.
                  </p>
                  <button
                    type='button'
                    className='text-[10px] text-amber-700 underline underline-offset-2 hover:no-underline dark:text-amber-400'
                    onClick={() => setFlowSelectorPickFgId(null)}
                  >
                    Huỷ
                  </button>
                </div>
              )}

              {/* Section header */}
              <div className='flex shrink-0 items-center gap-2 overflow-hidden border-b border-border/40 bg-muted/20 px-4 py-1.5'>
                <Clapperboard className='size-3.5 shrink-0 text-muted-foreground' />
                <span className='shrink-0 text-[11px] font-semibold text-foreground'>
                  {showFlowUi ? 'Sơ đồ Flow' : t('editorSectionTitle')}
                </span>
                <div
                  className='flex min-w-0 flex-1 items-center justify-end gap-1.5 overflow-x-auto whitespace-nowrap [scrollbar-width:thin] [&::-webkit-scrollbar]:h-1 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-border'
                >
                <div className='hidden shrink-0 items-center gap-1 sm:flex'>
                  {record.pollingXml && <RefreshCw size={11} className='animate-spin text-red-500/70' />}
                  <Button
                    size='sm'
                    variant={record.recording ? 'destructive' : 'default'}
                    className='h-7 shrink-0 gap-1.5 px-2 text-[10px]'
                    onClick={() => void record.toggleRecording()}
                    disabled={!selectedDevice}
                  >
                    {record.recording ? <Square className='size-3' /> : <Circle className='size-3 fill-current' />}
                    {record.recording ? t('stopRecording') : t('startRecording')}
                  </Button>
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-7 shrink-0 gap-1.5 px-2 text-[10px]'
                    onClick={() => setPlayerMode(true)}
                    disabled={
                      !selectedDevice ||
                      (selectedDevice.state || '').replace('DeviceState.', '') === 'BUSY'
                    }
                    title={
                      selectedDevice &&
                      (selectedDevice.state || '').replace('DeviceState.', '') === 'BUSY'
                        ? 'Thiết bị đang chạy campaign — không cho chạy thử'
                        : undefined
                    }
                  >
                    <Play className='size-3' />
                    {t('tryRun')}
                  </Button>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size='sm' variant='outline' className='h-7 shrink-0 gap-1 px-2 text-[10px]'>
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
                <Tooltip delayDuration={300}>
                  <TooltipTrigger asChild>
                    <Button size='sm' variant='outline' className='h-7 shrink-0 gap-1 px-2 text-[10px]' onClick={() => setInstallDialogOpen(true)} disabled={!selectedDevice}>
                      <PackagePlus className='size-3' />
                      APK
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side='bottom' className='text-xs'>Cài APK từ URL lên thiết bị</TooltipContent>
                </Tooltip>
                <Tooltip delayDuration={300}>
                  <TooltipTrigger asChild>
                    <Button size='sm' variant='ghost' className='h-7 w-7 shrink-0 p-0' onClick={() => setJsonDialogOpen(true)} disabled={steps.items.length === 0}>
                      <Code2 className='size-3.5' />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side='bottom' className='text-xs'>Xem JSON</TooltipContent>
                </Tooltip>
                <Tooltip delayDuration={300}>
                  <TooltipTrigger asChild>
                    <Button size='sm' variant='ghost' className='h-7 w-7 shrink-0 p-0' onClick={steps.copyJson} disabled={steps.items.length === 0}>
                      <Copy className='size-3.5' />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side='bottom' className='text-xs'>Copy JSON</TooltipContent>
                </Tooltip>
                <Button
                  size='sm'
                  variant='default'
                  className='h-7 shrink-0 gap-1 px-2 text-[10px]'
                  onClick={steps.openSave}
                  disabled={steps.items.length === 0 || safeReadOnly}
                  title={safeReadOnly ? 'Safe mode: không cho lưu' : undefined}
                >
                  <Save className='size-3' />
                  Lưu
                </Button>
                {/* Variables editor button */}
                <Tooltip delayDuration={400}>
                  <TooltipTrigger asChild>
                    <button
                      type='button'
                      onClick={() => setVarDialogOpen(true)}
                      className={cn(
                        'flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors',
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
                    <button type='button' className='shrink-0 rounded-full p-0.5 text-muted-foreground hover:bg-muted'>
                      <HelpCircle className='size-3.5' />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side='bottom' className='max-w-xs text-xs'>{t('tooltipScenarioSection')}</TooltipContent>
                </Tooltip>
                </div>
              </div>

              {/* Flow editor */}
              <div className='min-h-0 flex-1 overflow-hidden px-3 pb-2'>
                {steps.items.length === 0 ? (
                  (() => {
                    type Picker = { type: string; label: string; onClick: () => void };
                    const interactions: Picker[] = [
                      { type: 'tap_selector',      label: t('emptyNodePicker.tapSelector'),    onClick: () => steps.addFlow('tap_selector') },
                      { type: 'long_tap_selector', label: t('emptyNodePicker.longTap'),         onClick: () => steps.addFlow('long_tap_selector') },
                      { type: 'input_selector',    label: t('emptyNodePicker.inputText'),       onClick: () => steps.addFlow('input_selector') },
                      { type: 'assert_element',    label: t('emptyNodePicker.assertElement'),   onClick: () => steps.addFlow('assert_element') },
                      { type: 'tap_ratio',         label: t('emptyNodePicker.tapRatio'),        onClick: () => steps.addFlow('tap_ratio') },
                      { type: 'swipe_ratio',       label: t('emptyNodePicker.swipe'),           onClick: () => steps.addFlow('swipe_ratio') },
                      { type: 'key',               label: t('emptyNodePicker.keyPress'),        onClick: () => steps.addFlow('key') },
                      { type: 'set_variable',      label: t('emptyNodePicker.setVariable'),     onClick: () => steps.addFlow('set_variable') },
                    ];
                    const flow: Picker[] = [
                      { type: 'wait',          label: t('emptyNodePicker.waitSeconds'), onClick: steps.addWait },
                      { type: 'wait_element',  label: t('emptyNodePicker.waitElement'), onClick: () => steps.addFlow('wait_element') },
                      { type: 'if_element',    label: t('emptyNodePicker.ifElement'),   onClick: () => steps.addFlow('if_element') },
                      { type: 'if_variable',   label: t('emptyNodePicker.ifVariable'),  onClick: () => steps.addFlow('if_variable') },
                      { type: 'repeat',        label: t('emptyNodePicker.repeatN'),     onClick: () => steps.addFlow('repeat') },
                      { type: 'repeat_until',  label: t('emptyNodePicker.repeatUntil'), onClick: () => steps.addFlow('repeat_until') },
                    ];
                    const sections = [
                      {
                        key: 'interaction',
                        title: t('emptyNodePicker.sectionInteraction'),
                        items: interactions,
                        accent: 'indigo',
                        bar: 'bg-indigo-500',
                        chip: 'bg-indigo-50 text-indigo-700 ring-indigo-200/60',
                        iconWrap: 'bg-indigo-50 text-indigo-600 ring-indigo-100',
                        cardHover: 'hover:border-indigo-300 hover:bg-indigo-50/40 hover:shadow-sm',
                      },
                      {
                        key: 'flow',
                        title: t('emptyNodePicker.sectionFlow'),
                        items: flow,
                        accent: 'amber',
                        bar: 'bg-amber-500',
                        chip: 'bg-amber-50 text-amber-700 ring-amber-200/60',
                        iconWrap: 'bg-amber-50 text-amber-600 ring-amber-100',
                        cardHover: 'hover:border-amber-300 hover:bg-amber-50/40 hover:shadow-sm',
                      },
                    ];
                    return (
                      <div className='flex h-full items-start justify-center overflow-y-auto rounded-xl bg-gradient-to-b from-muted/[0.04] to-transparent px-5 py-8'>
                        <div className='w-full max-w-2xl space-y-6'>
                          <div className='text-center'>
                            <h3 className='text-base font-semibold tracking-tight text-foreground'>
                              {t('emptyNodePicker.title')}
                            </h3>
                            <p className='mx-auto mt-1 max-w-md text-xs leading-relaxed text-muted-foreground'>
                              {t('emptyNodePicker.subtitle')}
                            </p>
                          </div>
                          {sections.map((s) => (
                            <div key={s.key} className='space-y-2.5'>
                              <div className='flex items-center gap-2'>
                                <span className={`h-3.5 w-1 rounded-full ${s.bar}`} aria-hidden />
                                <span className='text-xs font-semibold uppercase tracking-wide text-foreground/80'>
                                  {s.title}
                                </span>
                                <span className={`ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${s.chip}`}>
                                  {s.items.length}
                                </span>
                              </div>
                              <div className='grid grid-cols-2 gap-2 sm:grid-cols-3'>
                                {s.items.map((it) => (
                                  <button
                                    key={it.type}
                                    type='button'
                                    onClick={it.onClick}
                                    className={`group flex h-12 items-center gap-2.5 rounded-lg border border-border/60 bg-background px-2.5 text-left text-xs font-medium text-foreground/90 transition ${s.cardHover}`}
                                  >
                                    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ring-1 ring-inset transition group-hover:scale-105 ${s.iconWrap}`}>
                                      <StepIcon type={it.type as any} size={14} />
                                    </span>
                                    <span className='truncate'>{it.label}</span>
                                  </button>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })()
                ) : showFlowUi ? (
                  <div className='flex h-full max-h-[calc(100vh-280px)] min-h-[280px] flex-col overflow-hidden rounded-lg border border-border/50 bg-background lg:flex-row'>
                    <div className='relative min-h-[220px] flex-1 overflow-hidden lg:min-h-0'>
                      <FlowgramCanvas
                        key={`flow-${flowCanvasKey}`}
                        steps={steps.items as any}
                        workbench={flowWorkbench}
                        onFlowCtx={(ctx) => {
                          flowCtxRef.current = ctx;
                        }}
                        onStepsChange={(newSteps) => {
                          flowStepsRef.current = newSteps as any;
                          steps.setItems(newSteps as any);
                        }}
                      />
                    </div>
                    <div className='max-h-[min(38vh,320px)] w-full shrink-0 overflow-y-auto border-t border-border bg-card lg:max-h-none lg:w-[min(100%,280px)] lg:border-l lg:border-t-0'>
                      {flowDetailStep ? (
                        <StepDetailPanel
                          step={flowDetailStep}
                          onChange={handleFlowDetailChange}
                          onClose={() => setFlowSelectedFgId(null)}
                          onRequestPickSelector={
                            flowSelectedFgId && flowDetailStep && isSelectorPickableStep(flowDetailStep)
                              ? () => {
                                  setFlowSelectorPickFgId(flowSelectedFgId);
                                  setSelectorPickTarget(null);
                                  setFlowCoordPick(null);
                                  setCoordinatePickTarget(null);
                                  toast.info('Chạm phần tử trên mirror để gán selector');
                                }
                              : undefined
                          }
                          onRequestPickTapCoords={
                            flowSelectedFgId
                              ? () => {
                                  setFlowCoordPick({ fgId: flowSelectedFgId, kind: 'tap' });
                                  setCoordinatePickTarget(null);
                                  setFlowSelectorPickFgId(null);
                                  toast.info('Chạm mirror để gán tọa độ cho node này');
                                }
                              : undefined
                          }
                          onRequestPickSwipeCoords={
                            flowSelectedFgId
                              ? () => {
                                  setFlowCoordPick({ fgId: flowSelectedFgId, kind: 'swipe' });
                                  setCoordinatePickTarget(null);
                                  setFlowSelectorPickFgId(null);
                                  toast.info('Vuốt trên mirror để gán swipe_ratio');
                                }
                              : undefined
                          }
                        />
                      ) : (
                        <div className='space-y-2 p-3 text-[11px] leading-relaxed text-muted-foreground'>
                          <p>
                            Bấm <strong>con trỏ</strong> trên node → chỉnh chi tiết; <strong>play</strong> chạy một bước.
                            Cây XML + thêm bước từ selector vẫn dùng cột trái như chế độ danh sách.
                          </p>
                          <p className='rounded-md border border-border/80 bg-muted/30 px-2 py-1.5 text-[10px]'>
                            <strong>Không có “kéo dây” tự do</strong> — Flowgram (fixed-layout) tự vẽ nối theo thứ tự dọc
                            và nhánh if/loop/random. Đổi thứ tự bằng <strong>kéo thả node</strong>. Muốn nối dây tùy ý cần
                            editor dạng graph tự do (vd. React Flow), không nằm trong thư viện hiện tại.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className='flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border/50 bg-background'>
                    {selectedDevice && Object.values(stepRunStates).some((st) => st === 'running') && (
                      <div className='flex shrink-0 justify-end border-b border-border/60 bg-muted/40 px-2 py-1.5'>
                        <Button
                          type='button'
                          size='sm'
                          variant='outline'
                          className='h-7 gap-1 text-xs text-destructive hover:bg-destructive/10'
                          onClick={handleStopInlineRun}
                        >
                          <Square className='size-3' fill='currentColor' />
                          Dừng chạy thử
                        </Button>
                      </div>
                    )}
                    <div className='min-h-0 flex-1 overflow-hidden'>
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
                        maxHeight='calc(100vh - 170px)'
                        selectorPickTarget={selectorPickTarget}
                        onSelectorPickTargetChange={setSelectorPickTarget}
                        coordinatePickTarget={coordinatePickTarget}
                        onCoordinatePickTargetChange={setCoordinatePickTargetSafe}
                        onRunStep={selectedDevice ? handleRunStep : undefined}
                        onStopInlineRun={selectedDevice ? handleStopInlineRun : undefined}
                        stepRunStates={stepRunStates}
                      />
                    </div>
                  </div>
                )}
              </div>

            </>
          )}
        </div>
      </div>

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
        <DialogContent className='max-h-[min(90dvh,920px)] max-w-2xl gap-4 overflow-hidden grid-rows-[auto_minmax(0,1fr)]'>
          <DialogHeader className='shrink-0'>
            <DialogTitle className='flex flex-wrap items-center gap-2 pr-8 text-base'>
              <Code2 className='size-4 shrink-0' />
              JSON kịch bản
              {steps.items.length > 0 && (
                <span className='rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary'>
                  {steps.items.length} bước
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          <div className='relative flex min-h-0 flex-col'>
            <Button
              size='sm'
              variant='outline'
              className='absolute right-1 top-1 z-10 h-6 gap-1 px-2 text-[10px] shadow-sm'
              onClick={steps.copyJson}
            >
              <Copy className='size-3' /> Copy
            </Button>
            <pre className='max-w-full min-h-0 flex-1 overflow-x-auto overflow-y-auto overscroll-y-contain rounded-md border border-border bg-muted/40 p-3 pb-10 pr-14 pt-9 text-[11px] font-mono leading-relaxed'>
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
                onClick={() => save.saveAsNew(save.selectedCampaignId!, scenarioVariables)}
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
                      onClick={() => save.saveTo(save.selectedCampaignId!, s.id, scenarioVariables)}
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

      <AlertDialog
        open={exitConfirm !== null}
        onOpenChange={(o) => { if (!o) setExitConfirm(null); }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('exitConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('exitConfirmDesc')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('exitConfirmCancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const action = exitConfirm;
                setExitConfirm(null);
                stopPlayerRef.current?.();
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
