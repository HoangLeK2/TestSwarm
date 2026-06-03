'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
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
import { ControlRecordMirror } from './control-record/control-record-mirror';
import { MultiDeviceStage } from './control-record/multi-device-stage';
import { MirrorPhonePlaceholder } from './control-record/mirror-phone-placeholder';
import { SafeModeBanner } from '@/features/core/components/safe-mode-banner';
import { useSafeMode } from '@/features/core/services/use-safe-mode';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
  DeviceVarsJsonPanel,
  formatInitialDeviceVars,
  mergeCampaignScenarioVariables,
  parseDeviceVarsJson
} from '@/components/device-vars-json-panel';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
  Circle,
  Square,
  Copy,
  Plus,
  Save,
  ArrowLeft,
  Play,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Video,
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
  List
} from 'lucide-react';
import dynamic from 'next/dynamic';

// Dynamic import để tránh lỗi InversifyJS "Ambiguous FlowRendererRegistry" khi SSR
const FlowgramCanvas = dynamic(
  () =>
    import(
      '@/features/scenario-templates/components/scenario-flow-editor/canvas'
    ).then((m) => m.FlowgramCanvas),
  {
    ssr: false,
    loading: () => (
      <div className='flex flex-1 items-center justify-center text-xs text-muted-foreground'>
        Đang tải canvas…
      </div>
    )
  }
);

const FlowEditor = dynamic(
  () =>
    import('@/features/campaigns/components/flow-editor').then(
      (m) => m.FlowEditor
    ),
  {
    ssr: false,
    loading: () => (
      <div className='flex flex-1 items-center justify-center text-xs text-muted-foreground'>
        Đang tải editor…
      </div>
    )
  }
);

const ScenarioPlayer = dynamic(
  () =>
    import('./control-record/scenario-player').then((m) => m.ScenarioPlayer),
  { ssr: false }
);

const VariableEditor = dynamic(
  () =>
    import('@/components/variable-editor').then((m) => m.VariableEditor),
  { ssr: false }
);
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { useSaveOrgScenarioBody } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { buildOrgScenarioBodyPayload } from '@/features/org-scenarios/lib/build-org-scenario-body';
import { isGraphOrgScenario } from '@/features/org-scenarios/lib/campaign-scenario-eligibility';
import { validateScenarioStepsForApi } from '@/features/campaigns/utils/validate-scenario-steps-for-api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useRouter } from '@/i18n/navigation';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useControlRecord } from '../hooks/use-control-record';
import { campaignVariables, campaignsApi } from '@/features/campaigns/services/api';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import type { ScenarioTemplateOut } from '@/features/scenario-templates/services/api';
import { useAccountGroups } from '@/features/account-groups/hooks/use-account-groups';
import { EmptyNodePicker } from './control-record/empty-node-picker';
import { XmlTreeViewer } from './control-record/xml-tree-viewer';
import {
  applySelectorToSteps,
  applyTapPointToSteps,
  applySwipeSegmentToSteps,
  type SelectorPickTarget,
  type CoordinatePickTarget
} from '@/features/campaigns/components/flow-editor';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import {
  findSelectorForTreeNode,
  findSelectorInXml
} from '../utils/control-record-xml';
import type { ScenarioSelectorShape } from '../lib/scenario-selector-step';
import { buildSelectorStep } from '../lib/scenario-selector-step';
import { parseHierarchyTree, findNodeIdAtRatio } from '../utils/hierarchy-tree';
import {
  previewScenarioStream,
  cancelPreviewStream,
  interruptDevice
} from '../services/api';
import {
  createPreviewRunSession,
  type ActivePreviewTrace
} from '../lib/preview-run-session';
import { devicesApi } from '../services/manage-api';
import { useTranslations } from 'next-intl';
import type { FixedLayoutPluginContext } from '@flowgram.ai/fixed-layout-editor';
import { StepDetailPanel } from '@/features/campaigns/components/flow-editor/step-detail-panel';
import {
  findStepByFlowgramId,
  mergeSelectorByFlowgramId,
  mergeStepByFlowgramId,
  patchStepByFlowgramId
} from '@/features/scenario-templates/components/scenario-flow-editor/patch-step-tree';
import { isSelectorPickableStep } from '@/features/campaigns/components/flow-editor/selector-pick';
import { applyStepsToFlowgramDocument } from '@/features/scenario-templates/components/scenario-flow-editor/flow-doc-sync';
import type { FlowgramRunState } from '@/features/scenario-templates/components/scenario-flow-editor/flowgram-scenario-context';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';

const MAX_MULTI_CONTROL_DEVICES = 20;
const MAX_MULTI_FOLLOWER_DEVICES = MAX_MULTI_CONTROL_DEVICES - 1;

/**
 * Template variables are stored as metadata dicts:
 *   {"GROUP_NAME": {"type": "string", "default": "foo", "description": "..."}}
 * Flatten them to plain values so they can be used at runtime:
 *   {"GROUP_NAME": "foo"}
 */
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

function mergeTemplateVariablesIntoEditor(
  prev: Record<string, any>,
  templateVars: Record<string, any> | undefined
): Record<string, any> {
  if (!templateVars || Object.keys(templateVars).length === 0) return prev;
  return flattenVarDefs({
    ...prev,
    ...flattenVarDefs(templateVars)
  });
}

/** Bounded label for device Select (long model/serial otherwise breaks the top bar). */
function formatDeviceSelectLabel(d: {
  brand: string;
  model: string;
  serial: string;
}) {
  const left = `${d.brand} ${d.model}`.trim().replace(/\s+/g, ' ');
  const s = d.serial;
  const serialShort = s.length > 16 ? `${s.slice(0, 7)}…${s.slice(-6)}` : s;
  if (!left) return serialShort;
  const maxLeft = 26;
  const leftShort =
    left.length > maxLeft ? `${left.slice(0, maxLeft - 1)}…` : left;
  return `${leftShort} — ${serialShort}`;
}

function deviceSelectFullTitle(d: {
  brand: string;
  model: string;
  serial: string;
}) {
  const left = `${d.brand} ${d.model}`.trim();
  return left ? `${left} — ${d.serial}` : d.serial;
}

function isManualControlEligible(d: {
  state?: string | null;
  scenario_active?: number | null;
}) {
  const state = String(d.state || '').replace('DeviceState.', '').toUpperCase();
  return state === 'READY' && (d.scenario_active ?? 0) <= 0;
}

type Props = {
  initialSerial?: string | null;
  initialCampaignId?: string | null;
  initialScenarioId?: string | null;
  initialTemplateId?: string | null;
  initialOrgScenarioId?: string | null;
  /** Optional redirect target after saving (used when launched from org-scenario). */
  returnTo?: string | null;
};

const ENABLE_FLOWGRAM_CONTROL_UI = false; // UI flowgram disabled

