'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ScenarioPlayer } from './control-record/scenario-player';
import { packageFromCurrentApp, type DeviceOpsConfig } from './device-ops-rail';
import { ControlRecordTopBar } from './control-record/control-record-top-bar';
import { ControlRecordHierarchyPanel } from './control-record/control-record-hierarchy-panel';
import { ControlRecordMirrorPanel } from './control-record/control-record-mirror-panel';
import { ControlRecordEditorToolbar } from './control-record/control-record-editor-toolbar';
import {
  ControlRecordDeviceVarsDialog,
  ControlRecordExitConfirmDialog,
  ControlRecordJsonDialog,
  ControlRecordRecoveryDialog,
  ControlRecordTakeoverConfirmDialog,
  ControlRecordTemplatePreviewDialog,
  ControlRecordVariablesDialog
} from './control-record/control-record-dialogs';
import { SafeModeBanner } from '@/features/core/components/safe-mode-banner';
import { useSafeMode } from '@/features/core/services/use-safe-mode';
import { Button } from '@/components/ui/button';
import {
  formatDeviceVarsJson,
  mergeCampaignScenarioVariables,
  parseDeviceVarsJson,
  splitDeviceOverridesFromMerged
} from '@/components/device-vars-json-panel';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Square,
  Plus,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Crosshair,
  MousePointerClick,
  Move,
  AlertCircle
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

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { normalizeInternalAppPath } from '@/lib/i18n-path';
import { useSaveOrgScenarioBody } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { buildOrgScenarioBodyPayload } from '@/features/org-scenarios/lib/build-org-scenario-body';
import { isGraphOrgScenario } from '@/features/org-scenarios/lib/campaign-scenario-eligibility';
import { validateScenarioStepsForApi } from '@/features/campaigns/utils/validate-scenario-steps-for-api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useRouter } from '@/i18n/navigation';
import {
  syncSavedScenarioCaches,
  useControlRecord
} from '../hooks/use-control-record';
import { useControlRecordChunkReloadGuard } from '../hooks/use-control-record-chunk-reload';
import { useControlRecordMultiDevice } from '../hooks/use-control-record-multi-device';
import { useTabNetworkActive } from '../hooks/use-tab-network-active';
import {
  campaignPerDeviceOverrides,
  campaignVariables,
  campaignsApi,
  scenariosApi,
  type ScenarioDeviceVariablesOut
} from '@/features/campaigns/services/api';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import type { ScenarioTemplateOut } from '@/features/scenario-templates/services/api';
import { useAccountGroups } from '@/features/account-groups/hooks/use-account-groups';
import { EmptyNodePicker } from './control-record/empty-node-picker';
import {
  applySelectorToSteps,
  type SelectorPickTarget
} from '@/features/campaigns/components/flow-editor/selector-pick';
import {
  applyTapPointToSteps,
  applySwipeSegmentToSteps,
  type CoordinatePickTarget
} from '@/features/campaigns/components/flow-editor/coordinate-pick';
import { FlowEditor } from '@/features/campaigns/components/flow-editor/flow-editor';
import { deriveNestedInlineRunStates } from '@/features/campaigns/components/flow-editor/inline-run-key';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import {
  findSelectorForTreeNode,
  findSelectorInXml,
  hashXml,
  listSelectorCandidatesInXml,
  type XmlSelectorPick
} from '../utils/control-record-xml';
import type { ScenarioSelectorShape } from '../lib/scenario-selector-step';
import { buildSelectorStep } from '../lib/scenario-selector-step';
import { parseHierarchyTree, findNodeIdAtRatio } from '../utils/hierarchy-tree';
import {
  previewScenarioStream,
  cancelPreviewStream,
  interruptDevice,
  takeOverDevice,
  runAgentShell
} from '../services/api';
import {
  createPreviewRunSession,
  type ActivePreviewTrace
} from '../lib/preview-run-session';
import { devicesApi } from '../services/manage-api';
import { useTranslations } from 'next-intl';
import type { FixedLayoutPluginContext } from '@flowgram.ai/fixed-layout-editor';
import { StepDetailPanel } from '@/features/campaigns/components/flow-editor/step-detail-panel';
import type { RecoveryPolicy } from '@/features/campaigns/types';
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
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  collectDeclaredDeviceVarKeys,
  flattenVarDefs,
  mergeDeclaredDeviceVarKeys,
  mergeTemplateVariablesIntoEditor
} from '../lib/control-record-variables';
import {
  deviceSerialMatches,
  isManualControlBlockedByAutomation,
  shouldShowControlRecordNoDeviceBanner
} from '../lib/control-record-device-state';
import {
  prepareInlinePreviewStep,
  preparePreviewStepPayload
} from '../lib/control-record-preview-steps';
import { syncCampaignDetailCaches } from '../lib/control-record-cache';

