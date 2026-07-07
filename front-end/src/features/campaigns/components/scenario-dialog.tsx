'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { toast } from 'sonner';
import { normalizeScenarioVariables } from '@/lib/scenario-variables';
import {
  detectSingleVariableRename,
  replaceScenarioVariableReferences,
  stripUndeclaredVariableReferencesFromTags
} from '@/lib/scenario-variable-references';
import {
  useCampaignDevices,
  useCompileCampaignScenario,
  useScenarios,
  useUpdateCampaignScenario,
  useUpdateScenario,
  useCompileScenario
} from '../hooks/use-campaigns';
import type { CampaignOut, ScenarioOut } from '../types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import {
  FileText,
  Trash2,
  Circle,
  Square,
  RefreshCw,
  Sparkles,
  FolderOpen,
  MousePointerClick,
  Move,
  List,
  GitBranch,
  Loader2
} from 'lucide-react';
import {
  cancelPreviewStream,
  fetchHierarchy,
  interruptDevice,
  previewScenarioStream
} from '@/features/devices/services/api';
import {
  createPreviewRunSession,
  type ActivePreviewTrace
} from '@/features/devices/lib/preview-run-session';
import type { FixedLayoutPluginContext } from '@flowgram.ai/fixed-layout-editor';
import { StepDetailPanel } from './flow-editor/step-detail-panel';
import type { FlowStep } from './scenario-steps/types';
import {
  findStepByFlowgramId,
  mergeStepByFlowgramId,
  patchStepByFlowgramId
} from '@/features/scenario-templates/components/scenario-flow-editor/patch-step-tree';
import { applyStepsToFlowgramDocument } from '@/features/scenario-templates/components/scenario-flow-editor/flow-doc-sync';
import type { FlowgramRunState } from '@/features/scenario-templates/components/scenario-flow-editor/flowgram-scenario-context';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
import { VariableEditor } from '@/components/variable-editor';
import { useTranslations } from 'next-intl';
import { useAccountGroups } from '@/features/account-groups/hooks/use-account-groups';
import { FlowEditor } from './flow-editor/flow-editor';
import { deriveNestedInlineRunStates } from './flow-editor/inline-run-key';
import { sanitizeScenarioStepsForApi } from '@/features/devices/lib/sanitize-scenario-steps-for-api';
import { validateScenarioStepsForApi } from '../utils/validate-scenario-steps-for-api';
import { stepsToGraph } from '../utils/steps-to-graph';
import type { FlowNode, FlowEdge } from './scenario-steps/types';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import {
  findSelectorInXml,
  getScreenSignature
} from '@/features/devices/utils/control-record-xml';
import {
  buildTapSelectorStep,
  normalizeSelectorStepFields
} from '@/features/devices/lib/scenario-selector-step';
import { useConfirm } from '@/providers/modal-provider';

const DynamicFlowgramCanvas = dynamic(
  () =>
    import(
      '@/features/scenario-templates/components/scenario-flow-editor/canvas'
    ).then((m) => m.FlowgramCanvas),
  {
    ssr: false,
    loading: () => (
      <div className='flex min-h-[min(380px,42vh)] items-center justify-center rounded-md border border-border bg-muted/20'>
        <Loader2
          className='size-6 animate-spin text-muted-foreground'
          aria-hidden
        />
      </div>
    )
  }
);

type SelectorBy =
  | 'resource-id'
  | 'text'
  | 'xpath'
  | 'class name'
  | 'description'
  | 'descriptionContains'
  | 'descriptionStartsWith'
  | 'content-desc';

const ALLOWED_SELECTOR_BY: readonly SelectorBy[] = [
  'resource-id',
  'text',
  'xpath',
  'class name',
  'description',
  'descriptionContains',
  'descriptionStartsWith',
  'content-desc'
];

function normalizeSelectorBy(
  by: unknown,
  fallback: SelectorBy = 'text'
): SelectorBy {
  const raw = String(by ?? '').trim();
  if (!raw) return fallback;
  if (ALLOWED_SELECTOR_BY.includes(raw as SelectorBy)) return raw as SelectorBy;

  const lower = raw.toLowerCase().replace(/\s+/g, '');
  if (
    lower === 'content-desc' ||
    lower === 'contentdesc' ||
    lower === 'accessibilityid'
  ) {
    return 'content-desc';
  }
  if (lower === 'description') {
    return 'description';
  }
  if (lower === 'content-desccontains' || lower === 'descriptioncontains') {
    return 'descriptionContains';
  }
  if (lower === 'content-descstartswith' || lower === 'descriptionstartswith') {
    return 'descriptionStartsWith';
  }
  if (lower === 'classname' || lower === 'class-name') {
    return 'class name';
  }
  return fallback;
}

function flattenVarDefs(vars: Record<string, any>): Record<string, any> {
  return normalizeScenarioVariables(vars) as Record<string, any>;
}

type StepType =
  | 'launch_app'
  | 'open_url'
  | 'wait'
  | 'tap_position'
  | 'tap'
  | 'tap_ratio'
  | 'swipe_ratio'
  | 'tap_selector'
  | 'wait_element'
  | 'assert_element'
  | 'input_selector'
  | 'long_tap_selector'
  | 'scroll_to'
  | 'wait_stable'
  | 'dismiss_popup'
  | 'input_text'
  | 'key'
  | 'scroll_down'
  | 'set_variable'
  | 'run_scenario';

type Step =
  | { type: 'launch_app'; package: string }
  | { type: 'open_url'; url: string; package?: string }
  | { type: 'wait'; seconds: number }
  | {
      type: 'tap_position';
      pos:
        | 'top_left'
        | 'top_center'
        | 'top_right'
        | 'middle_left'
        | 'middle_center'
        | 'middle_right'
        | 'bottom_left'
        | 'bottom_center'
        | 'bottom_right'
        | 'search_bar';
    }
  | {
      type: 'tap';
      selector?: { by?: SelectorBy; value?: string };
      fallback?: { rx?: number; ry?: number };
      timeout?: number;
    }
  | { type: 'tap_ratio'; x: number; y: number }
  | {
      type: 'swipe_ratio';
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      duration_ms?: number;
    }
  | {
      type: 'tap_selector';
      by: SelectorBy;
      value: string;
      fallback_rx?: number;
      fallback_ry?: number;
      timeout?: number;
    }
  | { type: 'wait_element'; by: SelectorBy; value: string; timeout?: number }
  | { type: 'assert_element'; by: SelectorBy; value: string; timeout?: number }
  | {
      type: 'input_selector';
      by: SelectorBy;
      value: string;
      text: string;
      clear_first?: boolean;
    }
  | {
      type: 'long_tap_selector';
      by: SelectorBy;
      value: string;
      duration_ms?: number;
    }
  | {
      type: 'scroll_to';
      by: SelectorBy;
      value: string;
      direction?: 'down' | 'up';
      max_swipes?: number;
    }
  | { type: 'wait_stable'; timeout?: number; stable_duration?: number }
  | { type: 'dismiss_popup'; retries?: number }
  | { type: 'input_text'; via: 'u2' | 'a11y_key'; text: string }
  | { type: 'key'; key: string }
  | { type: 'scroll_down'; repeats: number; start_x_ratio?: number | string }
  | {
      type: 'set_variable';
      name: string;
      value?: string;
      from_list?: string[];
      increment?: number;
    }
  | {
      type: 'run_scenario';
      scenario_id?: string;
      scenario_name?: string;
      variables?: Record<string, any>;
    };

type Props = {
  campaign: CampaignOut;
  /** When provided, edits this specific scenario row (new 3-level structure). */
  scenario?: ScenarioOut;
  /** Custom trigger element. If omitted, default button is rendered. */
  children?: React.ReactNode;
};