export function ControlRecordView({
  initialSerial,
  initialCampaignId,
  initialScenarioId,
  initialTemplateId,
  initialOrgScenarioId,
  returnTo
}: Props = {}) {
  const t = useTranslations('devicesControlRecord.view');
  const tOrg = useTranslations('orgScenariosFeature.detail');
  const tDv = useTranslations('components.deviceVarsJson');
  const tDvDlg = useTranslations('devicesControlRecord.deviceVarsDialog');
  const tModal = useTranslations('components.modal');
  const tVar = useTranslations('components.variableEditor');
  const router = useRouter();
  const { error, device, record, steps, save, hierarchy, selector } =
    useControlRecord(
      initialSerial,
      initialCampaignId,
      initialScenarioId,
      initialTemplateId,
      initialOrgScenarioId
    );
  const hierarchyXml = hierarchy.xml;
  const handleScreenTapRef = useRef<(rx: number, ry: number) => void>(() => {});
  const handleScreenSwipeRef = useRef<
    (
      rx1: number,
      ry1: number,
      rx2: number,
      ry2: number,
      durationMs: number
    ) => void
  >(() => {});
  const { read_only: safeReadOnly, stream_hierarchy: safeHierarchy } =
    useSafeMode();
  const devicePerms = useResourcePermissions('devices');
  const campaignPerms = useResourcePermissions('campaigns');
  const templatePerms = useResourcePermissions('scenario-templates');
  const orgScenarioPerms = useResourcePermissions('scenarios');
  const canExecuteDevice = devicePerms.canExecute && !safeReadOnly;
  const savingOrgScenario = Boolean(initialOrgScenarioId);
  const canSaveWork =
    !safeReadOnly &&
    (save.templateContext
      ? templatePerms.canUpdate
      : savingOrgScenario
        ? orgScenarioPerms.canUpdate
        : campaignPerms.canUpdate);
  const { setSkipTapRecordingWhilePick } = record;

  const saveOrgBodyMutation = useSaveOrgScenarioBody();

  useEffect(() => {
    if (!isGraphOrgScenario(save.orgScenarioContext)) return;
    const back = (returnTo ?? '').trim() || ROUTES.ORG_SCENARIOS.ROOT;
    toast.error(tOrg('sequenceOnlyNoGraph'));
    router.replace(back);
  }, [save.orgScenarioContext?.kind, returnTo, router, tOrg]);

  const handleSaveOrgScenario = async () => {
    const scenarioId = (initialOrgScenarioId ?? '').trim();
    if (!scenarioId) return;
    if (isGraphOrgScenario(save.orgScenarioContext)) {
      toast.error(tOrg('sequenceOnlyNoGraph'));
      return;
    }
    if (steps.items.length === 0) {
      toast.warning(tOrg('saveOrgNoSteps'));
      return;
    }
    const body = buildOrgScenarioBodyPayload(steps.items, scenarioVariables);
    const check = validateScenarioStepsForApi(body.steps ?? []);
    if (!check.ok) {
      toast.error(check.message);
      return;
    }
    saveOrgBodyMutation.mutate(
      {
        scenarioId,
        body
      },
      {
        onSuccess: () => {
          toast.success(tOrg('saveOrgSuccess'));
          const next = (returnTo ?? '').trim();
          if (next) {
            router.push(next);
          } else {
            router.push(ROUTES.ORG_SCENARIOS.ROOT);
          }
        },
        onError: (err) => {
          toast.error(formatFarmApiError(err, tOrg('saveOrgFailed')));
        }
      }
    );
  };

  const [highlightBounds, setHighlightBounds] = useState<
    [number, number, number, number] | null
  >(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [playerMode, setPlayerMode] = useState(false);
  const [selectorPickTarget, setSelectorPickTarget] =
    useState<SelectorPickTarget | null>(null);
  const [coordinatePickTarget, setCoordinatePickTarget] =
    useState<CoordinatePickTarget | null>(null);
  const mirrorColRef = useRef<HTMLDivElement>(null);
  const leftCollapsedBeforeMultiRef = useRef<boolean | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [flowMode, setFlowMode] = useState(false);
  useEffect(() => {
    if (!ENABLE_FLOWGRAM_CONTROL_UI) setFlowMode(false);
  }, []);
  const showFlowUi = ENABLE_FLOWGRAM_CONTROL_UI && flowMode;
  const [multiFollowerSerials, setMultiFollowerSerials] = useState<string[]>(
    []
  );
  const [stepPickerOpen, setStepPickerOpen] = useState(true);
  const multiFollowerOptions = useMemo(
    () =>
      device.connectedDevices.filter(
        (d) =>
          d.serial !== device.selectedDevice?.serial &&
          isManualControlEligible(d)
      ),
    [device.connectedDevices, device.selectedDevice?.serial]
  );
  useEffect(() => {
    const allowed = new Set(multiFollowerOptions.map((d) => d.serial));
    setMultiFollowerSerials((prev) =>
      prev
        .filter((serial) => allowed.has(serial))
        .slice(0, MAX_MULTI_FOLLOWER_DEVICES)
    );
  }, [multiFollowerOptions]);
  const activeMultiSerials = useMemo(() => {
    const primary = device.selectedDevice?.serial;
    if (!primary) return [];
    return [
      primary,
      ...multiFollowerSerials.filter((serial) => serial !== primary)
    ];
  }, [device.selectedDevice?.serial, multiFollowerSerials]);
  const selectedMultiFollowerDevices = useMemo(() => {
    const selected = new Set(multiFollowerSerials);
    return device.connectedDevices.filter((d) => selected.has(d.serial));
  }, [device.connectedDevices, multiFollowerSerials]);
  const hasMultiFollowers = multiFollowerSerials.length > 0;
  const multiFocusMode = hasMultiFollowers && !stepPickerOpen && !playerMode;
  const showEditorPanel =
    !hasMultiFollowers || stepPickerOpen || playerMode;
  const treePanelOpen = safeHierarchy && !leftCollapsed && !hasMultiFollowers;

  const prevMultiRef = useRef(false);

  useEffect(() => {
    if (hasMultiFollowers) {
      if (!prevMultiRef.current) {
        setStepPickerOpen(false);
      }
      setLeftCollapsed((prev) => {
        if (leftCollapsedBeforeMultiRef.current === null) {
          leftCollapsedBeforeMultiRef.current = prev;
        }
        return true;
      });
    } else {
      if (prevMultiRef.current) {
        setStepPickerOpen(true);
      }
      if (leftCollapsedBeforeMultiRef.current !== null) {
        const restore = leftCollapsedBeforeMultiRef.current;
        leftCollapsedBeforeMultiRef.current = null;
        setLeftCollapsed(restore);
      }
    }
    prevMultiRef.current = hasMultiFollowers;
  }, [hasMultiFollowers]);
  const sendAndRecord = record.sendAndRecord;
  const mirrorWsSend = useCallback(
    (obj: object) => {
      sendAndRecord(obj, { multiSerials: activeMultiSerials });
    },
    [sendAndRecord, activeMultiSerials]
  );
  // Track steps updated from the flowgram canvas (used for saving in flow mode)
  const flowStepsRef = useRef<typeof steps.items>(steps.items);
  const [flowCanvasKey, setFlowCanvasKey] = useState(0);
  const [flowSelectedFgId, setFlowSelectedFgId] = useState<string | null>(null);
  const [flowDetailStep, setFlowDetailStep] = useState<FlowStep | null>(null);

  // Template picker: fetched lazily only when the empty-state view is shown
  // (see below — hook is called unconditionally; React-Query is cheap to keep
  // alive). `previewTemplate` holds the template being inspected before load.
  const templatesQuery = useScenarioTemplates();
  const [previewTemplate, setPreviewTemplate] =
    useState<ScenarioTemplateOut | null>(null);

  // Account-group picker for the Save dialog. `'_none'` = do not bind.
  // On open, we hydrate from editingContext so a user returning to edit a
  // scenario sees the already-bound group pre-selected.
  const { data: accountGroups = [] } = useAccountGroups();
  const [saveAccountGroupId, setSaveAccountGroupId] = useState<string>('');
  useEffect(() => {
    if (save.editingContext?.accountGroupId) {
      setSaveAccountGroupId(save.editingContext.accountGroupId);
    } else {
      setSaveAccountGroupId('');
    }
  }, [save.editingContext]);
  const [flowRunStates, setFlowRunStates] = useState<
    Record<string, FlowgramRunState>
  >({});
  const [flowCoordPick, setFlowCoordPick] = useState<null | {
    fgId: string;
    kind: 'tap' | 'swipe';
  }>(null);
  /** Flow mode: chọn selector từ mirror cho node đang chọn (giống pick trên danh sách). */
  const [flowSelectorPickFgId, setFlowSelectorPickFgId] = useState<
    string | null
  >(null);
  const flowCtxRef = useRef<FixedLayoutPluginContext | null>(null);
  const stepsItemsRef = useRef(steps.items);
  const flowSelectedFgIdRef = useRef<string | null>(null);
  const flowDetailDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const flowDetailPendingRef = useRef<FlowStep | null>(null);
  const flowDetailSyncingRef = useRef(false);
  const flowRunLeafAbortRef = useRef<AbortController | null>(null);
  const flowRunningFgIdsRef = useRef<Set<string>>(new Set());
  const [varDialogOpen, setVarDialogOpen] = useState(false);
  const [deviceVarDialogOpen, setDeviceVarDialogOpen] = useState(false);
  const [selectedScenarioDeviceId, setSelectedScenarioDeviceId] = useState<
    string | null
  >(null);
  const [installDialogOpen, setInstallDialogOpen] = useState(false);
  const [installUrl, setInstallUrl] = useState('');
  const [jsonDialogOpen, setJsonDialogOpen] = useState(false);

  // Scenario-player running state + stop handle. Used by the Farm back button
  // and device-switch guard to confirm+abort before leaving.
  const [playerPlaying, setPlayerPlaying] = useState(false);
  const stopPlayerRef = useRef<(() => void) | null>(null);
  const [exitConfirm, setExitConfirm] = useState<null | (() => void)>(null);

  const setCoordinatePickTargetSafe = useCallback(
    (next: CoordinatePickTarget | null) => {
      if (next != null && record.recording) {
        toast.warning('Tắt chế độ ghi trước khi lấy tọa độ từ mirror.');
        return;
      }
      setCoordinatePickTarget(next);
    },
    [record.recording]
  );

  useEffect(() => {
    if (coordinatePickTarget || flowCoordPick || flowSelectorPickFgId) {
      queueMicrotask(() =>
        mirrorColRef.current?.scrollIntoView({
          behavior: 'smooth',
          block: 'nearest'
        })
      );
    }
  }, [coordinatePickTarget, flowCoordPick, flowSelectorPickFgId]);

  // Hierarchy changed => stale node bounds/highlight must be cleared.
  useEffect(() => {
    setHighlightBounds(null);
    setSelectedNodeId(null);
  }, [hierarchy.xml]);

  // Inline step runner (step-by-step without entering player mode)
  const [stepRunStates, setStepRunStates] = useState<
    Record<string, 'idle' | 'running' | 'ok' | 'error'>
  >({});
  const stepRunAbortRef = useRef<AbortController | null>(null);
  // Track active SSE preview trace so unmount (navigation away) can both
  // abort the fetch AND hit the server's explicit cancel endpoint — the SSE
  // disconnect check on the server can lag a cycle on slow networks, and
  // the user expected the scenario to stop the moment they leave the page.
  const activePreviewRef = useRef<ActivePreviewTrace | null>(null);
  const previewRunIdRef = useRef(0);
  const previewSession = useMemo(
    () => createPreviewRunSession(activePreviewRef, previewRunIdRef),
    []
  );
  const selectedSerialForStopRef = useRef<string | null>(null);
  useEffect(() => {
    selectedSerialForStopRef.current =
      device.selectedDevice?.serial?.trim() ?? null;
  }, [device.selectedDevice?.serial]);

  // Hard stop on unmount: abort in-flight previews and cancel server-side.
  useEffect(() => {
    const hardStop = () => {
      stepRunAbortRef.current?.abort();
      flowRunLeafAbortRef.current?.abort();
      const active = previewSession.takeActiveForCancel();
      const serial = selectedSerialForStopRef.current;
      if (active) {
        cancelPreviewStream(active.serial, active.traceId).catch(
          () => undefined
        );
        interruptDevice(active.serial).catch(() => undefined);
      } else if (serial) {
        interruptDevice(serial).catch(() => undefined);
      }
    };
    const onPageHide = () => hardStop();
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      hardStop();
    };
  }, [previewSession]);

  const handleStopInlineRun = useCallback(() => {
    // Three-pronged stop so the scenario exits quickly regardless of where
    // the executor is stuck:
    //   1) abort() closes the SSE fetch → server notices disconnect (~100ms)
    //   2) explicit cancel route sets cancel_event immediately (no polling lag)
    //   3) interrupt also cancels any preview without a captured trace_id
    stepRunAbortRef.current?.abort();
    flowRunLeafAbortRef.current?.abort();
    const serial = device.selectedDevice?.serial?.trim();
    const active = previewSession.takeActiveForCancel();
    if (active) {
      cancelPreviewStream(active.serial, active.traceId).catch(() => undefined);
      interruptDevice(active.serial).catch(() => undefined);
    } else if (serial) {
      interruptDevice(serial).catch(() => undefined);
    }
    flowRunningFgIdsRef.current.clear();
    const hadRunning =
      Object.values(stepRunStates).some((st) => st === 'running') ||
      Object.values(flowRunStates).some((st) => st === 'running');
    setStepRunStates((s) => {
      if (!Object.values(s).some((st) => st === 'running')) return s;
      const n = { ...s };
      for (const k of Object.keys(n)) {
        if (n[k] === 'running') delete n[k];
      }
      return n;
    });
    setFlowRunStates((s) => {
      if (!Object.values(s).some((st) => st === 'running')) return s;
      const n = { ...s };
      for (const k of Object.keys(n)) {
        if (n[k] === 'running') delete n[k];
      }
      return n;
    });
    if (hadRunning) {
      queueMicrotask(() => toast.info('Đã dừng chạy thử'));
    }
  }, [
    previewSession,
    device.selectedDevice?.serial,
    stepRunStates,
    flowRunStates
  ]);

  const inlinePreviewRunning = useMemo(
    () =>
      Object.values(stepRunStates).some((st) => st === 'running') ||
      Object.values(flowRunStates).some((st) => st === 'running'),
    [stepRunStates, flowRunStates]
  );
  const previewBlocking = playerPlaying || inlinePreviewRunning;

  const deviceSelectValue = useMemo(() => {
    const serial = device.selectedSerial;
    if (!serial) return undefined;
    return device.connectedDevices.some((d) => d.serial === serial)
      ? serial
      : undefined;
  }, [device.selectedSerial, device.connectedDevices]);

  const handleFlowStepsChange = useCallback(
    (newSteps: FlowStep[]) => {
      steps.setItems(
        newSteps.map((s: FlowStep, i: number) => ({
          ...s,
          _id: (s as { _id?: string })._id || `step-${Date.now()}-${i}`
        })) as typeof steps.items
      );
    },
    [steps]
  );

  const handlePlayerPlayingChange = useCallback(
    (playing: boolean) => {
      hierarchy.setPaused(playing);
      setPlayerPlaying(playing);
    },
    [hierarchy.setPaused]
  );

  const registerPlayerStop = useCallback((fn: (() => void) | null) => {
    stopPlayerRef.current = fn;
  }, []);

  const mirrorBusyBanner = useMemo(() => {
    const d = device.selectedDevice;
    if (!d) return null;
    const blocked =
      (d.state || '').replace('DeviceState.', '') === 'BUSY' ||
      (d.scenario_active ?? 0) > 0;
    if (!blocked) return null;
    return (
      <div className='flex w-full shrink-0 items-center gap-2 border-b border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300'>
        <span>{t('takeover.manualControlBlocked')}</span>
      </div>
    );
  }, [device.selectedDevice, t]);

  // Farm back button, device switch, player close — confirm before leaving while preview runs.
  const guardWhilePreviewActive = useCallback(
    (action: () => void) => {
      if (previewBlocking) {
        setExitConfirm(() => action);
      } else {
        action();
      }
    },
    [previewBlocking]
  );

  const promoteMultiFollower = useCallback(
    (serial: string) => {
      guardWhilePreviewActive(() => {
        const previousPrimary = device.selectedDevice?.serial;
        if (!previousPrimary) return;
        setMultiFollowerSerials((prev) =>
          Array.from(
            new Set([
              ...prev.filter((item) => item !== serial),
              previousPrimary
            ])
          )
        );
        device.setSelectedSerial(serial);
      });
    },
    [
      device.selectedDevice?.serial,
      device.setSelectedSerial,
      guardWhilePreviewActive
    ]
  );

  // Global guard: intercept sidebar/header links while preview is running.
  useEffect(() => {
    if (!previewBlocking) return;
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
  }, [previewBlocking, router]);

  // Variables for step execution (synced from loaded scenario, editable inline)
  const [scenarioVariables, setScenarioVariables] = useState<
    Record<string, any>
  >(() => flattenVarDefs(save.editingContext?.variables ?? {}));
  const [deviceVarJsonDrafts, setDeviceVarJsonDrafts] = useState<
    Record<string, string>
  >({});
  const [deviceVarEnabledByDevice, setDeviceVarEnabledByDevice] = useState<
    Record<string, boolean>
  >({});
  const [
    pendingScenarioDeviceVarsDraftMap,
    setPendingScenarioDeviceVarsDraftMap
  ] = useState<Record<string, Record<string, any>> | null>(null);
  const activeCampaignId = save.editingContext?.campaignId ?? null;
  const activeScenarioId = save.editingContext?.scenarioId ?? null;
  const selectedSerial = device.selectedDevice?.serial ?? null;
  const devicesQuery = useQuery({
    queryKey: ['control-record-device-map'],
    queryFn: devicesApi.list,
    staleTime: 15_000
  });
  const selectedDeviceId = useMemo(() => {
    if (!selectedSerial) return null;
    return (
      devicesQuery.data?.find((d) => d.serial === selectedSerial)?.id ?? null
    );
  }, [devicesQuery.data, selectedSerial]);
  const deviceVarsParseMsgs = useMemo(
    () => ({
      invalidJson: tDv('parseInvalidJson'),
      invalidRoot: tDv('parseInvalidRoot')
    }),
    [tDv]
  );
  const inlineScenarioDeviceVars = useMemo(() => {
    if (!selectedDeviceId) return null;
    if (deviceVarEnabledByDevice[selectedDeviceId] !== true) return null;
    const draft = deviceVarJsonDrafts[selectedDeviceId];
    let vars: Record<string, any>;
    try {
      vars = parseDeviceVarsJson(draft ?? '{}', deviceVarsParseMsgs);
    } catch {
      return null;
    }
    return Object.keys(vars).length > 0 ? vars : null;
  }, [
    selectedDeviceId,
    deviceVarJsonDrafts,
    deviceVarEnabledByDevice,
    deviceVarsParseMsgs
  ]);
  const hasEnabledDeviceVars = useMemo(
    () => Object.values(deviceVarEnabledByDevice).some(Boolean),
    [deviceVarEnabledByDevice]
  );
  const campaignDevicesQuery = useQuery({
    queryKey: ['campaign-devices', activeCampaignId],
    enabled: !!activeCampaignId,
    queryFn: () => campaignsApi.getDevices(activeCampaignId!)
  });
  const campaignForGlobalVarsQuery = useQuery({
    queryKey: ['campaign', activeCampaignId, 'global-vars-preview'],
    enabled: deviceVarDialogOpen && !!activeCampaignId,
    queryFn: () => campaignsApi.get(activeCampaignId!),
    staleTime: 30_000
  });
  useEffect(() => {
    if (!deviceVarDialogOpen) return;
    if (selectedScenarioDeviceId) return;
    if (selectedDeviceId) {
      setSelectedScenarioDeviceId(selectedDeviceId);
      return;
    }
    const firstCampaignDeviceId = campaignDevicesQuery.data?.[0]?.id ?? null;
    if (firstCampaignDeviceId)
      setSelectedScenarioDeviceId(firstCampaignDeviceId);
  }, [
    deviceVarDialogOpen,
    selectedScenarioDeviceId,
    selectedDeviceId,
    campaignDevicesQuery.data
  ]);
  const selectedDeviceLabel = useMemo(() => {
    const source = campaignDevicesQuery.data ?? devicesQuery.data ?? [];
    const d = source.find(
      (x) => x.id === (selectedScenarioDeviceId ?? selectedDeviceId)
    );
    if (!d) return tDvDlg('noDeviceSelected');
    const model = `${d.brand || ''} ${d.model || ''}`.trim();
    return model ? `${model} (${d.serial})` : d.serial;
  }, [
    campaignDevicesQuery.data,
    devicesQuery.data,
    selectedScenarioDeviceId,
    selectedDeviceId,
    tDvDlg
  ]);
  const currentDeviceVarJsonDraft = selectedScenarioDeviceId
    ? (deviceVarJsonDrafts[selectedScenarioDeviceId] ??
      formatInitialDeviceVars({}, scenarioVariables))
    : formatInitialDeviceVars({}, scenarioVariables);
  const currentDeviceVarsEnabled = selectedScenarioDeviceId
    ? deviceVarEnabledByDevice[selectedScenarioDeviceId] === true
    : false;
  const currentDeviceVarJsonError = useMemo(() => {
    if (!currentDeviceVarsEnabled) return '';
    try {
      parseDeviceVarsJson(currentDeviceVarJsonDraft, deviceVarsParseMsgs);
      return '';
    } catch (err) {
      return err instanceof Error ? err.message : tDv('parseUnknown');
    }
  }, [
    currentDeviceVarJsonDraft,
    currentDeviceVarsEnabled,
    deviceVarsParseMsgs,
    tDv
  ]);
  const deviceVarGlobalPreview = useMemo(
    () =>
      mergeCampaignScenarioVariables(
        campaignVariables(campaignForGlobalVarsQuery.data),
        scenarioVariables
      ),
    [campaignForGlobalVarsQuery.data, scenarioVariables]
  );
  const setCurrentDeviceVarsEnabled = useCallback(
    (enabled: boolean) => {
      if (!selectedScenarioDeviceId) return;
      setDeviceVarEnabledByDevice((prev) => ({
        ...prev,
        [selectedScenarioDeviceId]: enabled
      }));
      setDeviceVarJsonDrafts((prev) => ({
        ...prev,
        [selectedScenarioDeviceId]:
          prev[selectedScenarioDeviceId] ??
          formatInitialDeviceVars({}, scenarioVariables)
      }));
    },
    [scenarioVariables, selectedScenarioDeviceId]
  );
  const setCurrentDeviceVarJsonDraft = useCallback(
    (value: string) => {
      if (!selectedScenarioDeviceId) return;
      setDeviceVarJsonDrafts((prev) => ({
        ...prev,
        [selectedScenarioDeviceId]: value
      }));
    },
    [selectedScenarioDeviceId]
  );
  const scenarioDeviceVarsQuery = useQuery({
    queryKey: [
      'scenario-device-vars',
      activeCampaignId,
      activeScenarioId,
      selectedScenarioDeviceId
    ],
    enabled:
      deviceVarDialogOpen &&
      !!activeCampaignId &&
      !!activeScenarioId &&
      !!selectedScenarioDeviceId,
    queryFn: () =>
      campaignsApi.getScenarioDeviceVariables(
        activeCampaignId!,
        activeScenarioId!,
        selectedScenarioDeviceId!
      )
  });
  useEffect(() => {
    if (!deviceVarDialogOpen) return;
    const devices = campaignDevicesQuery.data ?? [];
    if (devices.length === 0) return;
    if (!activeScenarioId) {
      const seeded: Record<string, string> = {};
      const enabled: Record<string, boolean> = {};
      const base = pendingScenarioDeviceVarsDraftMap ?? {};
      for (const d of devices) {
        const vars = { ...(base[d.id] ?? {}) };
        seeded[d.id] = formatInitialDeviceVars(vars, scenarioVariables);
        enabled[d.id] = Object.keys(vars).length > 0;
      }
      setDeviceVarJsonDrafts(seeded);
      setDeviceVarEnabledByDevice(enabled);
      return;
    }
    let cancelled = false;
    (async () => {
      const entries = await Promise.all(
        devices.map(async (d) => {
          const res = await campaignsApi.getScenarioDeviceVariables(
            activeCampaignId!,
            activeScenarioId,
            d.id
          );
          return [d.id, (res.vars ?? {}) as Record<string, any>] as const;
        })
      );
      if (cancelled) return;
      const seeded: Record<string, string> = Object.fromEntries(
        entries.map(([deviceId, vars]) => [
          deviceId,
          formatInitialDeviceVars(vars, scenarioVariables)
        ])
      );
      const enabled: Record<string, boolean> = Object.fromEntries(
        entries.map(([deviceId, vars]) => [
          deviceId,
          Object.keys(vars).length > 0
        ])
      );
      setDeviceVarJsonDrafts(seeded);
      setDeviceVarEnabledByDevice(enabled);
    })().catch((err) =>
      toast.error(tDvDlg('loadVarsError', { message: String(err) }))
    );
    return () => {
      cancelled = true;
    };
  }, [
    deviceVarDialogOpen,
    campaignDevicesQuery.data,
    activeCampaignId,
    activeScenarioId,
    pendingScenarioDeviceVarsDraftMap,
    scenarioVariables,
    tDvDlg
  ]);
  const saveScenarioDeviceVarsMutation = useMutation({
    mutationFn: async (drafts: Record<string, string>) => {
      if (!activeCampaignId || !activeScenarioId) return;
      const devices = campaignDevicesQuery.data ?? [];
      await Promise.all(
        devices.map((d) => {
          let vars: Record<string, any> = {};
          if (deviceVarEnabledByDevice[d.id] === true) {
            try {
              vars = parseDeviceVarsJson(
                drafts[d.id] ?? '{}',
                deviceVarsParseMsgs
              );
            } catch {
              throw new Error(tDv('invalidAtDevice', { serial: d.serial }));
            }
          }
          return campaignsApi.replaceScenarioDeviceVariables(
            activeCampaignId,
            activeScenarioId,
            d.id,
            {
              vars
            }
          );
        })
      );
    },
    onSuccess: async () => {
      if (!activeCampaignId || !activeScenarioId) {
        toast.success(tDvDlg('saveAllSuccess'));
        setDeviceVarDialogOpen(false);
        return;
      }
      try {
        const devices = campaignDevicesQuery.data ?? [];
        const entries = await Promise.all(
          devices.map(async (d) => {
            const res = await campaignsApi.getScenarioDeviceVariables(
              activeCampaignId,
              activeScenarioId,
              d.id
            );
            return [d.id, (res.vars ?? {}) as Record<string, any>] as const;
          })
        );
        setDeviceVarJsonDrafts(
          Object.fromEntries(
            entries.map(([deviceId, vars]) => [
              deviceId,
              formatInitialDeviceVars(vars, scenarioVariables)
            ])
          )
        );
        setDeviceVarEnabledByDevice(
          Object.fromEntries(
            entries.map(([deviceId, vars]) => [
              deviceId,
              Object.keys(vars).length > 0
            ])
          )
        );
      } catch {
        /* drafts may be stale until dialog reopens; server still has saved vars */
      }
      toast.success(tDvDlg('saveAllSuccess'));
      setDeviceVarDialogOpen(false);
    },
    onError: (err) => toast.error(String(err))
  });
  useEffect(() => {
    if (!pendingScenarioDeviceVarsDraftMap) return;
    if (!activeCampaignId || !activeScenarioId) return;
    const devices = campaignDevicesQuery.data ?? [];
    if (devices.length === 0) return;
    Promise.all(
      devices.map((d) => {
        const vars = pendingScenarioDeviceVarsDraftMap[d.id] ?? {};
        return campaignsApi.replaceScenarioDeviceVariables(
          activeCampaignId,
          activeScenarioId,
          d.id,
          {
            vars
          }
        );
      })
    )
      .then(() => {
        toast.success('Đã áp dụng biến thiết bị vào scenario vừa lưu');
        setPendingScenarioDeviceVarsDraftMap(null);
      })
      .catch((err) => {
        toast.error(
          `Không áp dụng được biến thiết bị sau khi lưu scenario: ${String(err)}`
        );
      });
  }, [
    pendingScenarioDeviceVarsDraftMap,
    activeCampaignId,
    activeScenarioId,
    campaignDevicesQuery.data
  ]);

  useEffect(() => {
    if (save.editingContext?.variables) {
      setScenarioVariables(flattenVarDefs(save.editingContext.variables));
    }
  }, [save.editingContext]);

  useEffect(() => {
    if (save.orgScenarioContext?.variables) {
      setScenarioVariables(flattenVarDefs(save.orgScenarioContext.variables));
    }
  }, [save.orgScenarioContext]);

  useEffect(() => {
    stepsItemsRef.current = steps.items;
  }, [steps.items]);

  useEffect(() => {
    flowSelectedFgIdRef.current = flowSelectedFgId;
  }, [flowSelectedFgId]);

  useEffect(() => {
    if (showFlowUi) return;
    setFlowSelectedFgId(null);
    setFlowDetailStep(null);
    setFlowCoordPick(null);
    setFlowSelectorPickFgId(null);
    setFlowRunStates((prev) =>
      Object.keys(prev).length === 0 ? prev : {}
    );
  }, [showFlowUi]);

  useEffect(() => {
    if (!flowSelectedFgId) {
      setFlowDetailStep(null);
      return;
    }
    if (flowDetailDebounceRef.current || flowDetailSyncingRef.current) {
      return;
    }
    const found = findStepByFlowgramId(
      steps.items as FlowStep[],
      flowSelectedFgId
    );
    setFlowDetailStep(
      found ? (JSON.parse(JSON.stringify(found)) as FlowStep) : null
    );
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
      const runId = previewSession.beginRun();
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
            if (ev.event === 'step_done') {
              setFlowRunStates((s) => ({
                ...s,
                [fgId]: ev.ok ? 'ok' : 'error'
              }));
              if (!ev.ok) toast.error(String(ev.message ?? 'Step lỗi'));
            }
          }),
          ctrl.signal,
          scenarioVariables,
          null,
          activeScenarioId,
          inlineScenarioDeviceVars
        );
      } catch (e) {
        if (!ctrl.signal.aborted) {
          setFlowRunStates((s) => ({ ...s, [fgId]: 'error' }));
          toast.error(String(e));
        }
      } finally {
        previewSession.onStreamEnd(runId);
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
    [
      activeScenarioId,
      device.selectedDevice,
      scenarioVariables,
      inlineScenarioDeviceVars,
      previewSession
    ]
  );

  const handleFlowDetailChange = useCallback(
    (next: FlowStep) => {
      const cloned = JSON.parse(JSON.stringify(next)) as FlowStep;
      flowDetailPendingRef.current = cloned;
      setFlowDetailStep(cloned);
      if (flowDetailDebounceRef.current)
        clearTimeout(flowDetailDebounceRef.current);
      flowDetailDebounceRef.current = setTimeout(() => {
        flowDetailDebounceRef.current = null;
        const fgId = flowSelectedFgIdRef.current;
        const ctx = flowCtxRef.current;
        const latest = flowDetailPendingRef.current;
        if (!fgId || !ctx || !latest) return;
        flowDetailSyncingRef.current = true;
        const patched = patchStepByFlowgramId(
          stepsItemsRef.current as FlowStep[],
          fgId,
          latest
        );
        try {
          const synced = applyStepsToFlowgramDocument(ctx, patched);
          flowStepsRef.current = synced as typeof steps.items;
          steps.setItems(synced as typeof steps.items);
          const updated = findStepByFlowgramId(synced, fgId);
          if (updated) {
            const normalized = JSON.parse(
              JSON.stringify(updated)
            ) as FlowStep;
            flowDetailPendingRef.current = normalized;
            setFlowDetailStep(normalized);
          }
        } catch (e) {
          toast.error(`Không áp dụng được lên canvas: ${String(e)}`);
        } finally {
          flowDetailSyncingRef.current = false;
        }
      }, 240);
    },
    [steps]
  );

  const flowWorkbench = useMemo(
    () => ({
      deviceSerial: device.selectedDevice?.serial ?? null,
      selectedFgId: flowSelectedFgId,
      setSelectedFgId: setFlowSelectedFgId,
      runStates: flowRunStates,
      onRunLeafStep: handleFlowRunLeaf
    }),
    [device.selectedDevice, flowSelectedFgId, flowRunStates, handleFlowRunLeaf]
  );

  const handleRunStep = useCallback(
    async (step: FlowStep, runKey: string) => {
      if (!device.selectedDevice) {
        toast.warning('Chưa chọn thiết bị');
        return;
      }
      if (stepRunStates[runKey] === 'running') return;
      stepRunAbortRef.current?.abort();
      const ctrl = new AbortController();
      stepRunAbortRef.current = ctrl;
      const runId = previewSession.beginRun();
      const label = /^\d+$/.test(runKey)
        ? `Bước ${Number(runKey) + 1}`
        : 'Bước';
      setStepRunStates((s) => ({ ...s, [runKey]: 'running' }));
      const serial = device.selectedDevice.serial;
      try {
        await previewScenarioStream(
          serial,
          [step as Record<string, any>],
          previewSession.makeStreamHandler(runId, serial, (event) => {
            if (event.event === 'step_done') {
              setStepRunStates((s) => ({
                ...s,
                [runKey]: event.ok ? 'ok' : 'error'
              }));
              if (!event.ok) toast.error(`${label}: ${event.message ?? 'Lỗi'}`);
            }
          }),
          ctrl.signal,
          scenarioVariables,
          null,
          activeScenarioId,
          inlineScenarioDeviceVars
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
        previewSession.onStreamEnd(runId);
        if (!ctrl.signal.aborted) {
          setTimeout(
            () =>
              setStepRunStates((s) => {
                const n = { ...s };
                if (n[runKey] !== 'running') delete n[runKey];
                return n;
              }),
            3000
          );
        }
      }
    },
    [
      activeScenarioId,
      device.selectedDevice,
      stepRunStates,
      scenarioVariables,
      inlineScenarioDeviceVars,
      previewSession
    ]
  );

  const addStepFromSelector = useCallback(
    (
      stepType:
        | 'tap_selector'
        | 'long_tap_selector'
        | 'wait_element'
        | 'assert_element'
        | 'input_selector'
    ) => {
      const by = selector.by as string;
      const value = selector.value;
      if (!value) return;
      const newStep: FlowStep = (
        stepType === 'tap_selector'
          ? buildSelectorStep('tap_selector', by, value)
          : stepType === 'long_tap_selector'
            ? buildSelectorStep('long_tap_selector', by, value, {
                duration_ms: 800
              })
            : stepType === 'wait_element'
              ? buildSelectorStep('wait_element', by, value, { timeout: 10 })
              : stepType === 'assert_element'
                ? buildSelectorStep('assert_element', by, value, { timeout: 5 })
                : buildSelectorStep('input_selector', by, value, {
                    text: '',
                    clear_first: true
                  })
      ) as FlowStep;
      const id = `step-${Date.now()}-${steps.items.length}`;
      steps.setItems([
        ...(steps.items as any[]),
        { ...newStep, _id: id }
      ] as any);
      toast.success(`Đã thêm bước ${stepType}`);
    },
    [selector.by, selector.value, steps]
  );

  useEffect(() => {
    setSkipTapRecordingWhilePick(
      selectorPickTarget != null ||
        coordinatePickTarget != null ||
        flowCoordPick != null ||
        flowSelectorPickFgId != null
    );
    return () => setSkipTapRecordingWhilePick(false);
  }, [
    selectorPickTarget,
    coordinatePickTarget,
    flowCoordPick,
    flowSelectorPickFgId,
    setSkipTapRecordingWhilePick
  ]);

  const applySelectorPick = useCallback(
    (
      pick: ScenarioSelectorShape,
      fallback?: { rx: number; ry: number } | null
    ) => {
      if (!selectorPickTarget) return;
      const raw = steps.items as FlowStep[];
      const next = applySelectorToSteps(
        raw,
        selectorPickTarget,
        pick,
        fallback ?? null
      );
      if (next === raw) {
        toast.warning(t('pickSelectorNoElement'));
        return;
      }
      steps.setItems(
        next.map((s: FlowStep, i: number) => ({
          ...s,
          _id: (s as { _id?: string })._id || `step-${Date.now()}-${i}`
        })) as any
      );
      selector.setBy(pick.by as typeof selector.by);
      selector.setValue(pick.value);
      setSelectorPickTarget(null);
      const condHint =
        pick.conditions && Object.keys(pick.conditions).length > 0
          ? ` · +${Object.keys(pick.conditions).length} điều kiện`
          : '';
      const instHint =
        pick.instance != null ? ` · instance=${pick.instance}` : '';
      if (fallback) {
        toast.success(
          `${t('pickSelectorApplied', { by: pick.by, value: pick.value.slice(0, 48) })}${condHint}${instHint} · fallback=(${fallback.rx.toFixed(3)}, ${fallback.ry.toFixed(3)})`
        );
      } else {
        toast.success(
          `${t('pickSelectorApplied', { by: pick.by, value: pick.value.slice(0, 48) })}${condHint}${instHint}`
        );
      }
    },
    [selectorPickTarget, steps, selector, t]
  );

  const handleScreenSwipe = useCallback(
    (
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
        showFlowUi &&
        flowCoordPick?.kind === 'swipe' &&
        flowCtxRef.current &&
        flowCoordPick.fgId
      ) {
        const ctx = flowCtxRef.current;
        const fgId = flowCoordPick.fgId;
        const merged = mergeStepByFlowgramId(
          steps.items as FlowStep[],
          fgId,
          (prev) => {
            if (prev.type === 'swipe_ratio') {
              return { ...prev, x1, y1, x2, y2, duration_ms } as FlowStep;
            }
            return prev;
          }
        );
        try {
          const synced = applyStepsToFlowgramDocument(ctx, merged);
          flowStepsRef.current = synced as typeof steps.items;
          steps.setItems(synced as typeof steps.items);
        } catch (e) {
          toast.error(`Canvas: ${String(e)}`);
        }
        setFlowCoordPick(null);
        toast.success(`Đã gán swipe_ratio: (${x1}, ${y1}) → (${x2}, ${y2})`, {
          duration: 2500
        });
        return;
      }

      if (coordinatePickTarget?.mode !== 'swipe_segment') return;
      const raw = steps.items as FlowStep[];
      const next = applySwipeSegmentToSteps(
        raw,
        coordinatePickTarget,
        rx1,
        ry1,
        rx2,
        ry2,
        durationMs
      );
      if (next === raw) {
        toast.warning('Bước đích phải là swipe_ratio.');
      } else {
        steps.setItems(
          next.map((s: FlowStep, i: number) => ({
            ...s,
            _id: (s as { _id?: string })._id || `step-${Date.now()}-${i}`
          })) as any
        );
        setCoordinatePickTarget(null);
        toast.success(
          `Đã cập nhật đoạn vuốt: (${x1}, ${y1}) → (${x2}, ${y2})`,
          { duration: 2500 }
        );
      }
    },
    [
      coordinatePickTarget,
      showFlowUi,
      flowCoordPick,
      steps
    ]
  );

  // When user taps the phone screen → hierarchy highlight + optional selector pick
  const handleScreenTap = useCallback(
    (rx: number, ry: number) => {
      const tree = parseHierarchyTree(hierarchyXml);
      if (tree) {
        const nodeId = findNodeIdAtRatio(tree, rx, ry);
        setSelectedNodeId(nodeId);
      }

      const rx3 = parseFloat(rx.toFixed(3));
      const ry3 = parseFloat(ry.toFixed(3));

      if (
        showFlowUi &&
        flowCoordPick?.kind === 'tap' &&
        flowCtxRef.current &&
        flowCoordPick.fgId
      ) {
        const ctx = flowCtxRef.current;
        const fgId = flowCoordPick.fgId;
        const merged = mergeStepByFlowgramId(
          steps.items as FlowStep[],
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
        try {
          const synced = applyStepsToFlowgramDocument(ctx, merged);
          flowStepsRef.current = synced as typeof steps.items;
          steps.setItems(synced as typeof steps.items);
        } catch (e) {
          toast.error(`Canvas: ${String(e)}`);
        }
        setFlowCoordPick(null);
        toast.success(`Đã gán tọa độ (${rx3}, ${ry3}) cho node`, {
          duration: 2000
        });
        return;
      }

      if (showFlowUi && flowSelectorPickFgId && flowCtxRef.current) {
        const sel = findSelectorInXml(hierarchyXml, rx, ry);
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
        const merged = mergeSelectorByFlowgramId(
          steps.items as FlowStep[],
          fgId,
          sel.selector
        );
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
        toast.success(
          t('pickSelectorApplied', {
            by: sel.by,
            value: sel.value.trim().slice(0, 48)
          })
        );
        return;
      }

      if (coordinatePickTarget?.mode === 'tap_point') {
        const raw = steps.items as FlowStep[];
        const next = applyTapPointToSteps(raw, coordinatePickTarget, rx, ry);
        if (next === raw) {
          toast.warning(
            'Bước đích phải là tap_ratio hoặc tap (tọa độ dự phòng).'
          );
        } else {
          steps.setItems(
            next.map((s: FlowStep, i: number) => ({
              ...s,
              _id: (s as { _id?: string })._id || `step-${Date.now()}-${i}`
            })) as any
          );
          setCoordinatePickTarget(null);
          toast.success(`Đã cập nhật tọa độ chạm: (${rx3}, ${ry3})`, {
            duration: 2500
          });
        }
        return;
      }

      if (selectorPickTarget) {
        const sel = findSelectorInXml(hierarchyXml, rx, ry);
        if (sel?.value) {
          applySelectorPick(sel.selector, { rx: rx3, ry: ry3 });
        } else {
          toast.warning(t('pickSelectorNoElement'));
        }
        return;
      }
    },
    [
      hierarchyXml,
      selectorPickTarget,
      coordinatePickTarget,
      applySelectorPick,
      steps,
      t,
      showFlowUi,
      flowCoordPick,
      flowSelectorPickFgId,
      device.selectedDevice,
      selector
    ]
  );

  handleScreenTapRef.current = handleScreenTap;
  handleScreenSwipeRef.current = handleScreenSwipe;

  const mirrorOnTap = useCallback((rx: number, ry: number) => {
    handleScreenTapRef.current(rx, ry);
  }, []);

  const mirrorSwipeEnabled =
    coordinatePickTarget?.mode === 'swipe_segment' ||
    (showFlowUi && flowCoordPick?.kind === 'swipe');

  const mirrorOnSwipe = useMemo(
    () =>
      mirrorSwipeEnabled
        ? (
            rx1: number,
            ry1: number,
            rx2: number,
            ry2: number,
            durationMs: number
          ) =>
            handleScreenSwipeRef.current(rx1, ry1, rx2, ry2, durationMs)
        : undefined,
    [mirrorSwipeEnabled]
  );

  const mirrorInputLocked = useMemo(() => {
    const d = device.selectedDevice;
    if (!d) return { hideControls: true, readOnlyPreview: true };
    const blocked =
      (d.state || '').replace('DeviceState.', '') === 'BUSY' ||
      (d.scenario_active ?? 0) > 0;
    return { hideControls: blocked, readOnlyPreview: blocked };
  }, [
    device.selectedDevice?.serial,
    device.selectedDevice?.state,
    device.selectedDevice?.scenario_active
  ]);

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
  if (
    device.connectedDevices.length === 0 &&
    !save.editingContext &&
    !save.templateContext
  ) {
    return (
      <div className='flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-20 text-center'>
        <Video className='mb-3 size-10 text-muted-foreground/40' />
        <p className='mb-1 text-base font-medium'>{t('noDeviceConnected')}</p>
        <p className='mb-4 text-sm text-muted-foreground'>
          {t('noDeviceConnectMessage')}
        </p>
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
    <div className='flex h-[calc(100vh-80px)] min-h-0 flex-col overflow-hidden bg-background'>
      <SafeModeBanner className='mx-3 mt-2' />

      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div className='flex min-w-0 shrink-0 items-center gap-3 overflow-hidden border-b bg-background px-3 py-2'>
        {/* Back */}
        <Button
          variant='ghost'
          size='sm'
          className='-ml-1 shrink-0 gap-1.5 text-muted-foreground hover:text-foreground'
          onClick={() =>
            guardWhilePreviewActive(() => router.push(ROUTES.DEVICES.ROOT))
          }
        >
          <ArrowLeft className='size-3.5' />
          Farm
        </Button>

        <div className='h-5 w-px bg-border' />

        {/* Title */}
        <div className='min-w-0 flex-1'>
          <p className='truncate text-sm font-semibold leading-tight'>
            {save.templateContext
              ? save.templateContext.name
              : save.editingContext
                ? save.editingContext.name
                : t('pageTitle')}
          </p>
          <p className='text-[10px] text-muted-foreground'>
            {save.templateContext ? t('templateEyebrow') : t('pageEyebrow')}
          </p>
        </div>

        {save.editingContext && (
          <Badge
            variant='outline'
            className='shrink-0 border-amber-400/40 bg-amber-400/10 text-[10px] font-medium text-amber-700 dark:text-amber-300'
          >
            {t('editingScenario')}
          </Badge>
        )}
        {save.templateContext && (
          <span className='inline-flex shrink-0 items-center rounded-full border border-emerald-400/40 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300'>
            {t('templateBadge')}
          </span>
        )}

        {/* Device selector + multi sync */}
        <div className='flex min-w-0 shrink items-center gap-1.5'>
          <div className='min-w-0 max-w-[min(240px,calc(100vw-16rem))]'>
            <Select
              value={deviceSelectValue}
              onValueChange={(v) =>
                guardWhilePreviewActive(() =>
                  device.setSelectedSerial(v || null)
                )
              }
            >
              <SelectTrigger
                className={cn(
                  'h-8 w-full min-w-0 max-w-full overflow-hidden text-xs',
                  '[&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:truncate [&_[data-slot=select-value]]:text-left'
                )}
              >
                <SelectValue placeholder={t('selectPhonePlaceholder')} />
              </SelectTrigger>
              <SelectContent className='max-w-[min(420px,calc(100vw-2rem))]'>
                {device.connectedDevices.map((d) => (
                  <SelectItem
                    key={d.serial}
                    value={d.serial}
                    title={deviceSelectFullTitle(d)}
                    className='text-xs'
                  >
                    <span className='inline-flex min-w-0 max-w-full items-center gap-1'>
                      <span className='min-w-0 truncate'>
                        {formatDeviceSelectLabel(d)}
                      </span>
                      {((d.state || '').replace('DeviceState.', '') ===
                        'BUSY' ||
                        (d.scenario_active ?? 0) > 0) && (
                        <Badge
                          variant='outline'
                          className='h-4 shrink-0 border-amber-400/40 bg-amber-400/10 px-1 text-[9px] font-medium text-amber-700 dark:text-amber-300'
                        >
                          {t('deviceCampaignBadge')}
                        </Badge>
                      )}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type='button'
                size='sm'
                variant={
                  multiFollowerSerials.length > 0 ? 'default' : 'outline'
                }
                className='h-8 shrink-0 gap-1.5 text-xs'
                disabled={
                  !selectedDevice ||
                  !canExecuteDevice ||
                  multiFollowerOptions.length === 0
                }
                title={
                  !canExecuteDevice
                    ? safeReadOnly
                      ? t('safeModeReadOnly')
                      : t('noControlPermission')
                    : multiFollowerOptions.length === 0
                      ? t('multiControl.noReadyDevices')
                      : undefined
                }
              >
                <SlidersHorizontal className='size-3.5' />
                {t('multiControl.buttonLabel')}
                {multiFollowerSerials.length > 0 ? (
                  <Badge
                    variant='secondary'
                    className='ml-0.5 h-4 rounded px-1 text-[10px]'
                  >
                    {multiFollowerSerials.length + 1}
                  </Badge>
                ) : null}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align='end' className='w-72'>
              <DropdownMenuLabel className='text-[11px] font-normal text-muted-foreground'>
                {t('multiControl.pickerLabel')}
              </DropdownMenuLabel>
              <DropdownMenuItem
                onSelect={(event) => {
                  event.preventDefault();
                  setMultiFollowerSerials(
                    multiFollowerOptions
                      .map((d) => d.serial)
                      .slice(0, MAX_MULTI_FOLLOWER_DEVICES)
                  );
                }}
                disabled={multiFollowerOptions.length === 0}
                className='text-xs'
              >
                {multiFollowerOptions.length > MAX_MULTI_FOLLOWER_DEVICES
                  ? t('multiControl.selectUpToLimit', {
                      count: MAX_MULTI_CONTROL_DEVICES
                    })
                  : t('multiControl.selectAllReady')}
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={(event) => {
                  event.preventDefault();
                  setMultiFollowerSerials([]);
                }}
                disabled={multiFollowerSerials.length === 0}
                className='text-xs'
              >
                {t('multiControl.clearSelection')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {multiFollowerOptions.length === 0 ? (
                <DropdownMenuItem disabled className='text-xs text-muted-foreground'>
                  {t('multiControl.noReadyDevices')}
                </DropdownMenuItem>
              ) : (
                multiFollowerOptions.map((d) => {
                  const checked = multiFollowerSerials.includes(d.serial);
                  const limitReached =
                    !checked &&
                    multiFollowerSerials.length >= MAX_MULTI_FOLLOWER_DEVICES;
                  return (
                    <DropdownMenuCheckboxItem
                      key={d.serial}
                      checked={checked}
                      disabled={limitReached}
                      onCheckedChange={(nextChecked) => {
                        setMultiFollowerSerials((prev) => {
                          if (!nextChecked) {
                            return prev.filter((serial) => serial !== d.serial);
                          }
                          if (
                            prev.includes(d.serial) ||
                            prev.length >= MAX_MULTI_FOLLOWER_DEVICES
                          ) {
                            return prev;
                          }
                          return [...prev, d.serial];
                        });
                      }}
                      onSelect={(event) => event.preventDefault()}
                      className='min-w-0 text-xs'
                      title={deviceSelectFullTitle(d)}
                    >
                      <span className='min-w-0 truncate'>
                        {formatDeviceSelectLabel(d)}
                      </span>
                    </DropdownMenuCheckboxItem>
                  );
                })
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* WS status */}
        <Badge
          variant='outline'
          className={cn(
            'h-8 shrink-0 gap-1.5 rounded-full px-2.5 text-[11px] font-medium',
            device.wsConnected
              ? 'border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400'
              : 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400'
          )}
        >
          <span
            className={cn(
              'size-1.5 rounded-full',
              device.wsConnected ? 'bg-green-500' : 'bg-red-500'
            )}
          />
          {device.wsConnected ? t('wsConnected') : t('wsDisconnected')}
        </Badge>

        <div className='h-5 w-px bg-border' />

        {/* Flow / List — ẩn khi ENABLE_FLOWGRAM_CONTROL_UI = false (tạm tắt Flowgram) */}
        {ENABLE_FLOWGRAM_CONTROL_UI && (
          <Button
            size='sm'
            variant={flowMode ? 'default' : 'outline'}
            className='h-8 shrink-0 gap-1.5 text-xs'
            onClick={() => {
              if (!flowMode) {
                flowStepsRef.current = steps.items;
                setFlowCanvasKey((k) => k + 1);
              } else {
                steps.setItems(flowStepsRef.current);
              }
              setFlowMode((v) => !v);
            }}
            title={
              flowMode ? t('flowSwitchToList') : t('flowSwitchToFlow')
            }
          >
            {flowMode ? (
              <List className='size-3.5' />
            ) : (
              <GitBranch className='size-3.5' />
            )}
            {flowMode ? t('flowListLabel') : t('flowFlowLabel')}
          </Button>
        )}
      </div>

      {/* ── Main: cây XML + mirror + editor (Danh sách hoặc Flow cùng khung) ── */}
      <div className='flex flex-1 overflow-hidden'>
        {/* ── COL 1: UI Hierarchy tree ──────────────────────────────────── */}
        <div
          className={cn(
            'flex shrink-0 flex-col border-r border-border/60 bg-muted/10 transition-all duration-200',
            treePanelOpen ? 'w-[280px]' : 'w-0 overflow-hidden'
          )}
        >
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
                deviceActive={Boolean(
                  selectedDevice?.state &&
                    !['DISCONNECTED', 'DEAD'].includes(
                      String(selectedDevice.state).toUpperCase()
                    )
                )}
                wsConnected={Boolean(device.wsConnected)}
                onNodeSelect={({ bounds, by, value, nodeId }) => {
                  setHighlightBounds(bounds);
                  if (nodeId != null) setSelectedNodeId(nodeId);
                  if (selectorPickTarget) {
                    const rich = findSelectorForTreeNode(hierarchy.xml, bounds);
                    if (rich?.value?.trim()) {
                      applySelectorPick(rich.selector);
                    } else if (value?.trim()) {
                      applySelectorPick({
                        by: by as ScenarioSelectorShape['by'],
                        value: value.trim()
                      });
                    } else {
                      toast.warning(t('pickSelectorNoElement'));
                    }
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
          <div
            className={cn(
              'shrink-0 border-t border-border/60 px-2.5 py-2',
              selector.value ? 'bg-primary/5' : 'bg-muted/30'
            )}
          >
            {selector.value ? (
              <>
                <div className='flex items-center gap-1.5 pb-1.5'>
                  <span className='min-w-0 flex-1 truncate font-mono text-[10px] text-muted-foreground'>
                    <span className='font-bold text-primary'>
                      [{selector.by}]
                    </span>{' '}
                    {selector.value}
                  </span>
                  <Button
                    size='sm'
                    variant='secondary'
                    className='h-5 shrink-0 px-1.5 text-[9px]'
                    onClick={() =>
                      selector.tap({ multiSerials: activeMultiSerials })
                    }
                    disabled={!selectedDevice || !canExecuteDevice}
                    title={
                      !canExecuteDevice
                        ? safeReadOnly
                          ? 'Safe mode: read-only'
                          : undefined
                        : undefined
                    }
                  >
                    Tap
                  </Button>
                </div>
                {!canExecuteDevice ? (
                  <p className='text-[10px] italic text-muted-foreground'>
                    {safeReadOnly
                      ? 'Safe mode: không cho điều khiển / thêm bước.'
                      : 'Bạn không có quyền điều khiển thiết bị.'}
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
                      <TooltipContent side='top' className='text-[10px]'>
                        Thêm bước tap_selector
                      </TooltipContent>
                    </Tooltip>
                    <Tooltip delayDuration={300}>
                      <TooltipTrigger asChild>
                        <button
                          type='button'
                          onClick={() =>
                            addStepFromSelector('long_tap_selector')
                          }
                          className='flex items-center gap-0.5 rounded bg-purple-500/10 px-1.5 py-0.5 text-[9px] font-medium text-purple-700 hover:bg-purple-500/20 dark:text-purple-400'
                        >
                          <MousePointerClick className='size-2.5' /> Long
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side='top' className='text-[10px]'>
                        Thêm bước long_tap_selector
                      </TooltipContent>
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
                      <TooltipContent side='top' className='text-[10px]'>
                        Thêm bước wait_element
                      </TooltipContent>
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
                      <TooltipContent side='top' className='text-[10px]'>
                        Thêm bước assert_element
                      </TooltipContent>
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
                      <TooltipContent side='top' className='text-[10px]'>
                        Thêm bước input_selector
                      </TooltipContent>
                    </Tooltip>
                  </div>
                )}
              </>
            ) : (
              <p className='text-[10px] text-muted-foreground'>
                {t('selectorBarHint')}
              </p>
            )}
          </div>
        </div>

        {/* Collapse toggle — hidden while multi-phone uses the freed horizontal space */}
        {!hasMultiFollowers ? (
          <button
            type='button'
            onClick={() => setLeftCollapsed(!leftCollapsed)}
            className='relative z-10 flex w-4 shrink-0 items-center justify-center border-r border-border/40 bg-muted/20 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground'
            title={leftCollapsed ? 'Mở cây giao diện' : 'Thu cây giao diện'}
          >
            {leftCollapsed ? (
              <ChevronRight className='size-3' />
            ) : (
              <ChevronLeft className='size-3' />
            )}
          </button>
        ) : null}

        {/* ── COL 2: Phone screen ───────────────────────────────────────── */}
        <div
          ref={mirrorColRef}
          className={cn(
            'flex min-h-0 flex-col overflow-hidden bg-muted/20',
            multiFocusMode
              ? 'min-w-0 flex-1'
              : 'w-[clamp(300px,30vw,360px)] shrink-0 border-r border-border/60'
          )}
        >
          {selectedDevice ? (
            hasMultiFollowers ? (
              <MultiDeviceStage
                mode={multiFocusMode ? 'focus' : 'edit'}
                toolbar={
                  multiFocusMode ? (
                    <div className='flex shrink-0 items-center gap-2 border-b border-border/60 bg-background/90 px-3 py-1.5'>
                      <Button
                        size='sm'
                        variant={record.recording ? 'destructive' : 'default'}
                        className='h-7 gap-1.5 px-2.5 text-xs'
                        onClick={() => void record.toggleRecording()}
                      >
                        {record.recording ? (
                          <Square className='size-3.5' />
                        ) : (
                          <Circle className='size-3.5 fill-current' />
                        )}
                        {record.recording
                          ? t('stopRecording')
                          : t('startRecording')}
                      </Button>
                      <Button
                        size='sm'
                        variant='outline'
                        className='h-7 gap-1.5 px-2.5 text-xs'
                        onClick={() => setPlayerMode(true)}
                        disabled={
                          (selectedDevice.state || '').replace(
                            'DeviceState.',
                            ''
                          ) === 'BUSY'
                        }
                      >
                        <Play className='size-3.5' />
                        {t('tryRun')}
                      </Button>
                      <div className='flex-1' />
                      <Button
                        size='sm'
                        variant='outline'
                        className='h-7 gap-1.5 px-2.5 text-xs'
                        onClick={() => setStepPickerOpen(true)}
                      >
                        <Plus className='size-3.5' />
                        {t('multiControl.openPicker')}
                      </Button>
                    </div>
                  ) : undefined
                }
                primaryMirror={
                  <ControlRecordMirror
                    device={selectedDevice}
                    logLines={device.logs[selectedDevice.serial] ?? []}
                    mode={device.mode}
                    wsSend={mirrorWsSend}
                    onToggleMode={record.handleToggleMode}
                    onRestart={record.handleRestart}
                    onTap={mirrorOnTap}
                    onSwipe={mirrorOnSwipe}
                    highlightBounds={highlightBounds}
                    hideControls={mirrorInputLocked.hideControls}
                    hideDeviceFunctions={mirrorInputLocked.hideControls}
                    readOnlyPreview={mirrorInputLocked.readOnlyPreview}
                    busyBanner={mirrorBusyBanner}
                    mirrorSize={multiFocusMode ? 'multiFocus' : 'multiCompact'}
                  />
                }
                devices={selectedMultiFollowerDevices}
                wsMode={device.mode}
                wsSend={mirrorWsSend}
                onPromote={promoteMultiFollower}
              />
            ) : (
              <div className='flex min-h-0 flex-1 flex-col items-center justify-center overflow-hidden'>
                <ControlRecordMirror
                  device={selectedDevice}
                  logLines={device.logs[selectedDevice.serial] ?? []}
                  mode={device.mode}
                  wsSend={mirrorWsSend}
                  onToggleMode={record.handleToggleMode}
                  onRestart={record.handleRestart}
                  onTap={mirrorOnTap}
                  onSwipe={mirrorOnSwipe}
                  highlightBounds={highlightBounds}
                  hideControls={mirrorInputLocked.hideControls}
                  hideDeviceFunctions={mirrorInputLocked.hideControls}
                  readOnlyPreview={mirrorInputLocked.readOnlyPreview}
                  busyBanner={mirrorBusyBanner}
                />
              </div>
            )
          ) : (
            <div className='flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center'>
              <MirrorPhonePlaceholder />
              <p className='text-xs text-muted-foreground'>
                Chọn thiết bị từ thanh trên
              </p>
            </div>
          )}
        </div>

        {/* ── COL 3: Recording / scenario editor ───────────────────────── */}
        {showEditorPanel ? (
          <div className='flex min-h-0 min-w-[min(100%,480px)] flex-1 flex-col overflow-hidden border-l border-border/60'>
          {playerMode && selectedDevice ? (
            /* Player mode — fill column; list scrolls inside ScenarioPlayer */
            <div className='flex min-h-0 flex-1 flex-col overflow-hidden p-4'>
              <ScenarioPlayer
                serial={selectedDevice.serial}
                onClose={() =>
                  guardWhilePreviewActive(() => setPlayerMode(false))
                }
                onPlayingChange={handlePlayerPlayingChange}
                registerStop={registerPlayerStop}
                preloadedSteps={
                  steps.items.length > 0 ? (steps.items as any[]) : undefined
                }
                preloadedName={save.editingContext?.name}
                preloadedVariables={scenarioVariables}
                preloadedScenarioId={activeScenarioId}
                preloadedScenarioDeviceVars={inlineScenarioDeviceVars}
                preloadedAccountGroupId={
                  saveAccountGroupId ||
                  save.editingContext?.accountGroupId ||
                  null
                }
                deviceBusy={
                  (selectedDevice.state || '').replace('DeviceState.', '') ===
                  'BUSY'
                }
              />
            </div>
          ) : (
            <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
              {/* Selector pick banner */}
              {selectorPickTarget && (
                <div className='flex shrink-0 items-center gap-2 border-b border-amber-400/30 bg-amber-50/80 px-4 py-2 dark:bg-amber-950/20'>
                  <Crosshair className='size-3.5 shrink-0 text-amber-600' />
                  <p className='flex-1 text-[11px] text-amber-800 dark:text-amber-300'>
                    {t('pickSelectorBanner')}
                  </p>
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
                    CHẠM TỌA ĐỘ — chạm một điểm trên mirror (cột điện thoại).
                    Esc hoặc Huỷ để thoát.
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
                    Vuốt trên mirror để lấy đoạn (điểm đầu → cuối). Esc hoặc Huỷ
                    để thoát.
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
                    FLOW — chạm phần tử trên mirror để gán selector cho node
                    đang chọn (cần XML cây bên trái). Esc để hủy.
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
              <div className='flex shrink-0 items-center gap-1 border-b border-border/40 bg-muted/20 px-2 py-2'>
                {hasMultiFollowers && stepPickerOpen ? (
                  <Button
                    type='button'
                    size='sm'
                    variant='ghost'
                    className='h-7 shrink-0 gap-1 px-2 text-xs text-muted-foreground'
                    onClick={() => setStepPickerOpen(false)}
                    title={t('multiControl.closePicker')}
                  >
                    <ChevronRight className='size-3.5' />
                  </Button>
                ) : null}
                <div className='flex min-w-0 max-w-full flex-1 flex-nowrap items-center gap-1.5 overflow-x-auto whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'>
                  {record.pollingXml && (
                    <RefreshCw
                      size={12}
                      className='animate-spin text-red-500/80'
                    />
                  )}
                  <Button
                    size='sm'
                    variant={record.recording ? 'destructive' : 'default'}
                    className='h-7 shrink-0 gap-1.5 px-2.5 text-xs'
                    onClick={() => void record.toggleRecording()}
                    disabled={!selectedDevice}
                  >
                    {record.recording ? (
                      <Square className='size-3.5' />
                    ) : (
                      <Circle className='size-3.5 fill-current' />
                    )}
                    {record.recording
                      ? t('stopRecording')
                      : t('startRecording')}
                  </Button>
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-7 shrink-0 gap-1.5 px-2.5 text-xs'
                    onClick={() => setPlayerMode(true)}
                    disabled={
                      !selectedDevice ||
                      (selectedDevice.state || '').replace(
                        'DeviceState.',
                        ''
                      ) === 'BUSY'
                    }
                    title={
                      selectedDevice &&
                      (selectedDevice.state || '').replace(
                        'DeviceState.',
                        ''
                      ) === 'BUSY'
                        ? 'Thiết bị đang chạy campaign — không cho chạy thử'
                        : undefined
                    }
                  >
                    <Play className='size-3.5' />
                    {t('tryRun')}
                  </Button>
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <Button
                        size='sm'
                        variant='ghost'
                        className='h-7 w-7 shrink-0 p-0'
                        onClick={() => setJsonDialogOpen(true)}
                        disabled={steps.items.length === 0}
                      >
                        <Code2 className='size-3.5' />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side='bottom' className='text-xs'>
                      Xem JSON
                    </TooltipContent>
                  </Tooltip>
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-7 shrink-0 gap-1.5 px-2.5 text-xs'
                    onClick={() => {
                      if (save.templateContext) {
                        save.saveToTemplate(scenarioVariables);
                        return;
                      }
                      if (savingOrgScenario) {
                        void handleSaveOrgScenario();
                        return;
                      }
                      steps.openSave();
                    }}
                    disabled={
                      steps.items.length === 0 ||
                      !canSaveWork ||
                      save.savingTemplate ||
                      saveOrgBodyMutation.isPending
                    }
                    title={
                      !canSaveWork
                        ? safeReadOnly
                          ? 'Safe mode: không cho lưu'
                          : undefined
                        : undefined
                    }
                  >
                    <Save className='size-3.5' />
                    {save.templateContext
                      ? save.savingTemplate
                        ? t('templateSaving')
                        : t('templateSave')
                      : savingOrgScenario
                        ? saveOrgBodyMutation.isPending
                          ? 'Đang lưu…'
                          : 'Lưu'
                        : 'Lưu'}
                  </Button>
                  <Tooltip delayDuration={400}>
                    <TooltipTrigger asChild>
                      <Button
                        size='sm'
                        variant='outline'
                        onClick={() => setVarDialogOpen(true)}
                        className={cn(
                          'h-7 shrink-0 gap-1.5 px-2.5 text-xs',
                          Object.keys(scenarioVariables).length > 0 &&
                            'border-primary/40 bg-primary/10 text-primary hover:bg-primary/20'
                        )}
                      >
                        <SlidersHorizontal className='size-3.5' />
                        Biến
                        {Object.keys(scenarioVariables).length > 0 && (
                          <span className='rounded-full bg-primary/20 px-1.5 text-[10px] font-bold'>
                            {Object.keys(scenarioVariables).length}
                          </span>
                        )}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side='bottom' className='text-xs'>
                      Chỉnh biến — giá trị thay thế cho {'${VAR}'} khi chạy thử
                      bước
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={400}>
                    <TooltipTrigger asChild>
                      <Button
                        size='sm'
                        variant='outline'
                        onClick={() => setDeviceVarDialogOpen(true)}
                        disabled={!activeCampaignId || !selectedDeviceId}
                        className={cn(
                          'h-7 shrink-0 gap-1.5 px-2.5 text-xs',
                          hasEnabledDeviceVars &&
                            activeCampaignId &&
                            selectedDeviceId
                            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-300'
                            : ''
                        )}
                      >
                        <SlidersHorizontal className='size-3.5' />
                        Biến thiết bị
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side='bottom' className='text-xs'>
                      {!activeCampaignId
                        ? 'Mở trong ngữ cảnh chiến dịch để thiết lập'
                        : !selectedScenarioDeviceId
                          ? 'Chọn thiết bị trước'
                          : `Đang gắn cho: ${selectedDeviceLabel}`}
                    </TooltipContent>
                  </Tooltip>
                  <Tooltip delayDuration={400}>
                    <TooltipTrigger asChild>
                      <Button
                        size='sm'
                        variant='ghost'
                        className='h-7 w-7 shrink-0 p-0'
                      >
                        <HelpCircle className='size-3.5' />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side='bottom' className='max-w-xs text-xs'>
                      {t('tooltipScenarioSection')}
                    </TooltipContent>
                  </Tooltip>
                </div>
              </div>

              {/* Flow editor */}
              <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
                <div className='min-h-0 flex-1 overflow-y-auto px-3 pb-2'>
                {steps.items.length === 0 ? (
                  <EmptyNodePicker
                    templates={templatesQuery.data}
                    templatesLoading={templatesQuery.isLoading}
                    onPreviewTemplate={(tpl) => {
                      setScenarioVariables((prev) =>
                        mergeTemplateVariablesIntoEditor(prev, tpl.variables)
                      );
                      setPreviewTemplate(tpl);
                    }}
                    onAddFlow={steps.addFlow}
                    onAddWait={steps.addWait}
                  />
                ) : showFlowUi ? (
                  <div className='flex h-full min-h-[240px] flex-col overflow-hidden rounded-lg border border-border/50 bg-background lg:flex-row'>
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
                            flowSelectedFgId &&
                            flowDetailStep &&
                            isSelectorPickableStep(flowDetailStep)
                              ? () => {
                                  setFlowSelectorPickFgId(flowSelectedFgId);
                                  setSelectorPickTarget(null);
                                  setFlowCoordPick(null);
                                  setCoordinatePickTarget(null);
                                  toast.info(
                                    'Chạm phần tử trên mirror để gán selector'
                                  );
                                }
                              : undefined
                          }
                          onRequestPickTapCoords={
                            flowSelectedFgId
                              ? () => {
                                  setFlowCoordPick({
                                    fgId: flowSelectedFgId,
                                    kind: 'tap'
                                  });
                                  setCoordinatePickTarget(null);
                                  setFlowSelectorPickFgId(null);
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
                                  setCoordinatePickTarget(null);
                                  setFlowSelectorPickFgId(null);
                                  toast.info(
                                    'Vuốt trên mirror để gán swipe_ratio'
                                  );
                                }
                              : undefined
                          }
                        />
                      ) : (
                        <div className='space-y-2 p-3 text-[11px] leading-relaxed text-muted-foreground'>
                          <p>
                            Bấm <strong>con trỏ</strong> trên node → chỉnh chi
                            tiết; <strong>play</strong> chạy một bước. Cây XML +
                            thêm bước từ selector vẫn dùng cột trái như chế độ
                            danh sách.
                          </p>
                          <p className='rounded-md border border-border/80 bg-muted/30 px-2 py-1.5 text-[10px]'>
                            <strong>Không có “kéo dây” tự do</strong> — Flowgram
                            (fixed-layout) tự vẽ nối theo thứ tự dọc và nhánh
                            if/loop/random. Đổi thứ tự bằng{' '}
                            <strong>kéo thả node</strong>. Muốn nối dây tùy ý
                            cần editor dạng graph tự do (vd. React Flow), không
                            nằm trong thư viện hiện tại.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className='flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border/50 bg-background'>
                    {selectedDevice &&
                      Object.values(stepRunStates).some(
                        (st) => st === 'running'
                      ) && (
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
                        onChange={handleFlowStepsChange}
                        maxHeight='calc(100vh - 170px)'
                        selectorPickTarget={selectorPickTarget}
                        onSelectorPickTargetChange={setSelectorPickTarget}
                        coordinatePickTarget={coordinatePickTarget}
                        onCoordinatePickTargetChange={
                          setCoordinatePickTargetSafe
                        }
                        onRunStep={selectedDevice ? handleRunStep : undefined}
                        onStopInlineRun={
                          selectedDevice ? handleStopInlineRun : undefined
                        }
                        stepRunStates={stepRunStates}
                      />
                    </div>
                  </div>
                )}
                </div>
              </div>
            </div>
          )}
          </div>
        ) : null}
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
          <p className='-mt-1 text-[12px] text-muted-foreground'>
            Nhập URL APK công khai. atx-agent trên thiết bị sẽ tải và cài đặt tự
            động.
          </p>
          <div className='flex gap-2'>
            <Input
              placeholder='https://example.com/app.apk'
              value={installUrl}
              onChange={(e) => setInstallUrl(e.target.value)}
              className='h-8 font-mono text-xs'
            />
            <Button
              size='sm'
              className='h-8 shrink-0'
              disabled={!installUrl.trim() || !selectedDevice}
              onClick={() => {
                if (!selectedDevice || !installUrl.trim()) return;
                record.wsSend({
                  type: 'install',
                  serial: selectedDevice.serial,
                  url: installUrl.trim()
                });
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
        <DialogContent className='!grid max-h-[min(85dvh,720px)] max-w-2xl grid-rows-[auto_minmax(0,1fr)] gap-3 overflow-hidden'>
          <DialogHeader className='shrink-0 space-y-1.5'>
            <DialogTitle className='flex flex-wrap items-center gap-2 text-base'>
              <SlidersHorizontal className='size-4 shrink-0' />
              {tVar('title')}
              {Object.keys(scenarioVariables).length > 0 ? (
                <Badge variant='secondary' className='h-6 text-[11px] font-normal'>
                  {tVar('variableCount', {
                    count: Object.keys(scenarioVariables).length
                  })}
                </Badge>
              ) : null}
            </DialogTitle>
            <DialogDescription className='text-xs'>
              {tVar('headerSubtitleLead')}{' '}
              <code className='rounded bg-muted/80 px-1 py-0.5 font-mono text-[11px] text-foreground'>
                {'${VAR}'}
              </code>{' '}
              {tVar('headerSubtitleTrail')}
            </DialogDescription>
          </DialogHeader>
          <div className='min-h-0 overflow-y-auto overscroll-y-contain pr-1 [-webkit-overflow-scrolling:touch]'>
            <VariableEditor
              variables={scenarioVariables}
              onChange={setScenarioVariables}
            />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={deviceVarDialogOpen} onOpenChange={setDeviceVarDialogOpen}>
        <DialogContent className='!grid max-h-[min(88dvh,760px)] !w-[min(94vw,980px)] !max-w-[980px] grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-4 overflow-hidden'>
          <DialogHeader className='shrink-0'>
            <DialogTitle className='flex items-center gap-2 text-base'>
              <SlidersHorizontal className='size-4' />
              {tDv('title')}
            </DialogTitle>
          </DialogHeader>
          <p className='-mt-1 shrink-0 text-[12px] text-muted-foreground'>
            {tDvDlg('scopeHint')}
          </p>
          <div className='shrink-0 rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground'>
            {tDvDlg('instructions')}
          </div>
          <div className='min-h-0 overflow-y-auto overscroll-y-contain pr-1 [-webkit-overflow-scrolling:touch]'>
            {scenarioDeviceVarsQuery.isLoading && activeScenarioId ? (
              <p className='text-xs text-muted-foreground'>
                {tDvDlg('loadingVars')}
              </p>
            ) : (campaignDevicesQuery.data ?? []).length === 0 ? (
              <p className='text-xs text-muted-foreground'>
                {tDvDlg('noDevicesInCampaign')}
              </p>
            ) : (
              <div className='grid min-h-[430px] grid-cols-[260px_1fr] divide-x rounded-md border'>
                <div className='min-h-0 overflow-y-auto p-2'>
                  {(campaignDevicesQuery.data ?? []).map((d) => {
                    const active = selectedScenarioDeviceId === d.id;
                    const enabled = deviceVarEnabledByDevice[d.id] === true;
                    return (
                      <button
                        key={d.id}
                        type='button'
                        className={cn(
                          'mb-1 flex w-full items-center gap-2 rounded border border-transparent px-2 py-2 text-left text-xs hover:bg-muted/60',
                          active && 'border-primary/30 bg-primary/[0.06]'
                        )}
                        onClick={() => setSelectedScenarioDeviceId(d.id)}
                      >
                        <span className='min-w-0 flex-1'>
                          <span className='block truncate font-medium'>
                            {d.name || d.serial}
                          </span>
                          <span className='block truncate font-mono text-[10px] text-muted-foreground'>
                            {d.serial}
                          </span>
                        </span>
                        <Badge
                          variant={enabled ? 'default' : 'secondary'}
                          className='shrink-0 text-[10px]'
                        >
                          {enabled
                            ? tDvDlg('badgePerDevice')
                            : tDvDlg('badgeGlobal')}
                        </Badge>
                      </button>
                    );
                  })}
                </div>
                <div className='min-h-0 p-4'>
                  <DeviceVarsJsonPanel
                    enabled={currentDeviceVarsEnabled}
                    onEnabledChange={setCurrentDeviceVarsEnabled}
                    draft={currentDeviceVarJsonDraft}
                    onDraftChange={setCurrentDeviceVarJsonDraft}
                    jsonError={currentDeviceVarJsonError}
                    deviceLabel={selectedDeviceLabel}
                    baseVariables={scenarioVariables}
                    globalVariablesPreview={deviceVarGlobalPreview}
                    editorClassName='min-h-[330px]'
                    emptyClassName='min-h-[330px]'
                  />
                </div>
              </div>
            )}
          </div>
          <div className='flex justify-end gap-2'>
            <Button
              variant='outline'
              size='sm'
              onClick={() => setDeviceVarDialogOpen(false)}
            >
              {tModal('cancel')}
            </Button>
            <Button
              size='sm'
              onClick={() => {
                if (activeScenarioId) {
                  saveScenarioDeviceVarsMutation.mutate(deviceVarJsonDrafts);
                  return;
                }
                const parsedDrafts: Record<string, Record<string, any>> = {};
                for (const d of campaignDevicesQuery.data ?? []) {
                  if (deviceVarEnabledByDevice[d.id] !== true) {
                    parsedDrafts[d.id] = {};
                    continue;
                  }
                  try {
                    parsedDrafts[d.id] = parseDeviceVarsJson(
                      deviceVarJsonDrafts[d.id] ?? '{}',
                      deviceVarsParseMsgs
                    );
                  } catch {
                    toast.error(tDv('invalidAtDevice', { serial: d.serial }));
                    return;
                  }
                }
                setPendingScenarioDeviceVarsDraftMap(parsedDrafts);
                setDeviceVarDialogOpen(false);
                toast.info(tDvDlg('saveDraftToast'));
              }}
              disabled={
                saveScenarioDeviceVarsMutation.isPending ||
                (campaignDevicesQuery.data ?? []).length === 0 ||
                !!currentDeviceVarJsonError
              }
            >
              {saveScenarioDeviceVarsMutation.isPending
                ? tDvDlg('saveLoading')
                : activeScenarioId
                  ? tDvDlg('save')
                  : tDvDlg('saveDraft')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── JSON viewer dialog ──────────────────────────────────────────────── */}
      <Dialog open={jsonDialogOpen} onOpenChange={setJsonDialogOpen}>
        <DialogContent className='max-h-[min(90dvh,920px)] max-w-2xl grid-rows-[auto_minmax(0,1fr)] gap-4 overflow-hidden'>
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
              <Copy className='size-3' /> Sao chép
            </Button>
            <pre className='min-h-0 max-w-full flex-1 overflow-x-auto overflow-y-auto overscroll-y-contain rounded-md border border-border bg-muted/40 p-3 pb-10 pr-14 pt-9 font-mono text-[11px] leading-relaxed'>
              {JSON.stringify(
                steps.items.map((s: any) => {
                  const { _id, ...rest } = s;
                  void _id;
                  return rest;
                }),
                null,
                2
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
        <DialogContent className='!grid max-h-[min(85dvh,720px)] max-w-lg grid-rows-[auto_minmax(0,1fr)] gap-4 overflow-hidden'>
          <DialogHeader className='shrink-0'>
            <DialogTitle>
              {save.selectedCampaignId
                ? t('chooseScenarioTitle', {
                    name:
                      save.campaigns.find(
                        (c) => c.id === save.selectedCampaignId
                      )?.name ?? ''
                  })
                : t('saveScenarioTitle')}
            </DialogTitle>
          </DialogHeader>

          <div className='min-h-0 overflow-y-auto overscroll-y-contain pr-1 [-webkit-overflow-scrolling:touch]'>
            {!save.selectedCampaignId && !save.editingContext ? (
              <div className='space-y-2'>
                <p className='text-xs text-muted-foreground'>
                  {t('stepsRecorded', { count: steps.items.length })}
                </p>
                {save.campaigns.length === 0 ? (
                  <p className='text-sm text-muted-foreground'>
                    {t('noCampaign')}
                  </p>
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

                {/* Account-group picker — bound to the scenario on save. Empty
                  means "do not use a pool; fall back to the device's primary
                  account" (legacy behavior). */}
                <div className='space-y-1 rounded-md border border-border/60 bg-muted/30 p-2'>
                  <p className='text-[11px] font-medium text-foreground/80'>
                    {t('accountGroupLabel')}
                  </p>
                  <Select
                    value={saveAccountGroupId || '_none'}
                    onValueChange={(v) =>
                      setSaveAccountGroupId(v === '_none' ? '' : v)
                    }
                  >
                    <SelectTrigger className='h-8 text-xs'>
                      <SelectValue />
                    </SelectTrigger>
                    {/* Dialog renders at z=10000; bump SelectContent above it so
                      the dropdown is not clipped/hidden behind the modal. */}
                    <SelectContent className='z-[10010]'>
                      <SelectItem value='_none' className='text-xs'>
                        {t('accountGroupNone')}
                      </SelectItem>
                      {accountGroups.map((g) => (
                        <SelectItem key={g.id} value={g.id} className='text-xs'>
                          {g.name} · {g.platform} · {g.member_count}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {saveAccountGroupId &&
                    (() => {
                      const picked = accountGroups.find(
                        (g) => g.id === saveAccountGroupId
                      );
                      if (!picked) return null;
                      return (
                        <p className='text-[10px] text-muted-foreground'>
                          {t('accountGroupCaption', {
                            count: picked.member_count,
                            strategy: picked.rotation_strategy
                          })}
                        </p>
                      );
                    })()}
                  <p className='text-[10px] text-muted-foreground'>
                    {t('accountGroupHint')}
                  </p>
                </div>

                <Button
                  variant='default'
                  className='w-full justify-start gap-2'
                  onClick={() =>
                    save.saveAsNew(
                      save.selectedCampaignId!,
                      scenarioVariables,
                      saveAccountGroupId || null
                    )
                  }
                  disabled={save.saving !== null}
                >
                  <Plus size={13} />
                  {save.saving === 'new'
                    ? t('creating')
                    : t('createNewScenario')}
                </Button>
                {save.campaignScenarios.length > 0 && (
                  <>
                    <p className='pt-1 text-xs text-muted-foreground'>
                      {t('overwriteExisting')}
                    </p>
                    {save.campaignScenarios.map((s) => (
                      <Button
                        key={s.id}
                        variant='outline'
                        className='h-auto w-full flex-col items-start justify-start py-2 text-left'
                        onClick={() =>
                          save.saveTo(
                            save.selectedCampaignId!,
                            s.id,
                            scenarioVariables,
                            saveAccountGroupId || null
                          )
                        }
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
          </div>
        </DialogContent>
      </Dialog>

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
                stopPlayerRef.current?.();
                handleStopInlineRun();
                if (action) action();
              }}
            >
              {t('exitConfirmConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Template preview dialog — opened from the empty-state picker. */}
      <Dialog
        open={previewTemplate !== null}
        onOpenChange={(o) => {
          if (!o) setPreviewTemplate(null);
        }}
      >
        <DialogContent className='max-w-xl'>
          <DialogHeader>
            <DialogTitle className='flex items-center gap-2'>
              <List className='size-4 text-emerald-600' />
              <span className='truncate'>{previewTemplate?.name ?? ''}</span>
              {previewTemplate?.is_builtin && (
                <Badge
                  variant='secondary'
                  className='h-5 px-1.5 text-[10px] font-semibold uppercase tracking-wide'
                >
                  {t('emptyNodePicker.templateBuiltinBadge')}
                </Badge>
              )}
            </DialogTitle>
          </DialogHeader>
          {previewTemplate && (
            <div className='space-y-3'>
              {previewTemplate.description && (
                <p className='text-xs leading-relaxed text-muted-foreground'>
                  {previewTemplate.description}
                </p>
              )}
              <div className='flex items-center gap-2 text-xs text-muted-foreground'>
                <span className='font-semibold text-foreground/80'>
                  {t('emptyNodePicker.templateStepCount', {
                    count: Array.isArray(previewTemplate.steps)
                      ? previewTemplate.steps.length
                      : 0
                  })}
                </span>
                {previewTemplate.category && (
                  <span>· {previewTemplate.category}</span>
                )}
              </div>
              <div className='max-h-[50vh] overflow-y-auto rounded-md border border-border/60 bg-muted/30 p-2'>
                {Array.isArray(previewTemplate.steps) &&
                previewTemplate.steps.length > 0 ? (
                  <ol className='space-y-1'>
                    {previewTemplate.steps.map((step: any, i: number) => {
                      const type =
                        typeof step?.type === 'string' ? step.type : 'unknown';
                      return (
                        <li
                          key={i}
                          className='flex items-start gap-2 rounded border border-border/40 bg-background px-2 py-1.5 text-xs'
                        >
                          <span className='flex h-5 w-5 shrink-0 items-center justify-center rounded bg-indigo-50 text-indigo-600 ring-1 ring-inset ring-indigo-100'>
                            <StepIcon type={type as any} size={12} />
                          </span>
                          <span className='min-w-0 flex-1'>
                            <span className='mr-1 text-[10px] font-semibold uppercase text-muted-foreground'>
                              #{i + 1}
                            </span>
                            <span className='font-medium text-foreground/90'>
                              {type}
                            </span>
                            {(step?.name || step?.label) && (
                              <span className='ml-1 text-muted-foreground'>
                                · {String(step.name || step.label)}
                              </span>
                            )}
                          </span>
                        </li>
                      );
                    })}
                  </ol>
                ) : (
                  <p className='py-4 text-center text-xs text-muted-foreground'>
                    {t('emptyNodePicker.templateNoSteps')}
                  </p>
                )}
              </div>
              <div className='flex items-center justify-end gap-2 pt-1'>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => setPreviewTemplate(null)}
                >
                  {t('emptyNodePicker.templateCancel')}
                </Button>
                <Button
                  size='sm'
                  onClick={() => {
                    const tpl = previewTemplate;
                    if (!tpl) return;
                    setScenarioVariables((prev) =>
                      mergeTemplateVariablesIntoEditor(prev, tpl.variables)
                    );
                    const n = steps.appendSteps(
                      Array.isArray(tpl.steps) ? tpl.steps : []
                    );
                    setPreviewTemplate(null);
                    if (n > 0) {
                      toast.success(
                        t('emptyNodePicker.templateLoaded', {
                          name: tpl.name,
                          count: n
                        })
                      );
                    } else {
                      toast.error(t('emptyNodePicker.templateEmptySteps'));
                    }
                  }}
                  disabled={
                    !Array.isArray(previewTemplate.steps) ||
                    previewTemplate.steps.length === 0
                  }
                >
                  {t('emptyNodePicker.templateAppend')}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