const MAX_MULTI_CONTROL_DEVICES = 20;
const MAX_MULTI_FOLLOWER_DEVICES = MAX_MULTI_CONTROL_DEVICES - 1;

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
  const tDeviceOps = useTranslations('devicesControlRecord.deviceOps');
  const tOrg = useTranslations('orgScenariosFeature.detail');
  const queryClient = useQueryClient();
  const tDv = useTranslations('components.deviceVarsJson');
  const tDvDlg = useTranslations('devicesControlRecord.deviceVarsDialog');
  const tModal = useTranslations('components.modal');
  const tVar = useTranslations('components.variableEditor');
  const tRecovery = useTranslations('campaignsFeature.recoveryPolicy');
  const router = useRouter();
  useControlRecordChunkReloadGuard();

  const { error, device, record, steps, save, hierarchy, selector } =
    useControlRecord(
      initialSerial,
      initialCampaignId,
      initialScenarioId,
      initialTemplateId,
      initialOrgScenarioId
    );
  const {
    wsSend: recordWsSend,
    handleToggleMode: recordHandleToggleMode,
    handleRestart: recordHandleRestart
  } = record;
  const hierarchyXml = hierarchy.xml;
  const hierarchyLoading = hierarchy.loading;
  const hierarchyAutoRefresh = hierarchy.autoRefresh;
  const setHierarchyAutoRefresh = hierarchy.setAutoRefresh;
  const refreshHierarchy = hierarchy.refresh;
  const setHierarchyPaused = hierarchy.setPaused;
  const pickTargetPackage = useMemo(
    () =>
      packageFromCurrentApp(device.selectedDevice?.current_app) || undefined,
    [device.selectedDevice?.current_app]
  );
  const hierarchyPickOptions = useMemo(() => {
    const w = device.selectedDevice?.screen_width ?? 0;
    const h = device.selectedDevice?.screen_height ?? 0;
    return {
      targetPackage: pickTargetPackage,
      screenDims: w > 0 && h > 0 ? ({ dw: w, dh: h } as const) : undefined
    };
  }, [
    device.selectedDevice?.screen_width,
    device.selectedDevice?.screen_height,
    pickTargetPackage
  ]);
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
    const back = normalizeInternalAppPath(returnTo, ROUTES.ORG_SCENARIOS.ROOT);
    toast.error(tOrg('sequenceOnlyNoGraph'));
    router.replace(back);
  }, [save.orgScenarioContext, returnTo, router, tOrg]);

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
    const body = buildOrgScenarioBodyPayload(
      flushPendingFlowDetailStep(),
      syncDeviceVarKeysIntoScenarioVariables()
    );
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
          router.push(
            normalizeInternalAppPath(returnTo, ROUTES.ORG_SCENARIOS.ROOT)
          );
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
  // Candidate cycling: when several elements overlap the same tap point
  // (common on Facebook), re-tapping the spot or using prev/next cycles them.
  const pickCandidatesRef = useRef<XmlSelectorPick[]>([]);
  const pickCycleIndexRef = useRef(0);
  const lastPickSpotRef = useRef<{ rx: number; ry: number } | null>(null);
  const [pickCycle, setPickCycle] = useState<{
    index: number;
    total: number;
  } | null>(null);
  const [pickSelectorWarning, setPickSelectorWarning] = useState<string | null>(
    null
  );
  const [coordinatePickTarget, setCoordinatePickTarget] =
    useState<CoordinatePickTarget | null>(null);
  const mirrorColRef = useRef<HTMLDivElement>(null);
  const [flowMode, setFlowMode] = useState(false);
  useEffect(() => {
    if (!ENABLE_FLOWGRAM_CONTROL_UI) setFlowMode(false);
  }, []);
  const showFlowUi = ENABLE_FLOWGRAM_CONTROL_UI && flowMode;
  const [optimisticTakeoverSerials, setOptimisticTakeoverSerials] = useState<
    Set<string>
  >(() => new Set());
  const liveConnectedDevicesForControl = useMemo(
    () =>
      device.connectedDevices.map((d) =>
        optimisticTakeoverSerials.has(d.serial)
          ? { ...d, manual_takeover_active: true }
          : d
      ),
    [device.connectedDevices, optimisticTakeoverSerials]
  );
  const [connectedDevicesForControl, setConnectedDevicesForControl] = useState(
    liveConnectedDevicesForControl
  );
  useEffect(() => {
    if (liveConnectedDevicesForControl.length > 0) {
      setConnectedDevicesForControl(liveConnectedDevicesForControl);
    }
  }, [liveConnectedDevicesForControl]);

  const rawSelectedDeviceForControl = useMemo(
    () =>
      device.selectedDevice &&
      optimisticTakeoverSerials.has(device.selectedDevice.serial)
        ? { ...device.selectedDevice, manual_takeover_active: true }
        : device.selectedDevice,
    [device.selectedDevice, optimisticTakeoverSerials]
  );
  const selectedDeviceForControl = useMemo(
    () =>
      rawSelectedDeviceForControl ??
      connectedDevicesForControl.find((d) => d.serial === device.selectedSerial) ??
      connectedDevicesForControl[0] ??
      null,
    [connectedDevicesForControl, device.selectedSerial, rawSelectedDeviceForControl]
  );
  const selectedPrimarySerial = selectedDeviceForControl?.serial ?? null;
  const {
    leftCollapsed,
    setLeftCollapsed,
    multiFollowerSerials,
    setMultiFollowerSerials,
    stepPickerOpen,
    setStepPickerOpen,
    multiFollowerOptions,
    activeMultiSerials,
    selectedMultiFollowerDevices,
    hasMultiFollowers,
    multiFocusMode,
    showEditorPanel,
    treePanelOpen
  } = useControlRecordMultiDevice({
    connectedDevices: connectedDevicesForControl,
    selectedPrimarySerial,
    safeHierarchy,
    playerMode,
    maxFollowers: MAX_MULTI_FOLLOWER_DEVICES
  });
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

  const showTemplatePicker = steps.items.length === 0;
  const templatesQuery = useScenarioTemplates(undefined, {
    enabled: showTemplatePicker
  });
  const [previewTemplate, setPreviewTemplate] =
    useState<ScenarioTemplateOut | null>(null);

  // Account-group picker for the Save dialog. `'_none'` = do not bind.
  // On open, we hydrate from editingContext so a user returning to edit a
  // scenario sees the already-bound group pre-selected.
  const { data: accountGroups = [] } = useAccountGroups(undefined, {
    enabled: save.dialogOpen
  });
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
  stepsItemsRef.current = steps.items;
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
  const deviceVarsHydratedKeyRef = useRef<string | null>(null);
  const deviceVarStateRef = useRef<{
    drafts: Record<string, string>;
    enabledByDevice: Record<string, boolean>;
  }>({ drafts: {}, enabledByDevice: {} });
  const deviceVarUserEditedRef = useRef<Set<string>>(new Set());
  const deviceVarDialogInitRef = useRef(false);
  const [selectedScenarioDeviceId, setSelectedScenarioDeviceId] = useState<
    string | null
  >(null);
  const [jsonDialogOpen, setJsonDialogOpen] = useState(false);

  // Scenario-player running state + stop handle. Used by the Farm back button
  // and device-switch guard to confirm+abort before leaving.
  const [playerPlaying, setPlayerPlaying] = useState(false);
  const stopPlayerRef = useRef<(() => void) | null>(null);
  const [exitConfirm, setExitConfirm] = useState<null | (() => void)>(null);
  const [takeoverDialogOpen, setTakeoverDialogOpen] = useState(false);
  const [takeoverPending, setTakeoverPending] = useState(false);
  const handleTakeControl = useCallback(() => setTakeoverDialogOpen(true), []);

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

  // Hierarchy content changed => stale node bounds/highlight must be cleared.
  // Use normalized hash so volatile bounds/index churn does not re-render the page.
  const hierarchyContentHashRef = useRef<number | null>(null);
  useEffect(() => {
    hierarchyContentHashRef.current = null;
  }, [device.selectedSerial]);
  useEffect(() => {
    const xml = hierarchyXml?.trim();
    if (!xml) return;
    const nextHash = hashXml(xml);
    if (hierarchyContentHashRef.current === nextHash) return;
    hierarchyContentHashRef.current = nextHash;
    setHighlightBounds(null);
    setSelectedNodeId(null);
  }, [hierarchyXml]);

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
      const active = previewSession.takeActiveForCancel();
      const serial = selectedSerialForStopRef.current;
      if (active) {
        cancelPreviewStream(active.serial, active.traceId).catch(
          () => undefined
        );
        interruptDevice(active.serial).catch(() => undefined);
      }
      stepRunAbortRef.current?.abort();
      flowRunLeafAbortRef.current?.abort();
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
    //   1) explicit cancel route sets cancel_event immediately (no polling lag)
    //   2) interrupt also cancels any preview without a captured trace_id
    //   3) abort() closes the SSE fetch after the server has been signalled
    const serial = device.selectedDevice?.serial?.trim();
    const active = previewSession.takeActiveForCancel();
    if (active) {
      cancelPreviewStream(active.serial, active.traceId).catch(() => undefined);
      interruptDevice(active.serial).catch(() => undefined);
    } else if (serial) {
      interruptDevice(serial).catch(() => undefined);
    }
    stepRunAbortRef.current?.abort();
    flowRunLeafAbortRef.current?.abort();
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
  useEffect(() => {
    setHierarchyPaused(previewBlocking);
  }, [setHierarchyPaused, previewBlocking]);
  const stopPreviewIfActive = useCallback(() => {
    if (!playerPlaying && !inlinePreviewRunning && !activePreviewRef.current) {
      return;
    }
    stopPlayerRef.current?.();
    handleStopInlineRun();
  }, [handleStopInlineRun, inlinePreviewRunning, playerPlaying]);

  const deviceSelectValue = useMemo(() => {
    const serial = selectedDeviceForControl?.serial ?? device.selectedSerial;
    if (!serial) return '';
    return connectedDevicesForControl.some((d) => d.serial === serial)
      ? serial
      : '';
  }, [connectedDevicesForControl, device.selectedSerial, selectedDeviceForControl]);

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

  const handlePlayerPlayingChange = useCallback((playing: boolean) => {
    setPlayerPlaying(playing);
  }, []);

  const registerPlayerStop = useCallback((fn: (() => void) | null) => {
    stopPlayerRef.current = fn;
  }, []);

  const handleTakeoverConfirm = useCallback(async () => {
    const serial = device.selectedDevice?.serial?.trim();
    if (!serial || takeoverPending) return;
    setTakeoverPending(true);
    try {
      await takeOverDevice(serial);
      setOptimisticTakeoverSerials((prev) => new Set(prev).add(serial));
      toast.success(t('takeover.success'));
      setTakeoverDialogOpen(false);
    } catch (err) {
      toast.error(
        formatFarmApiError(err, t('takeover.failed')) ?? t('takeover.failed')
      );
    } finally {
      setTakeoverPending(false);
    }
  }, [device.selectedDevice?.serial, takeoverPending, t]);

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
    [device, guardWhilePreviewActive, setMultiFollowerSerials]
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
  deviceVarStateRef.current = {
    drafts: deviceVarJsonDrafts,
    enabledByDevice: deviceVarEnabledByDevice
  };
  const [
    pendingScenarioDeviceVarsDraftMap,
    setPendingScenarioDeviceVarsDraftMap
  ] = useState<Record<string, Record<string, any>> | null>(null);
  const activeCampaignId =
    save.editingContext?.campaignId ??
    (savingOrgScenario ? (initialCampaignId ?? null) : null);
  const activeScenarioId = save.editingContext?.scenarioId ?? null;
  const activeDeviceVarScenarioId = savingOrgScenario ? null : activeScenarioId;
  const [recoveryDialogOpen, setRecoveryDialogOpen] = useState(false);
  const [recoveryPolicy, setRecoveryPolicy] = useState<RecoveryPolicy>({});
  const usesCampaignDeviceOverrides = Boolean(
    activeCampaignId && savingOrgScenario
  );
  const canManageDeviceVars = Boolean(
    activeCampaignId &&
      (activeDeviceVarScenarioId || usesCampaignDeviceOverrides)
  );
  const selectedSerial = selectedDeviceForControl?.serial ?? null;
  const { currentOrg } = useOrganization();
  const controlRecordOrgId = currentOrg?.id ?? null;
  const tabActive = useTabNetworkActive();
  const devicesQuery = useQuery({
    queryKey: ['control-record-device-map', controlRecordOrgId],
    queryFn: devicesApi.list,
    enabled: Boolean(controlRecordOrgId) && tabActive,
    staleTime: 15_000
  });
  const campaignDevicesQuery = useQuery({
    queryKey: ['campaign-devices', activeCampaignId],
    enabled: !!activeCampaignId && tabActive,
    queryFn: () => campaignsApi.getDevices(activeCampaignId!)
  });
  const campaignRecoveryQuery = useQuery({
    queryKey: ['campaign', activeCampaignId, 'recovery-policy'],
    enabled: !!activeCampaignId && tabActive,
    queryFn: () => campaignsApi.get(activeCampaignId!),
    staleTime: 30_000
  });
  useEffect(() => {
    if (!campaignRecoveryQuery.data) return;
    setRecoveryPolicy(
      (campaignRecoveryQuery.data.recovery_policy ?? {}) as RecoveryPolicy
    );
  }, [campaignRecoveryQuery.data]);
  const recoveryPolicyEnabled = Boolean(
    (campaignRecoveryQuery.data?.recovery_policy ?? recoveryPolicy)?.enabled
  );
  const editingRecoveryScenario =
    save.orgScenarioContext?.isRecoveryScenario === true;
  const recoveryReturnTo = normalizeInternalAppPath(returnTo, '');
  const saveRecoveryPolicyMutation = useMutation({
    mutationFn: async (policy: RecoveryPolicy) => {
      if (!activeCampaignId) {
        throw new Error(tRecovery('missingCampaignError'));
      }
      return campaignsApi.patchEntity(activeCampaignId, {
        recovery_policy: policy as Record<string, any>
      });
    },
    onSuccess: () => {
      toast.success(tRecovery('saveSuccess'));
      setRecoveryDialogOpen(false);
      void queryClient.invalidateQueries({
        queryKey: ['campaign', activeCampaignId, 'recovery-policy']
      });
      void queryClient.invalidateQueries({
        queryKey: ['campaign', activeCampaignId, 'global-vars-preview']
      });
    },
    onError: (err) => {
      toast.error(formatFarmApiError(err, tRecovery('saveFailed')));
    }
  });
  const selectedDeviceId = useMemo(() => {
    if (!selectedSerial) return null;
    const matchBySerial = (
      rows: Array<{ id: string; serial: string }> | undefined
    ) =>
      rows?.find((d) => deviceSerialMatches(d.serial, selectedSerial))?.id ??
      null;
    return (
      matchBySerial(devicesQuery.data) ??
      matchBySerial(campaignDevicesQuery.data)
    );
  }, [devicesQuery.data, campaignDevicesQuery.data, selectedSerial]);
  const hasCampaignDevices = (campaignDevicesQuery.data ?? []).length > 0;
  const canOpenDeviceVarsDialog = canManageDeviceVars && hasCampaignDevices;
  const deviceVarsParseMsgs = useMemo(
    () => ({
      invalidJson: tDv('parseInvalidJson'),
      invalidRoot: tDv('parseInvalidRoot')
    }),
    [tDv]
  );
  const declaredDeviceVarKeys = useMemo(
    () =>
      collectDeclaredDeviceVarKeys(
        deviceVarJsonDrafts,
        deviceVarEnabledByDevice,
        deviceVarsParseMsgs,
        parseDeviceVarsJson
      ),
    [deviceVarJsonDrafts, deviceVarEnabledByDevice, deviceVarsParseMsgs]
  );
  const scenarioVariablesWithDeviceKeys = useMemo(
    () => mergeDeclaredDeviceVarKeys(scenarioVariables, declaredDeviceVarKeys),
    [scenarioVariables, declaredDeviceVarKeys]
  );
  const syncDeviceVarKeysIntoScenarioVariables = useCallback(() => {
    const next = mergeDeclaredDeviceVarKeys(
      scenarioVariables,
      declaredDeviceVarKeys
    );
    if (next !== scenarioVariables) setScenarioVariables(next);
    return next;
  }, [scenarioVariables, declaredDeviceVarKeys]);
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
  const campaignForGlobalVarsQuery = useQuery({
    queryKey: ['campaign', activeCampaignId, 'global-vars-preview'],
    enabled:
      tabActive &&
      !!activeCampaignId &&
      (deviceVarDialogOpen || canManageDeviceVars),
    queryFn: () => campaignsApi.get(activeCampaignId!),
    staleTime: 0,
    refetchOnMount: 'always'
  });
  useEffect(() => {
    if (!deviceVarDialogOpen) {
      deviceVarUserEditedRef.current = new Set();
      deviceVarDialogInitRef.current = false;
    }
  }, [deviceVarDialogOpen]);
  const selectScenarioDeviceForVars = useCallback(
    (deviceId: string, serial: string) => {
      setSelectedScenarioDeviceId(deviceId);
      setDeviceVarJsonDrafts((prev) => ({
        ...prev,
        [deviceId]: prev[deviceId] ?? formatDeviceVarsJson({})
      }));
      if (device.connectedDevices.some((d) => d.serial === serial)) {
        device.setSelectedSerial(serial);
      }
    },
    [device]
  );
  useEffect(() => {
    if (!deviceVarDialogOpen) return;
    if (deviceVarDialogInitRef.current) return;
    deviceVarDialogInitRef.current = true;
    const pickId =
      selectedDeviceId ?? campaignDevicesQuery.data?.[0]?.id ?? null;
    if (!pickId) return;
    const pickSerial =
      campaignDevicesQuery.data?.find((d) => d.id === pickId)?.serial ??
      selectedSerial;
    if (pickSerial) {
      selectScenarioDeviceForVars(pickId, pickSerial);
    } else {
      setSelectedScenarioDeviceId(pickId);
      setDeviceVarJsonDrafts((prev) => ({
        ...prev,
        [pickId]: prev[pickId] ?? formatDeviceVarsJson({})
      }));
    }
  }, [
    deviceVarDialogOpen,
    selectedDeviceId,
    selectedSerial,
    campaignDevicesQuery.data,
    selectScenarioDeviceForVars
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
      formatDeviceVarsJson({}))
    : formatDeviceVarsJson({});
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
        scenarioVariablesWithDeviceKeys
      ),
    [campaignForGlobalVarsQuery.data, scenarioVariablesWithDeviceKeys]
  );
  const setCurrentDeviceVarsEnabled = useCallback(
    (enabled: boolean) => {
      if (!selectedScenarioDeviceId) return;
      deviceVarUserEditedRef.current.add(selectedScenarioDeviceId);
      setDeviceVarEnabledByDevice((prev) => ({
        ...prev,
        [selectedScenarioDeviceId]: enabled
      }));
      setDeviceVarJsonDrafts((prev) => ({
        ...prev,
        [selectedScenarioDeviceId]:
          prev[selectedScenarioDeviceId] ?? formatDeviceVarsJson({})
      }));
    },
    [selectedScenarioDeviceId]
  );
  const setCurrentDeviceVarJsonDraft = useCallback(
    (value: string) => {
      if (!selectedScenarioDeviceId) return;
      deviceVarUserEditedRef.current.add(selectedScenarioDeviceId);
      setDeviceVarJsonDrafts((prev) => ({
        ...prev,
        [selectedScenarioDeviceId]: value
      }));
    },
    [selectedScenarioDeviceId]
  );
  const setScenarioDeviceVarsCache = useCallback(
    (entries: Array<readonly [string, Record<string, any>]>) => {
      if (!activeCampaignId || !activeDeviceVarScenarioId) return;
      for (const [deviceId, vars] of entries) {
        queryClient.setQueryData<ScenarioDeviceVariablesOut>(
          [
            'campaign-device-variables',
            activeCampaignId,
            activeDeviceVarScenarioId,
            deviceId
          ],
          {
            scenario_id: activeDeviceVarScenarioId,
            device_id: deviceId,
            vars
          }
        );
      }
    },
    [activeCampaignId, activeDeviceVarScenarioId, queryClient]
  );
  useEffect(() => {
    if (!canManageDeviceVars) return;
    const devices = campaignDevicesQuery.data ?? [];
    if (devices.length === 0) return;

    if (usesCampaignDeviceOverrides && !campaignForGlobalVarsQuery.data) {
      return;
    }

    const hydrationKey = usesCampaignDeviceOverrides
      ? `campaign:${activeCampaignId}:${campaignForGlobalVarsQuery.dataUpdatedAt}`
      : `scenario:${activeCampaignId}:${activeDeviceVarScenarioId}:${deviceVarDialogOpen ? 'open' : 'bg'}`;

    if (deviceVarsHydratedKeyRef.current === hydrationKey) {
      return;
    }

    const applySeeds = (
      entries: Array<readonly [string, Record<string, any>, boolean?]>
    ) => {
      setDeviceVarJsonDrafts((prev) =>
        Object.fromEntries(
          entries.map(([deviceId, vars]) => [
            deviceId,
            deviceVarDialogOpen &&
            deviceVarUserEditedRef.current.has(deviceId) &&
            prev[deviceId] !== undefined
              ? prev[deviceId]
              : formatDeviceVarsJson(vars)
          ])
        )
      );
      setDeviceVarEnabledByDevice((prev) =>
        Object.fromEntries(
          entries.map(([deviceId, vars, enabled]) => [
            deviceId,
            deviceVarDialogOpen &&
            deviceVarUserEditedRef.current.has(deviceId) &&
            prev[deviceId] !== undefined
              ? prev[deviceId]
              : (enabled ?? Object.keys(vars).length > 0)
          ])
        )
      );
      deviceVarsHydratedKeyRef.current = hydrationKey;
    };

    if (usesCampaignDeviceOverrides) {
      let cancelled = false;
      (async () => {
        const detail = await campaignsApi.get(activeCampaignId!);
        if (cancelled) return;
        syncCampaignDetailCaches(queryClient, activeCampaignId!, detail);
        const overrides = campaignPerDeviceOverrides(detail);
        applySeeds(
          devices.map(
            (d) =>
              [
                d.id,
                { ...(overrides[d.id] ?? {}) },
                Object.prototype.hasOwnProperty.call(overrides, d.id)
              ] as const
          )
        );
        const dataUpdatedAt = queryClient.getQueryState([
          'campaign',
          activeCampaignId,
          'global-vars-preview'
        ])?.dataUpdatedAt;
        deviceVarsHydratedKeyRef.current = `campaign:${activeCampaignId}:${dataUpdatedAt ?? 0}`;
      })().catch((err) =>
        toast.error(tDvDlg('loadVarsError', { message: String(err) }))
      );
      return () => {
        cancelled = true;
      };
    }

    if (!activeDeviceVarScenarioId) {
      const seeded: Record<string, string> = {};
      const enabled: Record<string, boolean> = {};
      const base = pendingScenarioDeviceVarsDraftMap ?? {};
      for (const d of devices) {
        const vars = { ...(base[d.id] ?? {}) };
        seeded[d.id] = formatDeviceVarsJson(vars);
        enabled[d.id] = Object.keys(vars).length > 0;
      }
      setDeviceVarJsonDrafts(seeded);
      setDeviceVarEnabledByDevice(enabled);
      deviceVarsHydratedKeyRef.current = hydrationKey;
      return;
    }

    if (pendingScenarioDeviceVarsDraftMap) {
      return;
    }

    let cancelled = false;
    (async () => {
      const entries = await Promise.all(
        devices.map(async (d) => {
          const res = await campaignsApi.getScenarioDeviceVariables(
            activeCampaignId!,
            activeDeviceVarScenarioId,
            d.id
          );
          return [d.id, (res.vars ?? {}) as Record<string, any>] as const;
        })
      );
      if (cancelled) return;
      applySeeds(entries);
    })().catch((err) =>
      toast.error(tDvDlg('loadVarsError', { message: String(err) }))
    );
    return () => {
      cancelled = true;
    };
  }, [
    canManageDeviceVars,
    deviceVarDialogOpen,
    campaignDevicesQuery.data,
    campaignForGlobalVarsQuery.data,
    campaignForGlobalVarsQuery.dataUpdatedAt,
    activeCampaignId,
    activeDeviceVarScenarioId,
    usesCampaignDeviceOverrides,
    pendingScenarioDeviceVarsDraftMap,
    tDvDlg,
    queryClient
  ]);
  const saveScenarioDeviceVarsMutation = useMutation({
    mutationFn: async ({
      drafts,
      enabledByDevice
    }: {
      drafts: Record<string, string>;
      enabledByDevice: Record<string, boolean>;
    }) => {
      if (!activeCampaignId) return;
      const devices = campaignDevicesQuery.data ?? [];

      if (usesCampaignDeviceOverrides) {
        syncDeviceVarKeysIntoScenarioVariables();
        const detail = await campaignsApi.get(activeCampaignId);
        const existing = campaignPerDeviceOverrides(detail);
        const nextOverrides: Record<string, Record<string, unknown>> = {
          ...existing
        };
        for (const d of devices) {
          if (enabledByDevice[d.id] !== true) {
            delete nextOverrides[d.id];
            continue;
          }
          let deviceOnly: Record<string, unknown>;
          try {
            const parsed = parseDeviceVarsJson(
              drafts[d.id] ?? '{}',
              deviceVarsParseMsgs
            );
            // Draft stores device-only overrides; fall back to split when raw merged JSON was kept.
            deviceOnly = splitDeviceOverridesFromMerged(
              parsed,
              deviceVarGlobalPreview
            );
            if (
              Object.keys(deviceOnly).length === 0 &&
              Object.keys(parsed).length > 0
            ) {
              deviceOnly = parsed;
            }
          } catch {
            throw new Error(tDv('invalidAtDevice', { serial: d.serial }));
          }
          nextOverrides[d.id] = deviceOnly;
        }
        const campaignVars = campaignVariables(detail);
        const declaredCampaignVars = mergeDeclaredDeviceVarKeys(
          campaignVars,
          declaredDeviceVarKeys
        );
        await campaignsApi.patchEntity(activeCampaignId, {
          per_device_overrides: nextOverrides,
          ...(declaredCampaignVars !== campaignVars
            ? { vars: declaredCampaignVars }
            : {})
        });
        return;
      }

      if (!activeDeviceVarScenarioId) return;
      const declaredVariables = syncDeviceVarKeysIntoScenarioVariables();
      await Promise.all(
        devices.map((d) => {
          let vars: Record<string, any> = {};
          if (enabledByDevice[d.id] === true) {
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
            activeDeviceVarScenarioId,
            d.id,
            {
              vars
            }
          );
        })
      );
      if (declaredVariables !== scenarioVariables) {
        const updated = await scenariosApi.update(
          activeCampaignId,
          activeDeviceVarScenarioId,
          {
            variables: declaredVariables
          }
        );
        syncSavedScenarioCaches(queryClient, activeCampaignId, updated);
      }
    },
    onSuccess: async () => {
      if (!activeCampaignId) {
        toast.success(tDvDlg('saveAllSuccess'));
        setDeviceVarDialogOpen(false);
        return;
      }
      try {
        const devices = campaignDevicesQuery.data ?? [];
        if (usesCampaignDeviceOverrides) {
          const detail = await campaignsApi.get(activeCampaignId);
          syncCampaignDetailCaches(queryClient, activeCampaignId, detail);
          const overrides = campaignPerDeviceOverrides(detail);
          setDeviceVarJsonDrafts(
            Object.fromEntries(
              devices.map((d) => [
                d.id,
                formatDeviceVarsJson({ ...(overrides[d.id] ?? {}) })
              ])
            )
          );
          setDeviceVarEnabledByDevice(
            Object.fromEntries(
              devices.map((d) => [
                d.id,
                Object.prototype.hasOwnProperty.call(overrides, d.id)
              ])
            )
          );
          const dataUpdatedAt = queryClient.getQueryState([
            'campaign',
            activeCampaignId,
            'global-vars-preview'
          ])?.dataUpdatedAt;
          deviceVarsHydratedKeyRef.current = `campaign:${activeCampaignId}:${dataUpdatedAt ?? 0}`;
        } else if (activeDeviceVarScenarioId) {
          const entries = await Promise.all(
            devices.map(async (d) => {
              const res = await campaignsApi.getScenarioDeviceVariables(
                activeCampaignId,
                activeDeviceVarScenarioId,
                d.id
              );
              return [d.id, (res.vars ?? {}) as Record<string, any>] as const;
            })
          );
          setDeviceVarJsonDrafts(
            Object.fromEntries(
              entries.map(([deviceId, vars]) => [
                deviceId,
                formatDeviceVarsJson(vars)
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
          deviceVarsHydratedKeyRef.current = `scenario:${activeCampaignId}:${activeDeviceVarScenarioId}:bg`;
          setScenarioDeviceVarsCache(entries);
        }
        deviceVarUserEditedRef.current = new Set();
        toast.success(tDvDlg('saveAllSuccess'));
        setDeviceVarDialogOpen(false);
      } catch (err) {
        toast.error(tDvDlg('loadVarsError', { message: String(err) }));
      }
    },
    onError: (err) => toast.error(String(err))
  });
  useEffect(() => {
    if (!pendingScenarioDeviceVarsDraftMap) return;
    if (!activeCampaignId || !activeDeviceVarScenarioId) return;
    const devices = campaignDevicesQuery.data ?? [];
    if (devices.length === 0) return;
    const draftMap = pendingScenarioDeviceVarsDraftMap;
    Promise.all(
      devices.map((d) => {
        const vars = draftMap[d.id] ?? {};
        return campaignsApi.replaceScenarioDeviceVariables(
          activeCampaignId,
          activeDeviceVarScenarioId,
          d.id,
          {
            vars
          }
        );
      })
    )
      .then(() => {
        const entries = devices.map(
          (d) => [d.id, { ...(draftMap[d.id] ?? {}) }] as const
        );
        setDeviceVarJsonDrafts(
          Object.fromEntries(
            entries.map(([deviceId, vars]) => [
              deviceId,
              formatDeviceVarsJson(vars)
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
        deviceVarsHydratedKeyRef.current = `scenario:${activeCampaignId}:${activeDeviceVarScenarioId}:bg`;
        setScenarioDeviceVarsCache(entries);
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
    activeDeviceVarScenarioId,
    campaignDevicesQuery.data,
    setScenarioDeviceVarsCache
  ]);

  useEffect(() => {
    if (save.editingContext?.variables) {
      setScenarioVariables(flattenVarDefs(save.editingContext.variables));
    }
  }, [save.editingContext]);

  useEffect(() => {
    if (save.editingContext?.variables) return;
    if (save.orgScenarioContext?.variables) {
      setScenarioVariables(flattenVarDefs(save.orgScenarioContext.variables));
    }
  }, [save.editingContext, save.orgScenarioContext]);

  useEffect(() => {
    flowSelectedFgIdRef.current = flowSelectedFgId;
  }, [flowSelectedFgId]);

  useEffect(() => {
    if (showFlowUi) return;
    setFlowSelectedFgId(null);
    setFlowDetailStep(null);
    setFlowCoordPick(null);
    setFlowSelectorPickFgId(null);
    setFlowRunStates((prev) => (Object.keys(prev).length === 0 ? prev : {}));
  }, [showFlowUi]);

  useEffect(() => {
    if (!flowSelectedFgId) {
      setFlowDetailStep(null);
      return;
    }
    const found = findStepByFlowgramId(
      stepsItemsRef.current as FlowStep[],
      flowSelectedFgId
    );
    setFlowDetailStep(
      found ? (JSON.parse(JSON.stringify(found)) as FlowStep) : null
    );
  }, [flowSelectedFgId]);

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
      const payload = preparePreviewStepPayload(step);
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
          scenarioVariablesWithDeviceKeys,
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
      scenarioVariablesWithDeviceKeys,
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
          flowDetailPendingRef.current = latest;
          setFlowDetailStep(latest);
        } catch (e) {
          toast.error(`Không áp dụng được lên canvas: ${String(e)}`);
        } finally {
          flowDetailSyncingRef.current = false;
        }
      }, 240);
    },
    [steps]
  );

  const flushPendingFlowDetailStep = useCallback(() => {
    const fgId = flowSelectedFgIdRef.current;
    const latest = flowDetailPendingRef.current;
    const current = stepsItemsRef.current as FlowStep[];
    if (flowDetailDebounceRef.current) {
      clearTimeout(flowDetailDebounceRef.current);
      flowDetailDebounceRef.current = null;
    }
    if (!fgId || !latest) return current as typeof steps.items;

    const patched = patchStepByFlowgramId(current, fgId, latest);
    const ctx = flowCtxRef.current;
    if (!ctx) {
      flowStepsRef.current = patched as typeof steps.items;
      steps.setItems(patched as typeof steps.items);
      return patched as typeof steps.items;
    }

    try {
      flowDetailSyncingRef.current = true;
      const synced = applyStepsToFlowgramDocument(ctx, patched);
      flowStepsRef.current = synced as typeof steps.items;
      steps.setItems(synced as typeof steps.items);
      flowDetailPendingRef.current = latest;
      setFlowDetailStep(latest);
      return synced as typeof steps.items;
    } catch (e) {
      toast.error(`Không áp dụng được lên canvas: ${String(e)}`);
      return current as typeof steps.items;
    } finally {
      flowDetailSyncingRef.current = false;
    }
  }, [steps]);

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
      // Ref synced every render — always read tree after mirror pick, not stale StepCard closure.
      const payload = prepareInlinePreviewStep(
        stepsItemsRef.current as FlowStep[],
        runKey,
        step
      );
      try {
        await previewScenarioStream(
          serial,
          [payload],
          previewSession.makeStreamHandler(runId, serial, (event) => {
            if (event.event === 'step_done') {
              setStepRunStates((s) => ({
                ...s,
                [runKey]: event.ok ? 'ok' : 'error',
                ...deriveNestedInlineRunStates(runKey, event)
              }));
              if (!event.ok) toast.error(`${label}: ${event.message ?? 'Lỗi'}`);
            }
          }),
          ctrl.signal,
          scenarioVariablesWithDeviceKeys,
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
                for (const key of Object.keys(n)) {
                  if (
                    (key === runKey || key.startsWith(`${runKey}/`)) &&
                    n[key] !== 'running'
                  ) {
                    delete n[key];
                  }
                }
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
      scenarioVariablesWithDeviceKeys,
      inlineScenarioDeviceVars,
      previewSession
    ]
  );

  const runDeviceOpStep = useCallback(
    async (step: FlowStep) => {
      const serial = device.selectedDevice?.serial?.trim();
      if (!serial) {
        toast.warning('Chưa chọn thiết bị');
        return;
      }
      const runId = previewSession.beginRun();
      try {
        await previewScenarioStream(
          serial,
          [preparePreviewStepPayload(step)],
          previewSession.makeStreamHandler(runId, serial, (event) => {
            if (event.event === 'step_done' && !event.ok) {
              toast.error(
                typeof event.message === 'string'
                  ? event.message
                  : 'Thao tác thất bại'
              );
            }
          }),
          undefined,
          scenarioVariablesWithDeviceKeys,
          null,
          activeScenarioId,
          inlineScenarioDeviceVars
        );
      } catch (e) {
        toast.error(String(e));
        throw e;
      } finally {
        previewSession.onStreamEnd(runId);
      }
    },
    [
      activeScenarioId,
      device.selectedDevice?.serial,
      inlineScenarioDeviceVars,
      previewSession,
      scenarioVariablesWithDeviceKeys
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
      fallback?: { rx: number; ry: number } | null,
      options?: { keepOpen?: boolean; silent?: boolean }
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
      if (!options?.keepOpen) setSelectorPickTarget(null);
      if (options?.silent) return;
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

  const treeSelectCtxRef = useRef({
    hierarchyXml: '',
    hierarchyPickOptions: hierarchyPickOptions as typeof hierarchyPickOptions,
    selectorPickTarget: null as SelectorPickTarget | null,
    applySelectorPick,
    selector,
    t
  });
  treeSelectCtxRef.current = {
    hierarchyXml,
    hierarchyPickOptions,
    selectorPickTarget,
    applySelectorPick,
    selector,
    t
  };

  const handleTreeNodeSelect = useCallback(
    ({
      bounds,
      by,
      value,
      nodeId
    }: {
      bounds: [number, number, number, number] | null;
      by: string;
      value: string;
      nodeId: number;
    }) => {
      const ctx = treeSelectCtxRef.current;
      setHighlightBounds(bounds);
      if (nodeId != null) setSelectedNodeId(nodeId);
      const rich = findSelectorForTreeNode(ctx.hierarchyXml, bounds, {
        ...ctx.hierarchyPickOptions
      });
      if (ctx.selectorPickTarget) {
        if (rich?.value?.trim()) {
          const fallback = rich.bounds
            ? {
                rx: parseFloat(
                  ((rich.bounds.rx1 + rich.bounds.rx2) / 2).toFixed(3)
                ),
                ry: parseFloat(
                  ((rich.bounds.ry1 + rich.bounds.ry2) / 2).toFixed(3)
                )
              }
            : null;
          ctx.applySelectorPick(rich.selector, fallback);
        } else if (value?.trim()) {
          ctx.applySelectorPick({
            by: by as ScenarioSelectorShape['by'],
            value: value.trim()
          });
        } else {
          toast.warning(ctx.t('pickSelectorNoElement'));
        }
        return;
      }
      if (rich?.value?.trim()) {
        ctx.selector.setBy(rich.by as typeof ctx.selector.by);
        ctx.selector.setValue(rich.value.trim());
        return;
      }
      ctx.selector.setBy(by as typeof ctx.selector.by);
      ctx.selector.setValue(value);
    },
    []
  );

  const selectedDeviceSerial = selectedDeviceForControl?.serial ?? null;
  const handleHierarchyRefresh = useCallback(() => {
    if (!selectedDeviceSerial) return;
    if (device.selectedSerial !== selectedDeviceSerial) {
      device.setSelectedSerial(selectedDeviceSerial);
    }
    refreshHierarchy(selectedDeviceSerial);
  }, [device, selectedDeviceSerial, refreshHierarchy]);

  // Apply the candidate at `index` to the active selector-pick step. With >1
  // candidate we keep pick mode open so the user can keep cycling overlapping
  // elements (Facebook-style nested layouts).
  const applyCandidateAtIndex = useCallback(
    (index: number) => {
      const cands = pickCandidatesRef.current;
      if (cands.length === 0) return;
      const i = ((index % cands.length) + cands.length) % cands.length;
      const cand = cands[i];
      const multi = cands.length > 1;
      pickCycleIndexRef.current = i;

      const fallback = cand.bounds
        ? {
            rx: parseFloat(
              ((cand.bounds.rx1 + cand.bounds.rx2) / 2).toFixed(3)
            ),
            ry: parseFloat(((cand.bounds.ry1 + cand.bounds.ry2) / 2).toFixed(3))
          }
        : null;

      applySelectorPick(cand.selector, fallback, {
        keepOpen: multi,
        silent: multi
      });

      const duplicateCount = Math.max(
        cand.resourceIdDuplicateCount ?? 0,
        cand.textDuplicateCount ?? 0,
        cand.descDuplicateCount ?? 0
      );
      if (cand.selectorVolatile) {
        setPickSelectorWarning(
          `Selector tạm theo ${cand.selectorReason ?? 'bounds'}; nên kiểm tra lại sau khi màn hình thay đổi.`
        );
      } else if (duplicateCount > 1) {
        setPickSelectorWarning(
          `Có ${duplicateCount} phần tử trùng selector; đang dùng ${cand.selectorReason ?? cand.by}.`
        );
      } else {
        setPickSelectorWarning(null);
      }

      if (cand.bounds) {
        setHighlightBounds([
          cand.bounds.left,
          cand.bounds.top,
          cand.bounds.right,
          cand.bounds.bottom
        ]);
        const tree = parseHierarchyTree(hierarchyXml);
        if (tree && fallback) {
          const nodeId = findNodeIdAtRatio(tree, fallback.rx, fallback.ry, {
            targetPackage: pickTargetPackage
          });
          if (nodeId != null) setSelectedNodeId(nodeId);
        }
      }

      if (multi) {
        setPickCycle({ index: i + 1, total: cands.length });
        toast.success(
          t('pickSelectorCycle', {
            index: i + 1,
            total: cands.length,
            by: cand.by,
            value: cand.value.slice(0, 48)
          })
        );
      } else {
        setPickCycle(null);
      }
    },
    [applySelectorPick, hierarchyXml, pickTargetPackage, t]
  );

  // Reset cycle bookkeeping whenever selector pick mode closes.
  useEffect(() => {
    if (!selectorPickTarget) {
      pickCandidatesRef.current = [];
      lastPickSpotRef.current = null;
      pickCycleIndexRef.current = 0;
      setPickCycle(null);
      setPickSelectorWarning(null);
    }
  }, [selectorPickTarget]);

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
    [coordinatePickTarget, showFlowUi, flowCoordPick, steps]
  );

  // When user taps the phone screen → hierarchy highlight + optional selector pick
  const handleScreenTap = useCallback(
    (rx: number, ry: number) => {
      const tree = parseHierarchyTree(hierarchyXml);
      if (tree) {
        const nodeId = findNodeIdAtRatio(tree, rx, ry, {
          targetPackage: pickTargetPackage
        });
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
        const sel = findSelectorInXml(
          hierarchyXml,
          rx,
          ry,
          hierarchyPickOptions
        );
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
        const cands = listSelectorCandidatesInXml(
          hierarchyXml,
          rx,
          ry,
          hierarchyPickOptions
        );
        if (cands.length === 0) {
          toast.warning(t('pickSelectorNoElement'));
          return;
        }
        const last = lastPickSpotRef.current;
        const sameSpot =
          last != null &&
          Math.abs(last.rx - rx) < 0.015 &&
          Math.abs(last.ry - ry) < 0.015 &&
          pickCandidatesRef.current.length > 0;
        if (sameSpot) {
          applyCandidateAtIndex(pickCycleIndexRef.current + 1);
        } else {
          pickCandidatesRef.current = cands;
          lastPickSpotRef.current = { rx, ry };
          applyCandidateAtIndex(0);
        }
        return;
      }
    },
    [
      hierarchyXml,
      selectorPickTarget,
      coordinatePickTarget,
      applyCandidateAtIndex,
      hierarchyPickOptions,
      steps,
      t,
      showFlowUi,
      flowCoordPick,
      flowSelectorPickFgId,
      pickTargetPackage,
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
          ) => handleScreenSwipeRef.current(rx1, ry1, rx2, ry2, durationMs)
        : undefined,
    [mirrorSwipeEnabled]
  );

  const mirrorInputLocked = useMemo(() => {
    if (!selectedDeviceSerial)
      return { hideControls: true, readOnlyPreview: true };
    const pickingFromMirror =
      coordinatePickTarget != null ||
      selectorPickTarget != null ||
      flowCoordPick != null ||
      flowSelectorPickFgId != null;
    if (pickingFromMirror) {
      return { hideControls: false, readOnlyPreview: false };
    }
    const blocked = selectedDeviceForControl
      ? isManualControlBlockedByAutomation(selectedDeviceForControl)
      : true;
    // Keep the control rail visible; only block tap/swipe on the live mirror.
    return { hideControls: false, readOnlyPreview: blocked };
  }, [
    selectedDeviceSerial,
    selectedDeviceForControl,
    coordinatePickTarget,
    selectorPickTarget,
    flowCoordPick,
    flowSelectorPickFgId
  ]);

  const mirrorDeviceOps = useMemo((): DeviceOpsConfig | undefined => {
    const d = device.selectedDevice;
    if (!d) return undefined;
    return {
      disabled: mirrorInputLocked.readOnlyPreview,
      defaultPackage: packageFromCurrentApp(d.current_app),
      onRunStep: runDeviceOpStep,
      onRunShell: (cmd) => runAgentShell(d.serial, cmd),
      onInstallApk: (url) => {
        recordWsSend({ type: 'install', serial: d.serial, url });
        toast.info(tDeviceOps('installApkRunning', { serial: d.serial }));
      }
    };
  }, [
    device.selectedDevice,
    mirrorInputLocked.readOnlyPreview,
    runDeviceOpStep,
    tDeviceOps,
    recordWsSend
  ]);

  // ── Error / empty states ─────────────────────────────────────────────────
  if (error) {
    return (
      <div className='rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive'>
        {error}
      </div>
    );
  }

  const selectedDevice = selectedDeviceForControl;
  const noConnectedDevices = shouldShowControlRecordNoDeviceBanner({
    devicesReady: device.devicesReady,
    connectedDeviceCount: connectedDevicesForControl.length
  });
  const topBarTitle = save.templateContext
    ? save.templateContext.name
    : save.editingContext
      ? save.editingContext.name
      : save.orgScenarioContext
        ? save.orgScenarioContext.name
        : t('pageTitle');
  const topBarLabels = {
    editingScenario: t('editingScenario'),
    templateBadge: t('templateBadge'),
    backToMainScenario: tRecovery('backToMainScenario'),
    selectPhonePlaceholder: t('selectPhonePlaceholder'),
    deviceCampaignBadge: t('deviceCampaignBadge'),
    wsConnected: t('wsConnected'),
    wsDisconnected: t('wsDisconnected'),
    flowSwitchToList: t('flowSwitchToList'),
    flowSwitchToFlow: t('flowSwitchToFlow'),
    flowListLabel: t('flowListLabel'),
    flowFlowLabel: t('flowFlowLabel')
  };

  return (
    <div className='flex h-[calc(100vh-80px)] min-h-0 flex-col overflow-hidden bg-background'>
      <SafeModeBanner className='mx-3 mt-2' poll={false} />
      {noConnectedDevices ? (
        <div className='mx-3 mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed border-amber-400/40 bg-amber-400/5 px-3 py-2 text-xs'>
          <div className='min-w-0'>
            <p className='font-medium text-foreground'>
              {t('noDeviceConnected')}
            </p>
            <p className='text-muted-foreground'>
              {t('noDeviceConnectMessage')}
            </p>
          </div>
          <Button asChild size='sm' variant='outline' className='shrink-0'>
            <Link href={ROUTES.DEVICES.MANAGE}>
              <ArrowLeft className='mr-1.5 size-4' />
              {t('addDevice')}
            </Link>
          </Button>
        </div>
      ) : null}

      <ControlRecordTopBar
        title={topBarTitle}
        eyebrow={save.templateContext ? t('templateEyebrow') : t('pageEyebrow')}
        labels={topBarLabels}
        editing={Boolean(save.editingContext)}
        template={Boolean(save.templateContext)}
        showRecoveryBack={Boolean(editingRecoveryScenario && recoveryReturnTo)}
        onRecoveryBack={() =>
          guardWhilePreviewActive(() => router.push(recoveryReturnTo))
        }
        devices={connectedDevicesForControl}
        deviceSelectValue={deviceSelectValue}
        onDeviceChange={(serial) =>
          guardWhilePreviewActive(() => device.setSelectedSerial(serial))
        }
        multiFollowerOptions={multiFollowerOptions}
        multiFollowerSerials={multiFollowerSerials}
        onMultiFollowerSerialsChange={setMultiFollowerSerials}
        maxMultiFollowers={MAX_MULTI_FOLLOWER_DEVICES}
        maxMultiDevices={MAX_MULTI_CONTROL_DEVICES}
        multiPickerDisabled={!selectedDevice || !canExecuteDevice}
        multiPickerDisabledTitle={
          !canExecuteDevice
            ? safeReadOnly
              ? t('safeModeReadOnly')
              : t('noControlPermission')
            : undefined
        }
        wsConnected={device.wsConnected}
        flowEnabled={ENABLE_FLOWGRAM_CONTROL_UI}
        flowMode={flowMode}
        onToggleFlowMode={() => {
          if (!flowMode) {
            flowStepsRef.current = steps.items;
            setFlowCanvasKey((k) => k + 1);
          } else {
            steps.setItems(flowStepsRef.current);
          }
          setFlowMode((v) => !v);
        }}
      />

      {/* ── Main: cây XML + mirror + editor (Danh sách hoặc Flow cùng khung) ── */}
      <div className='flex flex-1 overflow-hidden'>
        <ControlRecordHierarchyPanel
          open={treePanelOpen}
          hiddenForMultiFollowers={hasMultiFollowers}
          safeHierarchy={safeHierarchy}
          xml={hierarchyXml}
          loading={hierarchyLoading}
          deviceActive={Boolean(
            selectedDevice?.state &&
              !['DISCONNECTED', 'DEAD'].includes(
                String(selectedDevice.state).toUpperCase()
              )
          )}
          wsConnected={Boolean(device.wsConnected)}
          onNodeSelect={handleTreeNodeSelect}
          selectedNodeId={selectedNodeId}
          onRefresh={handleHierarchyRefresh}
          autoRefresh={hierarchyAutoRefresh}
          onAutoRefreshChange={setHierarchyAutoRefresh}
          selectorBy={selector.by}
          selectorValue={selector.value}
          onTapSelector={() =>
            selector.tap({ multiSerials: activeMultiSerials })
          }
          onAddStepFromSelector={addStepFromSelector}
          canExecuteDevice={canExecuteDevice}
          hasSelectedDevice={Boolean(selectedDevice)}
          safeReadOnly={safeReadOnly}
          collapsed={leftCollapsed}
          onToggleCollapsed={() => setLeftCollapsed(!leftCollapsed)}
          selectorBarHint={t('selectorBarHint')}
        />

        <ControlRecordMirrorPanel
          ref={mirrorColRef}
          selectedDevice={selectedDevice}
          logsBySerial={device.logs}
          wsMode={device.mode}
          wsSend={mirrorWsSend}
          onToggleMode={recordHandleToggleMode}
          onRestart={recordHandleRestart}
          onTap={mirrorOnTap}
          onSwipe={mirrorOnSwipe}
          highlightBounds={highlightBounds}
          mirrorInputLocked={mirrorInputLocked}
          canExecuteDevice={canExecuteDevice}
          onTakeControl={handleTakeControl}
          deviceOps={mirrorDeviceOps}
          hasMultiFollowers={hasMultiFollowers}
          multiFocusMode={multiFocusMode}
          selectedMultiFollowerDevices={selectedMultiFollowerDevices}
          onPromoteFollower={promoteMultiFollower}
          recording={record.recording}
          onToggleRecording={() => void record.toggleRecording()}
          onOpenPlayer={() => setPlayerMode(true)}
          onOpenStepPicker={() => setStepPickerOpen(true)}
          labels={{
            startRecording: t('startRecording'),
            stopRecording: t('stopRecording'),
            tryRun: t('tryRun'),
            openPicker: t('multiControl.openPicker'),
            selectDevice: 'Chọn thiết bị từ thanh trên'
          }}
        />

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
                  preloadedVariables={scenarioVariablesWithDeviceKeys}
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
                  <div className='flex shrink-0 gap-2 border-b border-amber-400/30 bg-amber-50/80 px-4 py-2 dark:bg-amber-950/20'>
                    <Crosshair className='mt-0.5 size-3.5 shrink-0 text-amber-600' />
                    <div className='min-w-0 flex-1'>
                      <div className='flex items-center gap-2'>
                        <p className='min-w-0 flex-1 text-[11px] text-amber-800 dark:text-amber-300'>
                          {pickCycle && pickCycle.total > 1
                            ? t('pickSelectorCycleHint', {
                                index: pickCycle.index,
                                total: pickCycle.total
                              })
                            : t('pickSelectorBanner')}
                        </p>
                        {pickCycle && pickCycle.total > 1 && (
                          <div className='flex shrink-0 items-center gap-0.5'>
                            <button
                              type='button'
                              aria-label='prev'
                              className='rounded p-0.5 text-amber-700 hover:bg-amber-200/50 dark:text-amber-400'
                              onClick={() =>
                                applyCandidateAtIndex(
                                  pickCycleIndexRef.current - 1
                                )
                              }
                            >
                              <ChevronLeft className='size-3.5' />
                            </button>
                            <span className='min-w-[34px] text-center font-mono text-[10px] text-amber-800 dark:text-amber-300'>
                              {pickCycle.index}/{pickCycle.total}
                            </span>
                            <button
                              type='button'
                              aria-label='next'
                              className='rounded p-0.5 text-amber-700 hover:bg-amber-200/50 dark:text-amber-400'
                              onClick={() =>
                                applyCandidateAtIndex(
                                  pickCycleIndexRef.current + 1
                                )
                              }
                            >
                              <ChevronRight className='size-3.5' />
                            </button>
                          </div>
                        )}
                      </div>
                      {pickSelectorWarning && (
                        <div className='mt-1 flex items-center gap-1 text-[10px] text-amber-900 dark:text-amber-200'>
                          <AlertCircle className='size-3 shrink-0' />
                          <span className='min-w-0'>{pickSelectorWarning}</span>
                        </div>
                      )}
                    </div>
                    <button
                      type='button'
                      className='shrink-0 self-start text-[10px] text-amber-700 underline underline-offset-2 hover:no-underline dark:text-amber-400'
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
                      Vuốt trên mirror để lấy đoạn (điểm đầu → cuối). Esc hoặc
                      Huỷ để thoát.
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

                <ControlRecordEditorToolbar
                  showClosePicker={hasMultiFollowers && stepPickerOpen}
                  onClosePicker={() => setStepPickerOpen(false)}
                  pollingXml={record.pollingXml}
                  recording={record.recording}
                  onToggleRecording={() => void record.toggleRecording()}
                  hasSelectedDevice={Boolean(selectedDevice)}
                  selectedDeviceBusy={
                    selectedDevice
                      ? isManualControlBlockedByAutomation(selectedDevice)
                      : false
                  }
                  onOpenPlayer={() => setPlayerMode(true)}
                  onOpenJson={() => setJsonDialogOpen(true)}
                  hasSteps={steps.items.length > 0}
                  onSave={() => {
                    if (save.templateContext) {
                      save.saveToTemplate(
                        syncDeviceVarKeysIntoScenarioVariables()
                      );
                      return;
                    }
                    if (savingOrgScenario) {
                      void handleSaveOrgScenario();
                      return;
                    }
                    steps.openSave();
                  }}
                  saveDisabled={
                    steps.items.length === 0 ||
                    !canSaveWork ||
                    save.savingTemplate ||
                    saveOrgBodyMutation.isPending
                  }
                  saveLabel={
                    save.templateContext
                      ? save.savingTemplate
                        ? t('templateSaving')
                        : t('templateSave')
                      : savingOrgScenario
                        ? saveOrgBodyMutation.isPending
                          ? 'Đang lưu…'
                          : 'Lưu'
                        : 'Lưu'
                  }
                  onOpenVariables={() => setVarDialogOpen(true)}
                  variableCount={
                    Object.keys(scenarioVariablesWithDeviceKeys).length
                  }
                  showRecovery={!editingRecoveryScenario}
                  recoveryEnabled={recoveryPolicyEnabled}
                  onOpenRecovery={() => setRecoveryDialogOpen(true)}
                  onOpenDeviceVars={() => setDeviceVarDialogOpen(true)}
                  deviceVarsEnabled={Boolean(
                    hasEnabledDeviceVars &&
                      canManageDeviceVars &&
                      selectedDeviceId
                  )}
                  deviceVarsDisabled={!canOpenDeviceVarsDialog}
                  labels={{
                    closePickerTitle: t('multiControl.closePicker'),
                    startRecording: t('startRecording'),
                    stopRecording: t('stopRecording'),
                    tryRun: t('tryRun'),
                    busyTitle:
                      'Thiết bị đang chạy campaign — không cho chạy thử',
                    jsonTooltip: 'Xem JSON',
                    variables: 'Biến',
                    variablesTooltip:
                      'Chỉnh biến — giá trị thay thế cho ${VAR} khi chạy thử bước',
                    recoveryTitle: tRecovery('controlRecordTitle'),
                    recoveryEnabledBadge: tRecovery('enabledBadge'),
                    recoveryTooltip: activeCampaignId
                      ? tRecovery('controlRecordTooltip')
                      : tRecovery('controlRecordNoCampaignTooltip'),
                    deviceVars: 'Biến thiết bị',
                    deviceVarsTooltip: !canManageDeviceVars
                      ? savingOrgScenario
                        ? 'Mở lại từ Campaign → Mở (URL cần orgScenarioId + campaignId)'
                        : 'Mở trong ngữ cảnh chiến dịch để thiết lập'
                      : !hasCampaignDevices
                        ? 'Thêm thiết bị vào chiến dịch trước'
                        : `Đang gắn cho: ${selectedDeviceLabel}`,
                    helpTooltip: t('tooltipScenarioSection')
                  }}
                />

                {/* Flow editor */}
                <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
                  <div className='min-h-0 flex-1 overflow-y-auto px-3 pb-2'>
                    {steps.items.length === 0 ? (
                      <EmptyNodePicker
                        templates={templatesQuery.data}
                        templatesLoading={templatesQuery.isLoading}
                        onPreviewTemplate={(tpl) => {
                          setScenarioVariables((prev) =>
                            mergeTemplateVariablesIntoEditor(
                              prev,
                              tpl.variables
                            )
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
                              if (flowDetailSyncingRef.current) return;
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
                                Bấm <strong>con trỏ</strong> trên node → chỉnh
                                chi tiết; <strong>play</strong> chạy một bước.
                                Cây XML + thêm bước từ selector vẫn dùng cột
                                trái như chế độ danh sách.
                              </p>
                              <p className='rounded-md border border-border/80 bg-muted/30 px-2 py-1.5 text-[10px]'>
                                <strong>Không có “kéo dây” tự do</strong> —
                                Flowgram (fixed-layout) tự vẽ nối theo thứ tự
                                dọc và nhánh if/loop/random. Đổi thứ tự bằng{' '}
                                <strong>kéo thả node</strong>. Muốn nối dây tùy
                                ý cần editor dạng graph tự do (vd. React Flow),
                                không nằm trong thư viện hiện tại.
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
                                <Square
                                  className='size-3'
                                  fill='currentColor'
                                />
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
                            onRunStep={
                              selectedDevice ? handleRunStep : undefined
                            }
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

      <ControlRecordVariablesDialog
        open={varDialogOpen}
        onOpenChange={setVarDialogOpen}
        variables={scenarioVariablesWithDeviceKeys}
        onVariablesChange={setScenarioVariables}
        labels={{
          title: tVar('title'),
          variableCount:
            Object.keys(scenarioVariablesWithDeviceKeys).length > 0
              ? tVar('variableCount', {
                  count: Object.keys(scenarioVariablesWithDeviceKeys).length
                })
              : null,
          headerSubtitleLead: tVar('headerSubtitleLead'),
          headerSubtitleTrail: tVar('headerSubtitleTrail')
        }}
      />

      <ControlRecordDeviceVarsDialog
        open={deviceVarDialogOpen}
        onOpenChange={setDeviceVarDialogOpen}
        campaignDevices={campaignDevicesQuery.data ?? []}
        selectedScenarioDeviceId={selectedScenarioDeviceId}
        deviceVarEnabledByDevice={deviceVarEnabledByDevice}
        selectScenarioDeviceForVars={selectScenarioDeviceForVars}
        panel={{
          enabled: currentDeviceVarsEnabled,
          onEnabledChange: setCurrentDeviceVarsEnabled,
          draft: currentDeviceVarJsonDraft,
          onDraftChange: setCurrentDeviceVarJsonDraft,
          jsonError: currentDeviceVarJsonError,
          deviceLabel: selectedDeviceLabel,
          baseVariables: deviceVarGlobalPreview,
          globalVariablesPreview: deviceVarGlobalPreview
        }}
        onCancel={() => setDeviceVarDialogOpen(false)}
        onSave={() => {
          if (activeDeviceVarScenarioId || usesCampaignDeviceOverrides) {
            syncDeviceVarKeysIntoScenarioVariables();
            saveScenarioDeviceVarsMutation.mutate(deviceVarStateRef.current);
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
          syncDeviceVarKeysIntoScenarioVariables();
          setPendingScenarioDeviceVarsDraftMap(parsedDrafts);
          setDeviceVarDialogOpen(false);
          toast.info(tDvDlg('saveDraftToast'));
        }}
        saveDisabled={
          saveScenarioDeviceVarsMutation.isPending ||
          (campaignDevicesQuery.data ?? []).length === 0 ||
          !!currentDeviceVarJsonError
        }
        saveLabel={
          saveScenarioDeviceVarsMutation.isPending
            ? tDvDlg('saveLoading')
            : activeDeviceVarScenarioId || usesCampaignDeviceOverrides
              ? tDvDlg('save')
              : tDvDlg('saveDraft')
        }
        labels={{
          title: tDv('title'),
          scopeHint: tDvDlg('scopeHint'),
          instructions: tDvDlg('instructions'),
          noDevicesInCampaign: tDvDlg('noDevicesInCampaign'),
          badgePerDevice: tDvDlg('badgePerDevice'),
          badgeGlobal: tDvDlg('badgeGlobal'),
          cancel: tModal('cancel')
        }}
      />

      <ControlRecordRecoveryDialog
        open={recoveryDialogOpen}
        onOpenChange={setRecoveryDialogOpen}
        activeCampaignId={activeCampaignId}
        selectedSerial={selectedSerial}
        value={recoveryPolicy}
        onChange={setRecoveryPolicy}
        savePending={saveRecoveryPolicyMutation.isPending}
        onBeforeRecord={async (policy) => {
          await saveRecoveryPolicyMutation.mutateAsync(policy);
          setRecoveryDialogOpen(false);
        }}
        onCancel={() => setRecoveryDialogOpen(false)}
        onSave={() => saveRecoveryPolicyMutation.mutate(recoveryPolicy)}
        labels={{
          title: tRecovery('controlRecordTitle'),
          description: tRecovery('controlRecordDescription'),
          standaloneWarning: tRecovery('standaloneWarning'),
          cancel: tModal('cancel'),
          saving: tRecovery('saving'),
          save: tRecovery('save')
        }}
      />

      <ControlRecordJsonDialog
        open={jsonDialogOpen}
        onOpenChange={setJsonDialogOpen}
        steps={steps.items as Record<string, any>[]}
        labels={{
          title: 'JSON kịch bản',
          stepCount: `${steps.items.length} bước`
        }}
      />

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
                      syncDeviceVarKeysIntoScenarioVariables(),
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
                            syncDeviceVarKeysIntoScenarioVariables(),
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

      <ControlRecordExitConfirmDialog
        open={exitConfirm !== null}
        onOpenChange={(o) => {
          if (!o) setExitConfirm(null);
        }}
        onConfirm={() => {
          const action = exitConfirm;
          setExitConfirm(null);
          stopPlayerRef.current?.();
          handleStopInlineRun();
          if (action) action();
        }}
        labels={{
          title: t('exitConfirmTitle'),
          description: t('exitConfirmDesc'),
          cancel: t('exitConfirmCancel'),
          confirm: t('exitConfirmConfirm')
        }}
      />

      <ControlRecordTakeoverConfirmDialog
        open={takeoverDialogOpen}
        onOpenChange={(o) => {
          if (!takeoverPending) setTakeoverDialogOpen(o);
        }}
        pending={takeoverPending}
        onConfirm={() => void handleTakeoverConfirm()}
        labels={{
          title: t('takeover.confirmTitle'),
          description: t('takeover.confirmDesc'),
          cancel: t('takeover.confirmCancel'),
          confirm: t('takeover.confirmAction')
        }}
      />

      <ControlRecordTemplatePreviewDialog
        template={previewTemplate}
        onOpenChange={(o) => {
          if (!o) {
            stopPreviewIfActive();
            setPreviewTemplate(null);
          }
        }}
        onCancel={() => {
          stopPreviewIfActive();
          setPreviewTemplate(null);
        }}
        onAppend={() => {
          stopPreviewIfActive();
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
        labels={{
          builtinBadge: t('emptyNodePicker.templateBuiltinBadge'),
          formatStepCount: (count) =>
            t('emptyNodePicker.templateStepCount', { count }),
          noSteps: t('emptyNodePicker.templateNoSteps'),
          cancel: t('emptyNodePicker.templateCancel'),
          append: t('emptyNodePicker.templateAppend')
        }}
      />
    </div>
  );
}