function coerceSteps(raw: any[]): Step[] {
  return raw.map((s: any): Step => {
    const t: StepType = s?.type;
    switch (t) {
      case 'launch_app':
        return { type: 'launch_app', package: String(s.package || '') };
      case 'open_url':
        return {
          type: 'open_url',
          url: String(s.url || ''),
          package:
            s.package != null && String(s.package).trim()
              ? String(s.package).trim()
              : undefined
        };
      case 'wait':
        return { type: 'wait', seconds: Number(s.seconds || 0) };
      case 'tap_position':
        return {
          type: 'tap_position',
          pos:
            s.pos === 'top_left' ||
            s.pos === 'top_center' ||
            s.pos === 'top_right' ||
            s.pos === 'middle_left' ||
            s.pos === 'middle_center' ||
            s.pos === 'middle_right' ||
            s.pos === 'bottom_left' ||
            s.pos === 'bottom_center' ||
            s.pos === 'bottom_right' ||
            s.pos === 'search_bar'
              ? s.pos
              : 'middle_center'
        };
      case 'tap':
        return {
          type: 'tap',
          ...(s.selector && typeof s.selector === 'object'
            ? {
                selector: {
                  ...(s.selector.by ? { by: s.selector.by } : {}),
                  ...(s.selector.value != null
                    ? { value: String(s.selector.value) }
                    : {})
                }
              }
            : {}),
          ...(s.fallback && typeof s.fallback === 'object'
            ? {
                fallback: {
                  ...(s.fallback.rx != null
                    ? { rx: Number(s.fallback.rx) }
                    : {}),
                  ...(s.fallback.ry != null
                    ? { ry: Number(s.fallback.ry) }
                    : {})
                }
              }
            : {}),
          ...(s.timeout != null ? { timeout: Number(s.timeout) } : {})
        };
      case 'tap_ratio':
        return {
          type: 'tap_ratio',
          x: Number(s.x ?? 0.5),
          y: Number(s.y ?? 0.5)
        };
      case 'swipe_ratio':
        return {
          type: 'swipe_ratio',
          x1: Number(s.x1 ?? 0.5),
          y1: Number(s.y1 ?? 0.5),
          x2: Number(s.x2 ?? 0.5),
          y2: Number(s.y2 ?? 0.5),
          duration_ms: Number(s.duration_ms ?? 300)
        };
      case 'tap_selector': {
        const by = normalizeSelectorBy(s.selector?.by ?? s.by, 'text');
        const value = String(s.selector?.value ?? s.value ?? '');
        return normalizeSelectorStepFields({
          type: 'tap_selector',
          selector: { by, value },
          by,
          value,
          ...(s.fallback && typeof s.fallback === 'object'
            ? { fallback: s.fallback }
            : s.fallback_rx != null && s.fallback_ry != null
              ? {
                  fallback: {
                    rx: Number(s.fallback_rx),
                    ry: Number(s.fallback_ry)
                  },
                  fallback_rx: Number(s.fallback_rx),
                  fallback_ry: Number(s.fallback_ry)
                }
              : {}),
          ...(s.timeout != null ? { timeout: Number(s.timeout) } : {})
        }) as Step;
      }
      case 'wait_element': {
        const by = normalizeSelectorBy(s.selector?.by ?? s.by, 'text');
        const value = String(s.selector?.value ?? s.value ?? '');
        return normalizeSelectorStepFields({
          type: 'wait_element',
          selector: { by, value },
          by,
          value,
          timeout: Number(s.timeout ?? 10),
          ...(s.poll != null ? { poll: Number(s.poll) } : {})
        }) as Step;
      }
      case 'assert_element': {
        const by = normalizeSelectorBy(s.selector?.by ?? s.by, 'text');
        const value = String(s.selector?.value ?? s.value ?? '');
        return normalizeSelectorStepFields({
          type: 'assert_element',
          selector: { by, value },
          by,
          value,
          timeout: Number(s.timeout ?? 5),
          ...(s.poll != null ? { poll: Number(s.poll) } : {})
        }) as Step;
      }
      case 'input_selector': {
        const by = normalizeSelectorBy(s.selector?.by ?? s.by, 'resource-id');
        const value = String(s.selector?.value ?? s.value ?? '');
        return normalizeSelectorStepFields({
          type: 'input_selector',
          selector: { by, value },
          by,
          value,
          text: String(s.text ?? ''),
          clear_first: s.clear_first !== false
        }) as Step;
      }
      case 'long_tap_selector': {
        const by = normalizeSelectorBy(s.selector?.by ?? s.by, 'text');
        const value = String(s.selector?.value ?? s.value ?? '');
        return normalizeSelectorStepFields({
          type: 'long_tap_selector',
          selector: { by, value },
          by,
          value,
          duration_ms: Number(s.duration_ms ?? 800)
        }) as Step;
      }
      case 'scroll_to': {
        const by = normalizeSelectorBy(s.selector?.by ?? s.by, 'text');
        const value = String(s.selector?.value ?? s.value ?? '');
        return normalizeSelectorStepFields({
          type: 'scroll_to',
          selector: { by, value },
          by,
          value,
          direction: s.direction === 'up' ? 'up' : 'down',
          max_swipes: Number(s.max_swipes ?? 5)
        }) as Step;
      }
      case 'wait_stable':
        return {
          type: 'wait_stable',
          ...(s.timeout != null ? { timeout: Number(s.timeout) } : {}),
          ...(s.stable_duration != null
            ? { stable_duration: Number(s.stable_duration) }
            : {})
        };
      case 'dismiss_popup':
        return {
          type: 'dismiss_popup',
          ...(s.retries != null ? { retries: Number(s.retries) } : {})
        };
      case 'input_text':
        return {
          type: 'input_text',
          via: s.via === 'a11y_key' ? 'a11y_key' : 'u2',
          text: String(s.text || '')
        };
      case 'key':
        return { type: 'key', key: String(s.key || '') };
      case 'scroll_down': {
        const repeats = Number(s.repeats || 1);
        const sx = s.start_x_ratio;
        if (sx == null || sx === '') {
          return { type: 'scroll_down', repeats };
        }
        if (typeof sx === 'number' && Number.isFinite(sx)) {
          return { type: 'scroll_down', repeats, start_x_ratio: sx };
        }
        return { type: 'scroll_down', repeats, start_x_ratio: String(sx) };
      }
      case 'set_variable':
        return {
          type: 'set_variable',
          name: String(s.name || ''),
          ...(s.value != null ? { value: String(s.value) } : {}),
          ...(Array.isArray(s.from_list)
            ? { from_list: s.from_list.map(String) }
            : {}),
          ...(s.increment != null ? { increment: Number(s.increment) } : {})
        };
      default:
        // Keep unknown step types visible instead of silently converting to wait(0).
        // This preserves DB data and avoids misleading UI.
        return s as Step;
    }
  });
}

/** Tắt tạm UI Flowgram (toggle + canvas). Đổi thành `true` để bật lại. */
const ENABLE_FLOWGRAM_SCENARIO_UI = false;

export function ScenarioDialog({
  campaign,
  scenario: scenarioProp,
  children
}: Props) {
  /** Prefer explicit prop; else first scenario row (API order) — legacy JSON field removed. */
  const effectiveRow = useMemo(
    () => scenarioProp ?? campaign.scenarios?.[0],
    [scenarioProp, campaign.scenarios]
  );
  const [childStepEditorOpen, setChildStepEditorOpen] = useState(false);
  const [open, setOpen] = useState(false);
  const [instructions, setInstructions] = useState('');
  const [steps, setSteps] = useState<Step[]>([]);
  const [graphNodes, setGraphNodes] = useState<FlowNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<FlowEdge[]>([]);
  const [variables, setVariables] = useState<Record<string, any>>({});
  const variablesRef = useRef<Record<string, any>>({});
  const initialVariablesRef = useRef<Record<string, any>>({});
  const [accountGroupId, setAccountGroupId] = useState<string>('');
  const [rawJson, setRawJson] = useState('');
  const tScenarioForm = useTranslations('components.scenariosForm');
  const tCommon = useTranslations('common');
  const tScenarioValidation = useTranslations(
    'campaignsFeature.scenarioValidation'
  );
  const confirm = useConfirm();
  const { data: accountGroups = [] } = useAccountGroups();
  const [deviceModel, setDeviceModel] = useState('');
  const [androidVersion, setAndroidVersion] = useState('');
  const [browserApp, setBrowserApp] = useState('');
  const [deviceNotes, setDeviceNotes] = useState('');
  // PATCH /campaigns/:id/scenario when no row yet; else scenario row APIs
  const { mutate: saveScenario, isPending: savingLegacy } =
    useUpdateCampaignScenario();
  const { mutate: compileScenario, isPending: compilingLegacy } =
    useCompileCampaignScenario();
  const { mutate: saveScenarioRow, isPending: savingRow } = useUpdateScenario();
  const { mutate: compileScenarioRow, isPending: compilingRow } =
    useCompileScenario();
  const useRowApi = Boolean(effectiveRow?.id);
  const isPending = useRowApi ? savingRow : savingLegacy;
  const compiling = useRowApi ? compilingRow : compilingLegacy;
  const { data: devices = [] } = useCampaignDevices(campaign.id);
  const [previewSerial, setPreviewSerial] = useState('');
  const [xmlSerial, setXmlSerial] = useState('');
  /** Nhiều màn hình: mỗi lần "Thu thập XML" = 1 snapshot từ màn hình hiện tại */
  const [collectedXmls, setCollectedXmls] = useState<
    Array<{ id: string; xml: string }>
  >([]);
  const [previewingAll, setPreviewingAll] = useState(false);
  const [fetchingXml, setFetchingXml] = useState(false);
  const [recording, setRecording] = useState(false);
  const recordingRef = useRef(false);
  /** Thủ công: thêm tap_ratio / swipe_ratio từ mirror (không dùng chế độ Ghi). */
  const [coordPickMode, setCoordPickMode] = useState<null | 'tap' | 'swipe'>(
    null
  );
  const deviceMirrorRef = useRef<HTMLDivElement>(null);
  /** XML cached from device — used for instant tap→selector without backend roundtrip */
  const [recordXml, setRecordXml] = useState<string | null>(null);
  const recordXmlRef = useRef<string | null>(null);
  const [refreshingXml, setRefreshingXml] = useState(false);
  /** flowgram.ai canvas vs dnd list (FlowEditor) */
  const [flowEditMode, setFlowEditMode] = useState(false);
  /** Remount Flowgram when entering flow mode or after external step list changes while in flow mode */
  const [flowCanvasKey, setFlowCanvasKey] = useState(0);
  const [flowSelectedFgId, setFlowSelectedFgId] = useState<string | null>(null);
  const [flowDetailStep, setFlowDetailStep] = useState<FlowStep | null>(null);
  const [flowRunStates, setFlowRunStates] = useState<
    Record<string, FlowgramRunState>
  >({});
  const [stepRunStates, setStepRunStates] = useState<
    Record<string, 'idle' | 'running' | 'ok' | 'error'>
  >({});
  const [flowCoordPick, setFlowCoordPick] = useState<null | {
    fgId: string;
    kind: 'tap' | 'swipe';
  }>(null);
  const flowCtxRef = useRef<FixedLayoutPluginContext | null>(null);
  const stepsRef = useRef<Step[]>([]);
  const flowSelectedFgIdRef = useRef<string | null>(null);
  const flowDetailDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const flowDetailSyncingRef = useRef(false);
  const flowRunAbortRef = useRef<AbortController | null>(null);
  const stepRunAbortRef = useRef<AbortController | null>(null);
  const previewAllAbortRef = useRef<AbortController | null>(null);
  const flowRunningIdsRef = useRef<Set<string>>(new Set());
  // Captured from the server's 'start' SSE event. Lets Stop / dialog-close
  // hit the explicit cancel endpoint instead of relying on the SSE disconnect
  // detector (which can lag ~100ms and waits for a step boundary anyway).
  const activePreviewRef = useRef<ActivePreviewTrace | null>(null);
  const previewRunIdRef = useRef(0);
  const previewSession = useMemo(
    () => createPreviewRunSession(activePreviewRef, previewRunIdRef),
    []
  );

  const hardStopPreview = useCallback(
    (options?: { interruptWithoutActive?: boolean }) => {
      previewAllAbortRef.current?.abort();
      flowRunAbortRef.current?.abort();
      stepRunAbortRef.current?.abort();
      const active = previewSession.takeActiveForCancel();
      const serial = (previewSerial || devices[0]?.serial || '').trim();
      if (active) {
        cancelPreviewStream(active.serial, active.traceId).catch(
          () => undefined
        );
        interruptDevice(active.serial).catch(() => undefined);
      } else if (options?.interruptWithoutActive !== false && serial) {
        interruptDevice(serial).catch(() => undefined);
      }
      setStepRunStates((s) => {
        const hadRunning = Object.values(s).some((st) => st === 'running');
        if (!hadRunning) return s;
        const n = { ...s };
        for (const k of Object.keys(n)) {
          if (n[k] === 'running') delete n[k];
        }
        return n;
      });
      setFlowRunStates((s) => {
        const hadRunning = Object.values(s).some((st) => st === 'running');
        if (!hadRunning) return s;
        const n = { ...s };
        for (const k of Object.keys(n)) {
          if (n[k] === 'running') delete n[k];
        }
        return n;
      });
      flowRunningIdsRef.current.clear();
      queueMicrotask(() => toast.info('Đã dừng chạy thử'));
    },
    [previewSession, previewSerial, devices]
  );

  // Dialog close / tab close / Next.js route change all end up unmounting
  // this component. Make sure the scenario actually stops server-side.
  useEffect(() => {
    const onPageHide = () => hardStopPreview({ interruptWithoutActive: false });
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      hardStopPreview({ interruptWithoutActive: false });
    };
  }, [hardStopPreview]);

  useEffect(() => {
    if (!ENABLE_FLOWGRAM_SCENARIO_UI) setFlowEditMode(false);
  }, []);
  const showFlowEditUi = ENABLE_FLOWGRAM_SCENARIO_UI && flowEditMode;

  useEffect(() => {
    stepsRef.current = steps;
  }, [steps]);
  useEffect(() => {
    variablesRef.current = variables;
  }, [variables]);
  useEffect(() => {
    flowSelectedFgIdRef.current = flowSelectedFgId;
  }, [flowSelectedFgId]);

  useEffect(() => {
    if (!showFlowEditUi) {
      setFlowSelectedFgId(null);
      setFlowDetailStep(null);
      setFlowCoordPick(null);
      setFlowRunStates({});
    }
  }, [showFlowEditUi]);

  useEffect(() => {
    if (!flowSelectedFgId) {
      setFlowDetailStep(null);
      return;
    }
    const found = findStepByFlowgramId(
      stepsRef.current as FlowStep[],
      flowSelectedFgId
    );
    setFlowDetailStep(
      found ? (JSON.parse(JSON.stringify(found)) as FlowStep) : null
    );
  }, [flowSelectedFgId]);

  // Debounced graph sync: stepsToGraph is O(n) — avoid running on every keystroke.
  // Structural changes (add/remove/reorder) call this after updating steps.
  const graphSyncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleGraphSync = useCallback((next: Step[]) => {
    if (graphSyncTimerRef.current) clearTimeout(graphSyncTimerRef.current);
    graphSyncTimerRef.current = setTimeout(() => {
      const { nodes, edges } = stepsToGraph(next as Record<string, unknown>[]);
      setGraphNodes(nodes);
      setGraphEdges(edges);
    }, 300);
  }, []);

  const replaceStepsAndGraph = useCallback(
    (next: Step[]) => {
      setSteps(next);
      scheduleGraphSync(next);
    },
    [scheduleGraphSync]
  );

  const handleVariablesChange = useCallback(
    (next: Record<string, any>) => {
      const normalizedNext = normalizeScenarioVariables(next) as Record<
        string,
        any
      >;
      const rename = detectSingleVariableRename(
        variablesRef.current,
        normalizedNext
      );
      variablesRef.current = normalizedNext;
      setVariables(normalizedNext);
      if (!rename) return;

      const nextSteps = replaceScenarioVariableReferences(
        stepsRef.current,
        rename
      ) as Step[];
      stepsRef.current = nextSteps;
      replaceStepsAndGraph(nextSteps);
      setFlowDetailStep((current) =>
        current ? replaceScenarioVariableReferences(current, rename) : current
      );
    },
    [replaceStepsAndGraph]
  );

  const appendStepsWithGraphSync = useCallback(
    (append: (prev: Step[]) => Step[]) => {
      // Compute next outside updater so we can schedule graph sync without
      // calling setState from inside a setState updater.
      setSteps((prev) => {
        const next = append(prev);
        scheduleGraphSync(next);
        return next;
      });
    },
    [scheduleGraphSync]
  );

  const applyPreviewStepRunEvent = useCallback(
    (
      runKey: string,
      ev: {
        event: string;
        ok?: boolean;
        success?: boolean;
        message?: string;
        error?: string;
        failed_message?: string;
      },
      setStates: React.Dispatch<
        React.SetStateAction<
          Record<string, 'idle' | 'running' | 'ok' | 'error'>
        >
      >
    ) => {
      if (ev.event === 'step_done') {
        setStates((s) => ({
          ...s,
          [runKey]: ev.ok ? 'ok' : 'error',
          ...deriveNestedInlineRunStates(runKey, ev)
        }));
        if (!ev.ok) toast.error(String(ev.message ?? 'Step lỗi'));
        return;
      }
      if (ev.event === 'done') {
        setStates((s) => {
          if (s[runKey] !== 'running') return s;
          const ok = ev.success !== false;
          return { ...s, [runKey]: ok ? 'ok' : 'error' };
        });
        if (ev.success === false) {
          toast.error(
            String(ev.failed_message ?? ev.message ?? 'Kịch bản lỗi')
          );
        }
        return;
      }
      if (ev.event === 'error') {
        setStates((s) => ({ ...s, [runKey]: 'error' }));
        toast.error(String(ev.error ?? 'Lỗi chạy thử'));
      }
    },
    []
  );

  const clearPreviewRunStateAfterDelay = useCallback(
    (
      runKey: string,
      setStates: React.Dispatch<
        React.SetStateAction<
          Record<string, 'idle' | 'running' | 'ok' | 'error'>
        >
      >
    ) => {
      setTimeout(() => {
        setStates((s) => {
          const n = { ...s };
          for (const key of Object.keys(n)) {
            if (
              (key === runKey || key.startsWith(`${runKey}/`)) &&
              n[key] !== 'running'
            ) {
              delete n[key];
            }
          }
          return n;
        });
      }, 2800);
    },
    []
  );

  const handleFlowRunLeaf = useCallback(
    async (fgId: string, step: FlowStep) => {
      const serial = previewSerial?.trim();
      if (!serial) {
        toast.error(
          'Chọn thiết bị trong dropdown "Chọn device để test" (cùng hàng với Test toàn bộ)'
        );
        return;
      }
      if (flowRunningIdsRef.current.has(fgId)) return;
      flowRunningIdsRef.current.add(fgId);
      setFlowRunStates((s) => ({ ...s, [fgId]: 'running' }));
      flowRunAbortRef.current?.abort();
      const ctrl = new AbortController();
      flowRunAbortRef.current = ctrl;
      const runId = previewSession.beginRun();
      const payload = JSON.parse(JSON.stringify(step)) as Record<string, any>;
      delete payload._fgId;
      try {
        await previewScenarioStream(
          serial,
          [payload],
          previewSession.makeStreamHandler(runId, serial, (ev) => {
            applyPreviewStepRunEvent(fgId, ev, setFlowRunStates);
          }),
          ctrl.signal,
          flattenVarDefs(variables)
        );
      } catch (e) {
        if (!ctrl.signal.aborted) {
          setFlowRunStates((s) => ({ ...s, [fgId]: 'error' }));
          toast.error(String(e));
        }
      } finally {
        previewSession.onStreamEnd(runId);
        flowRunningIdsRef.current.delete(fgId);
        if (!ctrl.signal.aborted) {
          setFlowRunStates((s) => {
            if (s[fgId] !== 'running') return s;
            return { ...s, [fgId]: 'error' };
          });
          clearPreviewRunStateAfterDelay(fgId, setFlowRunStates);
        }
      }
    },
    [
      previewSerial,
      variables,
      previewSession,
      applyPreviewStepRunEvent,
      clearPreviewRunStateAfterDelay
    ]
  );

  const handleFlowDetailChange = useCallback(
    (next: FlowStep) => {
      const cloned = JSON.parse(JSON.stringify(next)) as FlowStep;
      setFlowDetailStep(cloned);
      if (flowDetailDebounceRef.current)
        clearTimeout(flowDetailDebounceRef.current);
      flowDetailDebounceRef.current = setTimeout(() => {
        flowDetailDebounceRef.current = null;
        const fgId = flowSelectedFgIdRef.current;
        const ctx = flowCtxRef.current;
        if (!fgId || !ctx) return;
        flowDetailSyncingRef.current = true;
        const patched = patchStepByFlowgramId(
          stepsRef.current as FlowStep[],
          fgId,
          cloned
        );
        try {
          const synced = applyStepsToFlowgramDocument(ctx, patched);
          replaceStepsAndGraph(synced as Step[]);
        } catch (e) {
          toast.error(`Không áp dụng được lên canvas: ${String(e)}`);
        } finally {
          flowDetailSyncingRef.current = false;
        }
      }, 240);
    },
    [replaceStepsAndGraph]
  );

  const flowWorkbench = useMemo(
    () => ({
      deviceSerial: previewSerial || null,
      selectedFgId: flowSelectedFgId,
      setSelectedFgId: setFlowSelectedFgId,
      runStates: flowRunStates,
      onRunLeafStep: handleFlowRunLeaf
    }),
    [previewSerial, flowSelectedFgId, flowRunStates, handleFlowRunLeaf]
  );

  const handleInlineRunStep = useCallback(
    async (step: FlowStep, runKey: string) => {
      const serial = (previewSerial || devices[0]?.serial || '').trim();
      if (!serial) {
        toast.error(
          'Chọn thiết bị trong dropdown "Chọn device để test" (cùng hàng với Test toàn bộ)'
        );
        return;
      }
      if (stepRunStates[runKey] === 'running') return;

      stepRunAbortRef.current?.abort();
      const ctrl = new AbortController();
      stepRunAbortRef.current = ctrl;
      const runId = previewSession.beginRun();

      setStepRunStates((s) => ({ ...s, [runKey]: 'running' }));
      const payload = JSON.parse(JSON.stringify(step)) as Record<
        string,
        unknown
      >;
      delete payload._fgId;

      try {
        await previewScenarioStream(
          serial,
          [payload],
          previewSession.makeStreamHandler(runId, serial, (ev) => {
            applyPreviewStepRunEvent(runKey, ev, setStepRunStates);
          }),
          ctrl.signal,
          flattenVarDefs(variables)
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
          toast.error(String(e));
        }
      } finally {
        previewSession.onStreamEnd(runId);
        if (!ctrl.signal.aborted) {
          setStepRunStates((s) => {
            if (s[runKey] !== 'running') return s;
            return { ...s, [runKey]: 'error' };
          });
          clearPreviewRunStateAfterDelay(runKey, setStepRunStates);
        }
      }
    },
    [
      previewSerial,
      devices,
      stepRunStates,
      variables,
      previewSession,
      applyPreviewStepRunEvent,
      clearPreviewRunStateAfterDelay
    ]
  );

  const handleFetchXml = async () => {
    if (!xmlSerial) return;
    setFetchingXml(true);
    try {
      const xml = await fetchHierarchy(xmlSerial, true);
      const trimmed = xml?.trim();
      if (trimmed) {
        setCollectedXmls((prev) => [
          ...prev,
          { id: `xml-${Date.now()}-${prev.length}`, xml: trimmed }
        ]);
        toast.success(
          `Đã thêm màn hình #${collectedXmls.length + 1} (${trimmed.length.toLocaleString()} ký tự)`
        );
      } else {
        toast.warning('Thiết bị không trả XML');
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : 'Lỗi kết nối';
      toast.error(`Thu thập XML thất bại: ${errMsg}`);
    } finally {
      setFetchingXml(false);
    }
  };

  useEffect(() => {
    recordingRef.current = recording;
  }, [recording]);
  useEffect(() => {
    recordXmlRef.current = recordXml;
  }, [recordXml]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setCoordPickMode(null);
        setFlowCoordPick(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (coordPickMode || flowCoordPick) {
      queueMicrotask(() =>
        deviceMirrorRef.current?.scrollIntoView({
          behavior: 'smooth',
          block: 'nearest'
        })
      );
    }
  }, [coordPickMode, flowCoordPick]);

  const refreshRecordXml = useCallback(async (serial: string) => {
    if (!serial) return;
    setRefreshingXml(true);
    try {
      const xml = await fetchHierarchy(serial, true);
      if (xml?.trim()) {
        setRecordXml(xml.trim());
        return xml.trim();
      } else {
        toast.error(
          'Thiết bị không trả XML — kiểm tra u2/uiautomator2 có đang chạy không'
        );
      }
    } catch {
      toast.error('Lấy XML thất bại');
    } finally {
      setRefreshingXml(false);
    }
    return null;
  }, []);

  /**
   * Called by DeviceControlEmbed on every tap when recording mode is active.
   * Fires hit_test → gets best selector (resource-id / text / content-desc) →
   * appends tap_selector step to the scenario automatically.
   */
  const handleRecordTap = useCallback(
    (serial: string, rx: number, ry: number) => {
      if (!recordingRef.current) return;
      const xml = recordXmlRef.current;
      const rx3 = parseFloat(rx.toFixed(3));
      const ry3 = parseFloat(ry.toFixed(3));

      if (xml) {
        const sig = getScreenSignature(xml);
        const sel = findSelectorInXml(xml, rx, ry, {
          targetPackage: sig.package || undefined
        });
        if (sel) {
          appendStepsWithGraphSync((prev) => [
            ...prev,
            buildTapSelectorStep({
              by: sel.by,
              value: sel.value,
              selector: sel.selector,
              rx: rx3,
              ry: ry3
            }) as Step
          ]);
          toast.success(`tap_selector by=${sel.by}: "${sel.value}"`, {
            duration: 2000
          });
        } else {
          // XML có nhưng không tìm thấy element có text/id — flat XML (STF u2 limitation)
          appendStepsWithGraphSync((prev) => [
            ...prev,
            { type: 'tap_ratio', x: rx3, y: ry3 }
          ]);
          toast.warning(
            'XML không có UI elements — dùng tap_ratio. Cần bật Accessibility Service trên thiết bị để ghi tap_selector.',
            { duration: 5000 }
          );
        }
        setTimeout(() => {
          if (recordingRef.current) refreshRecordXml(serial);
        }, 1000);
      } else {
        appendStepsWithGraphSync((prev) => [
          ...prev,
          { type: 'tap_ratio', x: rx3, y: ry3 }
        ]);
        toast.info('Thêm tap_ratio — bấm "Ghi kịch bản" để lấy XML trước', {
          duration: 3000
        });
      }
    },
    [refreshRecordXml, appendStepsWithGraphSync]
  );

  const activateCoordPick = useCallback(
    (mode: 'tap' | 'swipe') => {
      if (recording) {
        toast.warning('Tắt Ghi trước khi lấy tọa độ thủ công trên mirror.');
        return;
      }
      setCoordPickMode((prev) => (prev === mode ? null : mode));
    },
    [recording]
  );

  const handleEmbedTapForCoords = useCallback(
    (serial: string, rx: number, ry: number) => {
      const rx3 = parseFloat(rx.toFixed(3));
      const ry3 = parseFloat(ry.toFixed(3));

      if (
        showFlowEditUi &&
        flowCoordPick?.kind === 'tap' &&
        flowCtxRef.current &&
        flowCoordPick.fgId
      ) {
        const ctx = flowCtxRef.current;
        const fgId = flowCoordPick.fgId;
        const merged = mergeStepByFlowgramId(
          stepsRef.current as FlowStep[],
          fgId,
          (prev) => {
            if (prev.type === 'tap_ratio')
              return { ...prev, x: rx3, y: ry3 } as FlowStep;
            if (prev.type === 'tap') {
              const t = prev as FlowStep & {
                fallback?: { rx?: number; ry?: number };
              };
              return {
                ...t,
                fallback: { ...(t.fallback ?? {}), rx: rx3, ry: ry3 }
              } as FlowStep;
            }
            if (prev.type === 'swipe_ratio')
              return { ...prev, x1: rx3, y1: ry3 } as FlowStep;
            return prev;
          }
        );
        const synced = applyStepsToFlowgramDocument(ctx, merged);
        replaceStepsAndGraph(synced as Step[]);
        setFlowCoordPick(null);
        toast.success(`Đã gán tọa độ (${rx3}, ${ry3}) cho node`, {
          duration: 2000
        });
        setTimeout(() => void refreshRecordXml(serial), 800);
        return;
      }

      if (coordPickMode !== 'tap') return;
      appendStepsWithGraphSync((prev) => [
        ...prev,
        { type: 'tap_ratio', x: rx3, y: ry3 }
      ]);
      setCoordPickMode(null);
      toast.success(`Đã thêm tap_ratio (${rx3}, ${ry3})`, { duration: 2000 });
      setTimeout(() => {
        void refreshRecordXml(serial);
      }, 800);
    },
    [
      showFlowEditUi,
      flowCoordPick,
      coordPickMode,
      refreshRecordXml,
      appendStepsWithGraphSync,
      replaceStepsAndGraph
    ]
  );

  const handleEmbedSwipeForCoords = useCallback(
    (
      serial: string,
      rx1: number,
      ry1: number,
      rx2: number,
      ry2: number,
      durationMs: number
    ) => {
      const x1 = parseFloat(rx1.toFixed(3));
      const y1 = parseFloat(ry1.toFixed(3));
      const x2 = parseFloat(rx2.toFixed(3));
      const y2 = parseFloat(ry2.toFixed(3));
      const duration_ms = Math.round(Math.max(100, Math.min(durationMs, 2000)));

      if (
        showFlowEditUi &&
        flowCoordPick?.kind === 'swipe' &&
        flowCtxRef.current &&
        flowCoordPick.fgId
      ) {
        const ctx = flowCtxRef.current;
        const fgId = flowCoordPick.fgId;
        const merged = mergeStepByFlowgramId(
          stepsRef.current as FlowStep[],
          fgId,
          (prev) => {
            if (prev.type === 'swipe_ratio') {
              return { ...prev, x1, y1, x2, y2, duration_ms } as FlowStep;
            }
            return prev;
          }
        );
        const synced = applyStepsToFlowgramDocument(ctx, merged);
        replaceStepsAndGraph(synced as Step[]);
        setFlowCoordPick(null);
        toast.success(
          `Đã gán swipe_ratio cho node: (${x1},${y1})→(${x2},${y2})`,
          { duration: 2500 }
        );
        setTimeout(() => void refreshRecordXml(serial), 800);
        return;
      }

      if (coordPickMode !== 'swipe') return;
      appendStepsWithGraphSync((prev) => [
        ...prev,
        { type: 'swipe_ratio', x1, y1, x2, y2, duration_ms }
      ]);
      setCoordPickMode(null);
      toast.success(`Đã thêm swipe_ratio (${x1},${y1})→(${x2},${y2})`, {
        duration: 2000
      });
      setTimeout(() => {
        void refreshRecordXml(serial);
      }, 800);
    },
    [
      showFlowEditUi,
      flowCoordPick,
      coordPickMode,
      refreshRecordXml,
      appendStepsWithGraphSync,
      replaceStepsAndGraph
    ]
  );

  const handleRecordSwipe = useCallback(
    (
      serial: string,
      rx1: number,
      ry1: number,
      rx2: number,
      ry2: number,
      durationMs: number
    ) => {
      if (!recordingRef.current) return;
      const x1 = parseFloat(rx1.toFixed(3));
      const y1 = parseFloat(ry1.toFixed(3));
      const x2 = parseFloat(rx2.toFixed(3));
      const y2 = parseFloat(ry2.toFixed(3));
      const duration_ms = Math.round(Math.max(100, Math.min(durationMs, 2000)));
      appendStepsWithGraphSync((prev) => [
        ...prev,
        { type: 'swipe_ratio', x1, y1, x2, y2, duration_ms }
      ]);
      toast.success(
        `Đã thêm swipe_ratio (${x1},${y1})→(${x2},${y2}) ${duration_ms}ms`,
        { duration: 2000 }
      );
      setTimeout(() => {
        if (recordingRef.current) void refreshRecordXml(serial);
      }, 1000);
    },
    [refreshRecordXml, appendStepsWithGraphSync]
  );

  const removeCollectedXml = (id: string) => {
    setCollectedXmls((prev) => prev.filter((s) => s.id !== id));
  };
  const clearAllCollectedXmls = () => {
    setCollectedXmls([]);
    toast.info('Đã xóa tất cả XML đã thu');
  };

  // Reset form state only when dialog opens (or source data changes).
  // Intentionally excludes `devices` and `xmlSerial` so that selecting a device
  // in the dropdown does NOT wipe the user's unsaved edits.
  useEffect(() => {
    if (!open) {
      setFlowEditMode(false);
      return;
    }
    let currentInstructions = '';
    let currentSteps: Step[] = [];
    let currentDeviceModel = '';
    let currentAndroidVersion = '';
    let currentBrowserApp = '';
    let currentDeviceNotes = '';

    let currentVariables: Record<string, any> = {};

    if (effectiveRow) {
      currentInstructions = effectiveRow.instructions ?? '';
      currentSteps = Array.isArray(effectiveRow.steps)
        ? coerceSteps(effectiveRow.steps)
        : [];
      currentVariables = normalizeScenarioVariables(
        ((effectiveRow as ScenarioOut).variables ?? {}) as Record<
          string,
          unknown
        >
      ) as Record<string, any>;
      const sc: any = (campaign.scenario as any) ?? {};
      const ctx: any = sc.device_context ?? {};
      currentDeviceModel = ctx.device_model ?? '';
      currentAndroidVersion = ctx.android_version ?? '';
      currentBrowserApp = ctx.browser_app ?? '';
      currentDeviceNotes = ctx.notes ?? '';
      setAccountGroupId((effectiveRow as ScenarioOut).account_group_id ?? '');
    } else {
      currentVariables = normalizeScenarioVariables(
        (campaign.variables ?? {}) as Record<string, unknown>
      ) as Record<string, any>;
      setAccountGroupId('');
    }

    setInstructions(currentInstructions);
    setSteps(currentSteps);
    setVariables(currentVariables);
    variablesRef.current = currentVariables;
    initialVariablesRef.current = currentVariables;
    // Load graph model if available and valid, else derive from steps.
    // Validate that each node has required `id` and `order` fields before trusting
    // the stored data (guards against old records saved before the graph refactor).
    const rawNodes: unknown[] = Array.isArray((effectiveRow as any)?.nodes)
      ? (effectiveRow as any).nodes
      : [];
    const validNodes = rawNodes.filter(
      (n): n is FlowNode =>
        typeof n === 'object' &&
        n !== null &&
        typeof (n as any).id === 'string' &&
        typeof (n as any).order === 'string'
    );
    if (validNodes.length > 0) {
      setGraphNodes(validNodes);
      setGraphEdges(
        Array.isArray((effectiveRow as any)?.edges)
          ? (effectiveRow as any).edges
          : []
      );
    } else if (currentSteps.length > 0) {
      const { nodes, edges } = stepsToGraph(
        currentSteps as Record<string, unknown>[]
      );
      setGraphNodes(nodes);
      setGraphEdges(edges);
    } else {
      setGraphNodes([]);
      setGraphEdges([]);
    }
    setDeviceModel(currentDeviceModel);
    setAndroidVersion(currentAndroidVersion);
    setBrowserApp(currentBrowserApp);
    setDeviceNotes(currentDeviceNotes);
    setRawJson(
      JSON.stringify(
        {
          instructions: currentInstructions,
          steps: currentSteps,
          variables: currentVariables
        },
        null,
        2
      )
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, campaign.scenario, campaign.scenarios, effectiveRow]);

  // Initialize xmlSerial once per dialog open when devices are available.
  // Separate from the form-reset effect so that device selection does not
  // trigger a form reset.
  const xmlSerialInitedRef = useRef(false);
  const previewSerialInitedRef = useRef(false);
  useEffect(() => {
    if (!open) {
      xmlSerialInitedRef.current = false;
      return;
    }
    if (!xmlSerialInitedRef.current && devices.length > 0 && !xmlSerial) {
      xmlSerialInitedRef.current = true;
      setXmlSerial(devices[0].serial);
    }
  }, [open, devices, xmlSerial]);

  useEffect(() => {
    if (!open) {
      previewSerialInitedRef.current = false;
      return;
    }
    if (
      !previewSerialInitedRef.current &&
      devices.length > 0 &&
      !previewSerial
    ) {
      previewSerialInitedRef.current = true;
      setPreviewSerial(devices[0].serial);
    }
  }, [open, devices, previewSerial]);

  // Khi đổi thiết bị thì xóa toàn bộ XML đã thu (mỗi thiết bị một bộ snapshot)
  useEffect(() => {
    setCollectedXmls([]);
  }, [xmlSerial]);

  const resolveVariablesForSave = (): Record<string, any> => {
    return normalizeScenarioVariables(variables) as Record<string, any>;
  };

  const handleSave = () => {
    let variablesToSave: Record<string, any>;
    try {
      variablesToSave = resolveVariablesForSave();
    } catch {
      toast.error(tScenarioForm('saveInvalidJsonVariables'));
      return;
    }
    let sanitizedSteps = sanitizeScenarioStepsForApi(steps);
    const pendingRename = detectSingleVariableRename(
      initialVariablesRef.current,
      variablesToSave
    );
    if (pendingRename) {
      sanitizedSteps = replaceScenarioVariableReferences(
        sanitizedSteps,
        pendingRename
      ) as Step[];
      stepsRef.current = sanitizedSteps;
      replaceStepsAndGraph(sanitizedSteps);
    }
    sanitizedSteps = stripUndeclaredVariableReferencesFromTags(
      sanitizedSteps,
      variablesToSave
    ) as Step[];
    const check = validateScenarioStepsForApi(sanitizedSteps, (key, values) =>
      tScenarioValidation(key, values)
    );
    if (!check.ok) {
      toast.error(check.message);
      return;
    }
    const { nodes: saveNodes, edges: saveEdges } = stepsToGraph(
      sanitizedSteps as Record<string, unknown>[]
    );
    if (useRowApi && effectiveRow?.id) {
      saveScenarioRow(
        {
          campaignId: campaign.id,
          scenarioId: effectiveRow.id,
          data: {
            instructions,
            steps: sanitizedSteps,
            variables: variablesToSave,
            nodes: saveNodes as any,
            edges: saveEdges as any,
            // Empty string clears the binding on the backend.
            account_group_id: accountGroupId ? accountGroupId : ''
          }
        },
        {
          onSuccess: () => {
            toast.success('Lưu kịch bản thành công');
            setOpen(false);
          },
          onError: (err) => {
            toast.error(formatFarmApiError(err, 'Lưu kịch bản thất bại'));
          }
        }
      );
    } else {
      const existing = (campaign.scenario as any) ?? {};
      const deviceContext = {
        device_model: deviceModel,
        android_version: androidVersion,
        browser_app: browserApp,
        notes: deviceNotes
      };
      const next: Record<string, any> = {
        ...existing,
        instructions,
        steps: sanitizedSteps,
        variables: variablesToSave,
        device_context: deviceContext
      };
      saveScenario(
        { id: campaign.id, scenario: next },
        {
          onSuccess: () => {
            toast.success('Lưu kịch bản thành công');
            setOpen(false);
          },
          onError: (err) => {
            toast.error(formatFarmApiError(err, 'Lưu kịch bản thất bại'));
          }
        }
      );
    }
  };

  const handlePreviewAll = async () => {
    const serial = (previewSerial || devices[0]?.serial || '').trim();
    if (!serial) {
      toast.error('Chọn thiết bị để test kịch bản');
      return;
    }
    const sanitizedSteps = sanitizeScenarioStepsForApi(steps);
    if (!sanitizedSteps.length) {
      toast.error('Chưa có bước nào để test');
      return;
    }
    previewAllAbortRef.current?.abort();
    const ctrl = new AbortController();
    previewAllAbortRef.current = ctrl;
    const runId = previewSession.beginRun();
    setPreviewingAll(true);
    const failedSteps: number[] = [];
    try {
      await previewScenarioStream(
        serial,
        sanitizedSteps,
        previewSession.makeStreamHandler(runId, serial, (ev) => {
          if (ev.event === 'step_done' && ev.ok === false) {
            failedSteps.push(Number(ev.index ?? 0) + 1);
          }
        }),
        ctrl.signal,
        flattenVarDefs(variables)
      );
      if (ctrl.signal.aborted) return;
      if (failedSteps.length > 0) {
        toast.error(
          `Một số bước lỗi: ${failedSteps.map((n) => `#${n}`).join(', ')}`
        );
      } else {
        toast.success('Đã chạy thử toàn bộ kịch bản');
      }
    } catch {
      if (!ctrl.signal.aborted) {
        toast.error('Test kịch bản thất bại');
      }
    } finally {
      previewSession.onStreamEnd(runId);
      previewAllAbortRef.current = null;
      setPreviewingAll(false);
    }
  };

  const handleCompile = async () => {
    const text = instructions.trim();
    if (!text) {
      toast.error('Vui lòng nhập mô tả trước');
      return;
    }
    const deviceContext = {
      device_model: deviceModel || undefined,
      android_version: androidVersion || undefined,
      browser_app: browserApp || undefined,
      notes: deviceNotes || undefined
    };
    let uiXml: string | undefined;
    let deviceSerial: string | undefined;
    if (collectedXmls.length > 0) {
      uiXml = collectedXmls
        .map(
          (s, i) => `\n\n--- UI hierarchy (màn hình ${i + 1}) ---\n\n${s.xml}`
        )
        .join('');
      toast.info(`Đang gửi ${collectedXmls.length} màn hình vào prompt AI…`);
    } else if (xmlSerial) {
      deviceSerial = xmlSerial;
      toast.info(
        'Backend sẽ gọi uiautomator2 lấy XML từ thiết bị, đang gọi AI…'
      );
    }
    if (useRowApi && effectiveRow?.id) {
      compileScenarioRow(
        {
          campaignId: campaign.id,
          scenarioId: effectiveRow.id,
          instructions: text,
          uiXml,
          deviceSerial,
          deviceContext
        },
        {
          onSuccess: (data) => {
            setInstructions(data.instructions ?? text);
            const s = Array.isArray(data.steps) ? coerceSteps(data.steps) : [];
            replaceStepsAndGraph(s);
            setFlowCanvasKey((k) => k + 1);
            toast.success('AI đã tạo kịch bản từ mô tả');
          },
          onError: () => {
            toast.error('Gọi AI sinh kịch bản thất bại');
          }
        }
      );
    } else {
      compileScenario(
        {
          id: campaign.id,
          instructions: text,
          uiXml,
          deviceSerial,
          deviceContext
        },
        {
          onSuccess: (data) => {
            const sc: any = data.scenario ?? {};
            setInstructions(sc.instructions ?? text);
            const currentSteps = Array.isArray(sc.steps)
              ? coerceSteps(sc.steps)
              : [];
            replaceStepsAndGraph(currentSteps);
            setFlowCanvasKey((k) => k + 1);
            toast.success('AI đã tạo kịch bản từ mô tả');
          },
          onError: () => {
            toast.error('Gọi AI sinh kịch bản thất bại');
          }
        }
      );
    }
  };

  const handleApplyJson = () => {
    const text = rawJson.trim();
    if (!text) {
      toast.error(tScenarioForm('jsonEmpty'));
      return;
    }
    try {
      const parsed = JSON.parse(text);
      const sc: any =
        parsed.scenario && Array.isArray(parsed.scenario?.steps)
          ? parsed.scenario
          : parsed;

      if (!Array.isArray(sc.steps) || sc.steps.length === 0) {
        toast.error(tScenarioForm('jsonInvalidSteps'));
        return;
      }
      const nextInstructions = String(sc.instructions ?? '');
      const nextSteps = coerceSteps(sc.steps);
      const nextVariables = normalizeScenarioVariables(
        sc.variables && typeof sc.variables === 'object'
          ? (sc.variables as Record<string, unknown>)
          : {}
      ) as Record<string, any>;
      const ctx: any = sc.device_context ?? {};
      setDeviceModel(String(ctx.device_model ?? ''));
      setAndroidVersion(String(ctx.android_version ?? ''));
      setBrowserApp(String(ctx.browser_app ?? ''));
      setDeviceNotes(String(ctx.notes ?? ''));
      setInstructions(nextInstructions);
      replaceStepsAndGraph(nextSteps);
      setFlowCanvasKey((k) => k + 1);
      setVariables(nextVariables);
      // Preserve raw JSON shape (including custom top-level keys) to avoid
      // lossy round-trip when users paste advanced scenario objects.
      const preserved = {
        ...sc,
        instructions: nextInstructions,
        steps: nextSteps,
        variables: nextVariables
      };
      setRawJson(JSON.stringify(preserved, null, 2));
      toast.success(tScenarioForm('jsonApplySuccess'));
    } catch {
      toast.error(tScenarioForm('jsonInvalid'));
    }
  };

  const handleAddStep = () => {
    appendStepsWithGraphSync((prev) => [
      ...prev,
      { type: 'launch_app', package: '' }
    ]);
    if (showFlowEditUi) setFlowCanvasKey((k) => k + 1);
  };

  /** Other scenarios in the campaign — used for the "load from template" picker. */
  const { data: allScenarios = [] } = useScenarios(campaign.id);
  const loadableScenarios = useMemo(
    () =>
      allScenarios.filter(
        (s) =>
          s.id !== effectiveRow?.id &&
          Array.isArray(s.steps) &&
          s.steps.length > 0
      ),
    [allScenarios, effectiveRow?.id]
  );

  /** For run_scenario step picker: other scenarios in this campaign (templates are listed separately in UI). */
  const runScenarioCampaignOptions = useMemo(
    () =>
      allScenarios
        .filter((s) => s.id !== effectiveRow?.id)
        .map((s) => ({
          id: s.id,
          name: s.name,
          steps: Array.isArray(s.steps) ? s.steps : []
        })),
    [allScenarios, effectiveRow?.id]
  );

  const handleLoadFromScenario = (scenarioId: string) => {
    void (async () => {
      const source = allScenarios.find((s) => s.id === scenarioId);
      if (!source) return;
      if (steps.length > 0) {
        const ok = await confirm({
          title: tScenarioForm('loadOverwriteTitle'),
          description: tScenarioForm('loadOverwriteDescription', {
            count: steps.length,
            name: source.name
          }),
          confirmText: tCommon('confirm'),
          cancelText: tCommon('cancel'),
          zIndex: 2000
        });
        if (!ok) return;
      }
      const loaded = Array.isArray(source.steps)
        ? coerceSteps(source.steps)
        : [];
      replaceStepsAndGraph(loaded);
      setFlowCanvasKey((k) => k + 1);
      if (source.instructions) setInstructions(source.instructions);
      toast.success(
        `Đã tải ${(source.steps as any[]).length} bước từ "${source.name}"`
      );
    })();
  };

  /** Luôn có thiết bị xem trước khi campaign có device — tránh cột phải trống khi chọn "Không gửi XML". */
  const embedSerial = xmlSerial || devices[0]?.serial || '';

  return (
    <Dialog open={open} onOpenChange={setOpen} modal={!childStepEditorOpen}>
      <DialogTrigger asChild>
        {children ?? (
          <Button size='sm' variant='outline' className='gap-1 text-[10px]'>
            <FileText size={12} strokeWidth={2} className='opacity-80' />
            Kịch bản
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className='z-[1000] flex max-h-[92vh] min-h-0 max-w-5xl flex-col gap-0 overflow-hidden rounded-lg p-3 sm:max-w-[min(100%-2rem,72rem)] sm:p-4 md:min-h-[48vh] lg:max-w-6xl [&>button.absolute]:right-3 [&>button.absolute]:top-3 [&>button.absolute]:h-7 [&>button.absolute]:w-7 [&>button.absolute_svg]:!size-3.5'>
        <DialogHeader className='shrink-0'>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <DialogTitle className='text-base'>
              {effectiveRow
                ? `Kịch bản: ${effectiveRow.name}`
                : 'Kịch bản campaign'}
            </DialogTitle>
            {loadableScenarios.length > 0 && (
              <div className='flex items-center gap-1.5'>
                <FolderOpen
                  size={12}
                  className='shrink-0 text-muted-foreground'
                />
                <span className='whitespace-nowrap text-[11px] text-muted-foreground'>
                  Tải từ kịch bản:
                </span>
                <Select onValueChange={handleLoadFromScenario}>
                  <SelectTrigger className='h-7 w-[160px] text-[11px]'>
                    <SelectValue placeholder='Chọn kịch bản…' />
                  </SelectTrigger>
                  <SelectContent>
                    {loadableScenarios.map((s) => (
                      <SelectItem
                        key={s.id}
                        value={s.id}
                        className='text-[11px]'
                      >
                        {s.name} ({(s.steps as any[]).length} bước)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </DialogHeader>
        <Separator className='shrink-0' />
        <div className='flex min-h-0 flex-1 flex-col gap-4 overflow-hidden pt-2 lg:flex-row'>
          <div className='order-1 min-h-[12rem] min-w-0 flex-1 space-y-4 overflow-y-auto overflow-x-hidden'>
            <div className='space-y-1'>
              <p className='text-xs font-medium'>Mô tả (ngôn ngữ tự nhiên)</p>
              <p className='text-[11px] text-muted-foreground'>
                Ví dụ: &quot;Vào Google, tìm tin tức công nghệ hôm nay, mở kết
                quả đầu tiên và kéo xuống cuối trang&quot;.
              </p>
              <Textarea
                className='h-24 text-[11px]'
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
              />
              {devices.length > 0 && (
                <p className='text-[11px] text-muted-foreground'>
                  Để AI sinh đúng selector (tap_selector, input_text): chọn
                  thiết bị → <strong>Mở điều khiển</strong> → vào đúng màn hình
                  cần automation (tap, mở app…) → quay lại đây bấm{' '}
                  <strong>Sinh kịch bản bằng AI</strong> (sẽ lấy XML từ màn hình
                  hiện tại).
                </p>
              )}
              <div className='flex flex-wrap items-center justify-between gap-2 pt-1'>
                <div className='flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground'>
                  {devices.length > 0 && (
                    <>
                      <span>Thiết bị để lấy UI XML:</span>
                      <Select
                        value={xmlSerial || '_none'}
                        onValueChange={(v) =>
                          setXmlSerial(v === '_none' ? '' : v)
                        }
                      >
                        <SelectTrigger className='h-6 w-[140px] text-[11px]'>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value='_none' className='text-[11px]'>
                            Không gửi XML
                          </SelectItem>
                          {devices.map((d) => (
                            <SelectItem
                              key={d.id}
                              value={d.serial}
                              className='text-[11px]'
                            >
                              {d.name || d.serial}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {xmlSerial && (
                        <>
                          <Button
                            size='sm'
                            variant='secondary'
                            onClick={handleFetchXml}
                            disabled={fetchingXml}
                          >
                            {fetchingXml ? 'Đang thu thập…' : 'Thu thập XML'}
                          </Button>
                          <span className='text-[10px] text-muted-foreground'>
                            Mỗi lần bấm = 1 màn hình. Điều khiển bên phải,
                            chuyển màn rồi thu thập. Sinh kịch bản sẽ gửi tất cả
                            vào prompt AI.
                          </span>
                          {collectedXmls.length > 0 && (
                            <>
                              <span className='text-[11px] font-medium text-green-600 dark:text-green-400'>
                                Đã thu {collectedXmls.length} màn hình
                              </span>
                              <Button
                                size='sm'
                                variant='ghost'
                                className='h-7 text-[10px]'
                                onClick={clearAllCollectedXmls}
                              >
                                Xóa tất cả
                              </Button>
                            </>
                          )}
                        </>
                      )}
                    </>
                  )}
                </div>
                {collectedXmls.length > 0 && (
                  <div className='mt-1 flex flex-wrap gap-1.5'>
                    {collectedXmls.map((s, i) => (
                      <span
                        key={s.id}
                        className='inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-[11px]'
                      >
                        Màn hình {i + 1} ({(s.xml.length / 1000).toFixed(1)}k)
                        <button
                          type='button'
                          className='rounded p-0.5 text-destructive hover:bg-destructive/10'
                          onClick={() => removeCollectedXml(s.id)}
                          title='Xóa màn hình này'
                        >
                          <Trash2 size={10} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <Button
                  size='sm'
                  variant='default'
                  className='gap-1.5 border-0 bg-[#10a37f] text-white hover:bg-[#0d8f6f]'
                  onClick={handleCompile}
                  disabled={compiling}
                  title='Gửi mô tả + XML lên OpenAI (ChatGPT) để sinh kịch bản'
                >
                  <Sparkles
                    size={12}
                    strokeWidth={2}
                    className='shrink-0 opacity-90'
                  />
                  {compiling ? 'ChatGPT đang sinh…' : 'Sinh bằng ChatGPT'}
                </Button>
              </div>
            </div>

            <div className='space-y-1'>
              <p className='text-xs font-medium'>
                Thông tin thiết bị (tùy chọn)
              </p>
              <p className='text-[11px] text-muted-foreground'>
                Gợi ý cho AI về loại máy sẽ chạy campaign này (không bắt buộc,
                chỉ là hint).
              </p>
              <div className='grid grid-cols-2 gap-2'>
                <div className='space-y-1'>
                  <p className='text-[11px] text-muted-foreground'>
                    Model / dòng máy
                  </p>
                  <Input
                    className='h-7 text-[11px]'
                    value={deviceModel}
                    onChange={(e) => setDeviceModel(e.target.value)}
                    placeholder='Galaxy S23, Pixel 8…'
                  />
                </div>
                <div className='space-y-1'>
                  <p className='text-[11px] text-muted-foreground'>
                    Android version
                  </p>
                  <Input
                    className='h-7 text-[11px]'
                    value={androidVersion}
                    onChange={(e) => setAndroidVersion(e.target.value)}
                    placeholder='Android 13, 14…'
                  />
                </div>
                <div className='space-y-1'>
                  <p className='text-[11px] text-muted-foreground'>
                    Ưu tiên browser / app
                  </p>
                  <Input
                    className='h-7 text-[11px]'
                    value={browserApp}
                    onChange={(e) => setBrowserApp(e.target.value)}
                    placeholder='Chrome, Facebook…'
                  />
                </div>
                <div className='space-y-1'>
                  <p className='text-[11px] text-muted-foreground'>
                    Ghi chú khác
                  </p>
                  <Input
                    className='h-7 text-[11px]'
                    value={deviceNotes}
                    onChange={(e) => setDeviceNotes(e.target.value)}
                    placeholder='màn hình nhỏ, ưu tiên tap bằng text…'
                  />
                </div>
              </div>
            </div>

            <div className='space-y-1'>
              <p className='text-xs font-medium'>
                {tScenarioForm('rawJsonTitle')}
              </p>
              <p className='text-[11px] text-muted-foreground'>
                {tScenarioForm.rich('rawJsonHint', {
                  scenarioWrapper: () => (
                    <code className='rounded bg-muted px-1'>
                      {tScenarioForm('rawJsonScenarioWrapper')}
                    </code>
                  ),
                  flatWrapper: () => (
                    <code className='rounded bg-muted px-1'>
                      {tScenarioForm('rawJsonFlatWrapper')}
                    </code>
                  )
                })}
              </p>
              <Textarea
                className='h-32 font-mono text-[11px]'
                value={rawJson}
                onChange={(e) => setRawJson(e.target.value)}
                placeholder={tScenarioForm('rawJsonPlaceholder')}
              />
              <div className='flex flex-col items-end gap-1 pt-1'>
                <Button size='sm' variant='outline' onClick={handleApplyJson}>
                  {tScenarioForm('jsonApply')}
                </Button>
                <p className='max-w-full text-right text-[10px] text-muted-foreground'>
                  {tScenarioForm('jsonApplyHint', {
                    applyLabel: tScenarioForm('jsonApply')
                  })}
                </p>
              </div>
            </div>

            {/* Account group picker — binds scenario to a pool of accounts for rotation */}
            <div className='space-y-1'>
              <p className='text-xs font-medium'>
                {tScenarioForm('accountGroupLabel')}
              </p>
              <Select
                value={accountGroupId || '_none'}
                onValueChange={(v) => setAccountGroupId(v === '_none' ? '' : v)}
              >
                <SelectTrigger className='h-7 w-full max-w-sm text-[11px]'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='_none' className='text-[11px]'>
                    {tScenarioForm('accountGroupNone')}
                  </SelectItem>
                  {accountGroups.map((g) => (
                    <SelectItem key={g.id} value={g.id} className='text-[11px]'>
                      {g.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {accountGroupId &&
                (() => {
                  const picked = accountGroups.find(
                    (g) => g.id === accountGroupId
                  );
                  if (!picked) return null;
                  return (
                    <p className='text-[10px] text-muted-foreground'>
                      {tScenarioForm('accountGroupCaption', {
                        count: picked.member_count,
                        strategy: picked.rotation_strategy
                      })}
                    </p>
                  );
                })()}
              <p className='text-[10px] text-muted-foreground'>
                {tScenarioForm('accountGroupHint')}
              </p>
            </div>

            {/* DF-001: Variables */}
            <div className='space-y-2'>
              <details
                className='group'
                open={Object.keys(variables).length > 0}
              >
                <summary className='flex cursor-pointer items-center gap-1 text-xs font-medium'>
                  <span>
                    {tScenarioForm('variablesTitle')}
                    {Object.keys(variables).length > 0 ? (
                      <span className='ml-1.5 font-normal text-muted-foreground'>
                        {tScenarioForm('variablesCount', {
                          count: Object.keys(variables).length
                        })}
                      </span>
                    ) : null}
                  </span>
                  <span className='font-normal text-muted-foreground'>
                    {tScenarioForm('variablesRuntimeHint', {
                      syntax: '${VAR}'
                    })}
                  </span>
                </summary>
                <div className='space-y-2 pt-2'>
                  <VariableEditor
                    variables={variables}
                    onChange={handleVariablesChange}
                  />
                  <p className='text-[10px] leading-relaxed text-muted-foreground'>
                    {tScenarioForm('variablesExampleIntro')}{' '}
                    <code className='rounded bg-muted px-1 font-mono'>
                      GROUP_NAME
                    </code>
                    ,{' '}
                    <code className='rounded bg-muted px-1 font-mono'>
                      GROUP_XPATH
                    </code>
                    ,{' '}
                    <code className='rounded bg-muted px-1 font-mono'>
                      MAX_SCROLLS
                    </code>
                    ,{' '}
                    <code className='rounded bg-muted px-1 font-mono'>
                      SCROLL_X_RATIO
                    </code>{' '}
                    {tScenarioForm('variablesExampleScrollHint')}{' '}
                    <code className='rounded bg-muted px-1 font-mono'>
                      SAVE_COLLECTION
                    </code>
                    .
                  </p>
                </div>
              </details>
            </div>

            <div className='space-y-2'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <p className='text-xs font-medium'>Các bước thực thi</p>
                <div className='flex flex-wrap items-center gap-2'>
                  {/* Ẩn khi ENABLE_FLOWGRAM_SCENARIO_UI = false — xem hằng số đầu file scenario-dialog */}
                  {ENABLE_FLOWGRAM_SCENARIO_UI && (
                    <div className='flex items-center rounded-md border border-border p-0.5'>
                      <Button
                        type='button'
                        size='sm'
                        variant={flowEditMode ? 'ghost' : 'secondary'}
                        className='h-6 gap-1 rounded-sm px-2 text-[10px]'
                        onClick={() => setFlowEditMode(false)}
                        title='Chỉnh danh sách có thụt lề (kéo thả)'
                      >
                        <List size={12} />
                        Danh sách
                      </Button>
                      <Button
                        type='button'
                        size='sm'
                        variant={flowEditMode ? 'secondary' : 'ghost'}
                        className='h-6 gap-1 rounded-sm px-2 text-[10px]'
                        onClick={() => {
                          if (!flowEditMode) setFlowCanvasKey((k) => k + 1);
                          setFlowEditMode(true);
                        }}
                        title='Flowgram.ai — sơ đồ tuyến tính + khối lồng'
                      >
                        <GitBranch size={12} />
                        Flow
                      </Button>
                    </div>
                  )}
                  {devices.length > 0 && (
                    <>
                      <Select
                        value={previewSerial || '_none'}
                        onValueChange={(v) =>
                          setPreviewSerial(v === '_none' ? '' : v)
                        }
                      >
                        <SelectTrigger className='h-6 w-[140px] text-[11px]'>
                          <SelectValue placeholder='Chọn device để test' />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value='_none' className='text-[11px]'>
                            Chọn device để test
                          </SelectItem>
                          {devices.map((d) => (
                            <SelectItem
                              key={d.id}
                              value={d.serial}
                              className='text-[11px]'
                            >
                              {d.name || d.serial}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {previewingAll ? (
                        <Button
                          size='sm'
                          variant='destructive'
                          onClick={() => hardStopPreview()}
                        >
                          Dừng
                        </Button>
                      ) : (
                        <Button
                          size='sm'
                          variant='outline'
                          onClick={handlePreviewAll}
                          disabled={
                            !steps.length ||
                            (!previewSerial && devices.length === 0)
                          }
                        >
                          Test toàn bộ
                        </Button>
                      )}
                    </>
                  )}
                  <Button size='sm' variant='outline' onClick={handleAddStep}>
                    Thêm bước
                  </Button>
                </div>
              </div>

              {showFlowEditUi ? (
                <div className='space-y-2'>
                  {flowCoordPick && (
                    <div className='rounded-md border border-sky-400/50 bg-sky-50/90 px-2 py-1.5 text-[10px] text-sky-900 dark:bg-sky-950/30 dark:text-sky-200'>
                      {flowCoordPick.kind === 'tap'
                        ? 'Chạm một điểm trên mirror bên phải để gán tọa độ cho node đang chọn. Esc để hủy.'
                        : 'Vuốt trên mirror để gán swipe_ratio cho node đang chọn. Esc để hủy.'}
                    </div>
                  )}
                  <div className='grid gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(260px,320px)] lg:items-start'>
                    <div className='relative min-h-[min(380px,48vh)] overflow-hidden rounded-md border border-border bg-muted/10'>
                      <DynamicFlowgramCanvas
                        key={`scenario-flow-${flowCanvasKey}`}
                        steps={steps as any[]}
                        workbench={flowWorkbench}
                        onFlowCtx={(ctx) => {
                          flowCtxRef.current = ctx;
                        }}
                        onStepsChange={(newSteps) => {
                          if (flowDetailSyncingRef.current) return;
                          replaceStepsAndGraph(newSteps as Step[]);
                        }}
                      />
                    </div>
                    <div className='max-h-[min(48vh,520px)] min-h-[120px] overflow-y-auto rounded-md border border-border bg-card'>
                      {flowDetailStep ? (
                        <StepDetailPanel
                          step={flowDetailStep}
                          onChange={handleFlowDetailChange}
                          onClose={() => setFlowSelectedFgId(null)}
                          onRequestPickSelector={undefined}
                          onRequestPickTapCoords={
                            flowSelectedFgId
                              ? () => {
                                  setFlowCoordPick({
                                    fgId: flowSelectedFgId,
                                    kind: 'tap'
                                  });
                                  setCoordPickMode(null);
                                  toast.info(
                                    'Chạm mirror để gán tọa độ cho node này'
                                  );
                                }
                              : undefined
                          }
                          onRequestPickSwipeCoords={
                            flowSelectedFgId
                              ? () => {
                                  setFlowCoordPick({
                                    fgId: flowSelectedFgId,
                                    kind: 'swipe'
                                  });
                                  setCoordPickMode(null);
                                  toast.info(
                                    'Vuốt trên mirror để gán swipe_ratio'
                                  );
                                }
                              : undefined
                          }
                        />
                      ) : (
                        <p className='p-3 text-[11px] leading-relaxed text-muted-foreground'>
                          Chọn node trên flow (nút con trỏ trên thẻ) để chỉnh
                          chi tiết. Nút play chạy một bước — cần chọn thiết bị ở
                          dropdown &quot;Chọn device để test&quot;.
                        </p>
                      )}
                    </div>
                  </div>
                  <p className='text-[10px] leading-relaxed text-muted-foreground'>
                    <strong>Luồng nối</strong> do Flowgram (fixed-layout) vẽ tự
                    động theo thứ tự dọc và nhánh (if/loop/random). Kéo thả node
                    để đổi thứ tự. <strong>Không hỗ trợ kéo dây tự do</strong>{' '}
                    giữa hai cổng bất kỳ — cần editor dạng free-graph (vd. React
                    Flow) nếu muốn nối tùy ý.
                  </p>
                </div>
              ) : steps.length === 0 ? (
                <p className='text-[11px] text-muted-foreground'>
                  Chưa có bước nào. Bạn có thể dùng AI để sinh, chế độ Flow (+
                  giữa các node), hoặc Thêm bước.
                </p>
              ) : (
                <div>
                  <FlowEditor
                    steps={steps as any[]}
                    onChange={(newSteps) => {
                      // Text edits in nested step overlay no longer bubble per-keystroke;
                      // only sync steps — graph is rebuilt on save.
                      setSteps(newSteps as Step[]);
                    }}
                    maxHeight='min(380px, 42vh)'
                    compact
                    nestedInDialog
                    onChildStepEditorOpenChange={setChildStepEditorOpen}
                    campaignScenarios={runScenarioCampaignOptions}
                    onRunStep={handleInlineRunStep}
                    stepRunStates={stepRunStates}
                    onStopInlineRun={hardStopPreview}
                  />
                </div>
              )}
            </div>

            <div className='flex justify-end gap-2 pt-2'>
              <Button
                size='sm'
                variant='ghost'
                onClick={() => setOpen(false)}
                disabled={isPending || compiling}
              >
                Đóng
              </Button>
              <Button size='sm' onClick={handleSave} disabled={isPending}>
                {isPending ? 'Đang lưu…' : 'Lưu kịch bản'}
              </Button>
            </div>
          </div>
          {devices.length > 0 && embedSerial && (
            <div
              ref={deviceMirrorRef}
              className='order-2 flex max-h-[min(52vh,520px)] min-h-0 w-full shrink-0 flex-col self-stretch overflow-y-auto border-t border-border pt-3 lg:max-h-full lg:w-[320px] lg:min-w-[320px] lg:border-l lg:border-t-0 lg:pl-3 lg:pt-0'
            >
              {!xmlSerial && (
                <p className='mb-2 rounded-md bg-muted/50 px-2 py-1 text-[10px] text-muted-foreground'>
                  Đang xem{' '}
                  <span className='font-mono text-foreground'>
                    {embedSerial.slice(0, 12)}…
                  </span>
                  . Chọn thiết bị ở &quot;Thiết bị để lấy UI XML&quot; nếu cần
                  XML khác cho AI.
                </p>
              )}
              <div className='mb-2 flex shrink-0 items-center justify-between gap-2'>
                <p className='text-[11px] font-medium text-muted-foreground'>
                  Điều khiển
                </p>
                <Button
                  size='sm'
                  variant={recording ? 'destructive' : 'outline'}
                  className='h-7 gap-1 px-2 text-[10px]'
                  onClick={async () => {
                    const next = !recording;
                    if (next && coordPickMode) setCoordPickMode(null);
                    const serialForRec = xmlSerial || devices[0]?.serial;
                    if (next && serialForRec) {
                      toast.info('Đang lấy XML màn hình hiện tại…');
                      const xml = await refreshRecordXml(serialForRec);
                      if (!xml) return;
                      toast.success('XML sẵn sàng — bắt đầu ghi kịch bản');
                    } else {
                      setRecordXml(null);
                    }
                    setRecording(next);
                  }}
                  title={
                    recording
                      ? 'Dừng ghi kịch bản'
                      : 'Bật ghi: lấy XML → mỗi tap tự thêm tap_selector'
                  }
                >
                  {recording ? (
                    <>
                      <Square size={9} className='fill-current' /> Dừng ghi
                    </>
                  ) : (
                    <>
                      <Circle size={9} className='fill-red-500 text-red-500' />{' '}
                      Ghi
                    </>
                  )}
                </Button>
              </div>
              <div className='mb-2 flex flex-wrap gap-1.5'>
                <Button
                  type='button'
                  size='sm'
                  variant={coordPickMode === 'tap' ? 'default' : 'outline'}
                  className='h-7 gap-1 px-2 text-[10px]'
                  disabled={recording}
                  onClick={() => activateCoordPick('tap')}
                  title='Cuộn tới mirror rồi chạm một điểm để thêm tap_ratio'
                >
                  <MousePointerClick size={12} />
                  Chạm lấy tọa độ
                </Button>
                <Button
                  type='button'
                  size='sm'
                  variant={coordPickMode === 'swipe' ? 'default' : 'outline'}
                  className='h-7 gap-1 px-2 text-[10px]'
                  disabled={recording}
                  onClick={() => activateCoordPick('swipe')}
                  title='Vuốt trên mirror để thêm swipe_ratio'
                >
                  <Move size={12} />
                  Vuốt lấy đoạn
                </Button>
              </div>
              {coordPickMode === 'tap' && (
                <div className='mb-2 rounded-md border border-sky-400/40 bg-sky-50 px-2 py-1.5 text-[10px] text-sky-900 dark:bg-sky-950/30 dark:text-sky-200'>
                  <strong>CHẠM TỌA ĐỘ:</strong> chạm một điểm trên màn hình bên
                  dưới — thêm <code className='text-[9px]'>tap_ratio</code>. Esc
                  để hủy.
                </div>
              )}
              {coordPickMode === 'swipe' && (
                <div className='mb-2 rounded-md border border-sky-400/40 bg-sky-50 px-2 py-1.5 text-[10px] text-sky-900 dark:bg-sky-950/30 dark:text-sky-200'>
                  <strong>Vuốt:</strong> kéo trên màn hình bên dưới — thêm{' '}
                  <code className='text-[9px]'>swipe_ratio</code>. Esc để hủy.
                </div>
              )}
              {recording && (
                <div className='mb-1.5 flex items-center justify-between gap-1 rounded bg-amber-50 px-2 py-1 dark:bg-amber-950/30'>
                  <p className='text-[10px] text-amber-800 dark:text-amber-400'>
                    {recordXml ? (
                      <>
                        Đang ghi — tap →{' '}
                        <code className='text-[9px]'>tap_selector</code>, vuốt →{' '}
                        <code className='text-[9px]'>swipe_ratio</code>. Đổi màn
                        → làm mới XML.
                      </>
                    ) : (
                      <span className='text-destructive'>
                        Chưa có XML — tap → tap_ratio; vuốt vẫn ghi swipe_ratio
                      </span>
                    )}
                  </p>
                  <Button
                    size='sm'
                    variant='ghost'
                    className='h-6 shrink-0 gap-0.5 px-1.5 text-[10px]'
                    disabled={refreshingXml}
                    onClick={() => {
                      const s = xmlSerial || devices[0]?.serial;
                      if (s) void refreshRecordXml(s);
                    }}
                    title='Làm mới XML sau khi đổi màn hình'
                  >
                    <RefreshCw
                      size={10}
                      className={refreshingXml ? 'animate-spin' : ''}
                    />
                    {refreshingXml ? '…' : 'Làm mới'}
                  </Button>
                </div>
              )}
              <DeviceControlEmbed
                initialSerial={embedSerial}
                compact
                hideStepMonitor
                onTap={
                  recording ||
                  coordPickMode === 'tap' ||
                  (showFlowEditUi && flowCoordPick?.kind === 'tap')
                    ? (serial, rx, ry) => {
                        if (
                          coordPickMode === 'tap' ||
                          (showFlowEditUi && flowCoordPick?.kind === 'tap')
                        ) {
                          handleEmbedTapForCoords(serial, rx, ry);
                          return;
                        }
                        handleRecordTap(serial, rx, ry);
                      }
                    : undefined
                }
                onSwipe={
                  recording ||
                  coordPickMode === 'swipe' ||
                  (showFlowEditUi && flowCoordPick?.kind === 'swipe')
                    ? (serial, rx1, ry1, rx2, ry2, ms) => {
                        if (
                          coordPickMode === 'swipe' ||
                          (showFlowEditUi && flowCoordPick?.kind === 'swipe')
                        ) {
                          handleEmbedSwipeForCoords(
                            serial,
                            rx1,
                            ry1,
                            rx2,
                            ry2,
                            ms
                          );
                          return;
                        }
                        handleRecordSwipe(serial, rx1, ry1, rx2, ry2, ms);
                      }
                    : undefined
                }
              />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
