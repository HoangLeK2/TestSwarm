'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  useAccount,
  useDeviceAccounts,
  useFacebookPlatformSession
} from '@/features/accounts/hooks/use-accounts';
import { ScenarioPlayer } from './control-record/scenario-player';
import { packageFromCurrentApp, type DeviceOpsConfig } from './device-ops-rail';
import { ControlRecordTopBar } from './control-record/control-record-top-bar';
import { ControlRecordHierarchyPanel } from './control-record/control-record-hierarchy-panel';
import { ControlRecordMirrorPanel } from './control-record/control-record-mirror-panel';
import { ScenarioWorkbenchShell } from './control-record/scenario-workbench-shell';
import type { ImageTemplatePick } from '@/features/campaigns/components/flow-editor/image-template-dialog';
import {
  ImageTemplateScenarioProvider,
  type MirrorRegion
} from '@/features/campaigns/components/flow-editor/image-template-scenario';
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
  AlertCircle,
  ListTree,
  Smartphone,
  MousePointer2,
  PlayCircle,
  Save
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
import { farmApi } from '@/lib/farm-api';
import {
  ScenarioRequirementsSettingsDialog,
  scenarioRequiresPlatformSession
} from '@/features/campaigns/components/scenario-requirements-summary';
import { normalizeInternalAppPath } from '@/lib/i18n-path';
import type { RegionSelect, RegionSelectRect } from './device-screen';
import { orgScenariosApi } from '@/features/org-scenarios/services/api';
import { useSaveOrgScenarioBody } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { buildOrgScenarioBodyPayload } from '@/features/org-scenarios/lib/build-org-scenario-body';
import { isGraphOrgScenario } from '@/features/org-scenarios/lib/campaign-scenario-eligibility';
import { validateScenarioStepsForApi } from '@/features/campaigns/utils/validate-scenario-steps-for-api';
import { stepsToGraph } from '@/features/campaigns/utils/steps-to-graph';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import {
  collectScenarioVariableReferences,
  detectSingleVariableRename,
  replaceScenarioVariableReferences
} from '@/lib/scenario-variable-references';
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
  scenarioDeviceCapabilitiesApi,
  scenarioSchemaApi,
  scenariosApi,
  type ScenarioCapabilityPreflightOut,
  type ScenarioDeviceVariablesOut
} from '@/features/campaigns/services/api';
import { useScenarioTemplates } from '@/features/scenario-templates/hooks/use-scenario-templates';
import {
  scenarioTemplatesApi,
  type ScenarioTemplateOut
} from '@/features/scenario-templates/services/api';
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
import type { StepRunResult } from '@/features/campaigns/components/flow-editor/step-run-result';
import { humanizeSessionGateMessage } from '@/features/campaigns/lib/session-gate-message';
import { canPersistScenario } from '@/features/campaigns/components/flow-editor/nested-step-edit';
import { deriveNestedInlineRunStates } from '@/features/campaigns/components/flow-editor/inline-run-key';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { deviceCapabilityMapFromDevice } from '@/features/campaigns/lib/node-capabilities';
import {
  scenarioCapabilityIssueSummary,
  scenarioCapabilityWarningSummary
} from '@/features/campaigns/lib/scenario-capability-preflight';
import {
  scenarioLintPreflightForInlineRun,
  scenarioLintPreflightForSteps,
  scenarioLintSummary,
  type ScenarioLintPreflightResult
} from '@/features/campaigns/lib/scenario-lint-preflight';
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
import { pushScenarioNodeDataUpdate } from '@/features/scenario-templates/components/scenario-flow-editor/node-data-history';
import type { FlowgramRunState } from '@/features/scenario-templates/components/scenario-flow-editor/flowgram-scenario-context';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  collectDeclaredDeviceVarKeys,
  flattenVarDefs,
  mergeDeclaredDeviceVarKeys,
  mergeTemplateVariablesIntoEditor
} from '../lib/control-record-variables';
import { buildControlRecordPageSummary } from '../lib/control-record-page-summary';
import {
  deviceSerialMatches,
  isManualControlBlockedByAutomation,
  resolveControlRecordSelectedDevice,
  shouldShowControlRecordNoDeviceBanner
} from '../lib/control-record-device-state';
import { needsFreshMirrorSelectorXml } from '../lib/control-record-hierarchy';
import {
  prepareInlinePreviewStep,
  preparePreviewStepPayload
} from '../lib/control-record-preview-steps';
import { syncCampaignDetailCaches } from '../lib/control-record-cache';
import { sanitizeScenarioStepsForApi } from '../lib/sanitize-scenario-steps-for-api';
import { useConfirm } from '@/providers/modal-provider';
import { useIsMobile } from '@/hooks/use-mobile';

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

const CONTROL_EDITOR_ENV = (
  process.env.NEXT_PUBLIC_DEVICE_FARM_CONTROL_EDITOR ?? 'list'
)
  .trim()
  .toLowerCase();
const ENABLE_FLOWGRAM_CONTROL_UI = CONTROL_EDITOR_ENV === 'flowgram';
const DEFAULT_FLOWGRAM_CONTROL_UI = ENABLE_FLOWGRAM_CONTROL_UI;

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
  const tRequirements = useTranslations(
    'campaignsFeature.stepEditor.requirements'
  );
  const isMobile = useIsMobile();
  const tGate = useTranslations('executionMessages');
  const tCapabilityPreflight = useTranslations(
    'campaignsFeature.capabilityPreflight'
  );
  const tScenarioLintPreflight = useTranslations(
    'devicesControlRecord.scenarioLintPreflight'
  );
  const confirm = useConfirm();
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
  const fetchFreshHierarchy = hierarchy.fetchFresh;
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
  const [childStepEditorOpen, setChildStepEditorOpen] = useState(false);
  const savingOrgScenario = Boolean(initialOrgScenarioId);
  const canSaveWork =
    !safeReadOnly &&
    (save.templateContext
      ? templatePerms.canUpdate
      : savingOrgScenario
        ? orgScenarioPerms.canUpdate
        : orgScenarioPerms.canCreate);
  const canSaveScenarioVariables =
    !safeReadOnly &&
    (save.templateContext
      ? templatePerms.canUpdate
      : savingOrgScenario && initialCampaignId
        ? campaignPerms.canUpdate
        : savingOrgScenario
          ? orgScenarioPerms.canUpdate
          : orgScenarioPerms.canCreate);
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
    const latestSteps = await lintCurrentScenarioBeforePersist(
      tScenarioLintPreflight('saveContext')
    );
    if (!latestSteps) return;
    if (latestSteps.length === 0) {
      toast.warning(tOrg('saveOrgNoSteps'));
      return;
    }
    const body = buildOrgScenarioBodyPayload(
      latestSteps,
      syncDeviceVarKeysIntoScenarioVariables(),
      save.requirements
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
  const [flowMode, setFlowMode] = useState(DEFAULT_FLOWGRAM_CONTROL_UI);
  const [flowSortMode, setFlowSortMode] = useState(false);
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
  const selectedDeviceForControl = useMemo(() => {
    const selectedSerial =
      rawSelectedDeviceForControl?.serial ?? device.selectedSerial;
    const liveSelected = resolveControlRecordSelectedDevice(
      connectedDevicesForControl,
      selectedSerial
    );
    if (!rawSelectedDeviceForControl) return liveSelected;
    if (!liveSelected) return rawSelectedDeviceForControl;
    return {
      ...rawSelectedDeviceForControl,
      ...liveSelected,
      manual_takeover_active:
        rawSelectedDeviceForControl.manual_takeover_active ??
        liveSelected.manual_takeover_active
    };
  }, [
    connectedDevicesForControl,
    device.selectedSerial,
    rawSelectedDeviceForControl
  ]);
  const { data: scenarioSchema } = useQuery({
    queryKey: ['scenario-schema'],
    queryFn: scenarioSchemaApi.get,
    staleTime: 300_000
  });
  const { data: selectedCapabilitySnapshot } = useQuery({
    queryKey: [
      'scenario-device-capabilities',
      selectedDeviceForControl?.serial ?? ''
    ],
    queryFn: () =>
      scenarioDeviceCapabilitiesApi.get(selectedDeviceForControl?.serial ?? ''),
    enabled: Boolean(selectedDeviceForControl?.serial),
    staleTime: 15_000,
    refetchInterval: 15_000
  });
  const selectedDeviceCapabilities = useMemo(
    () => ({
      ...(deviceCapabilityMapFromDevice(selectedDeviceForControl) ?? {}),
      ...(selectedCapabilitySnapshot?.capabilities ?? {})
    }),
    [selectedDeviceForControl, selectedCapabilitySnapshot?.capabilities]
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
  const flowDetailPendingFgIdRef = useRef<string | null>(null);
  const flowDetailSyncingRef = useRef(false);
  const flowRunLeafAbortRef = useRef<AbortController | null>(null);
  const flowRunningFgIdsRef = useRef<Set<string>>(new Set());
  const [varDialogOpen, setVarDialogOpen] = useState(false);
  const [deviceVarDialogOpen, setDeviceVarDialogOpen] = useState(false);
  const [requirementsDialogOpen, setRequirementsDialogOpen] = useState(false);
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
  const [stepRunResults, setStepRunResults] = useState<
    Record<string, StepRunResult>
  >({});
  const [scenarioPreflight, setScenarioPreflight] =
    useState<ScenarioCapabilityPreflightOut | null>(null);
  const [scenarioPreflightChecking, setScenarioPreflightChecking] =
    useState(false);
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
  }, [
    connectedDevicesForControl,
    device.selectedSerial,
    selectedDeviceForControl
  ]);

  const handleFlowStepsChange = useCallback(
    (newSteps: FlowStep[]) => {
      // Inline run results are keyed by *position* (`rootIndex/listKey:childIndex`),
      // so inserting or removing a step re-points every key below it. Rather than
      // show a result under the wrong card, drop them whenever the shape changes.
      if (newSteps.length !== steps.items.length) {
        setStepRunResults({});
        setStepRunStates({});
      }
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
  const scenarioVariablesRef = useRef<Record<string, any>>(scenarioVariables);
  const scenarioVariableHydrationKeyRef = useRef<string | null>(null);
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
  // Image templates are stored under a per-scenario prefix, and this screen
  // edits scenarios in two shapes: one owned by a campaign (editingContext) and
  // a standalone org one. `activeScenarioId` only covers the first, so cropping
  // silently had no home to save to while editing an org scenario.
  const templateScenarioId =
    activeScenarioId ?? save.orgScenarioContext?.scenarioId ?? null;
  // Grabber installed by DeviceScreen: reads the frame already on screen so
  // cropping a tap_image template needs no backend screenshot round trip.
  const captureFrameRef = useRef<(() => string | null) | null>(null);
  const [regionSelecting, setRegionSelecting] = useState(false);
  // Frame pinned when selection starts — what the user drags on is what gets
  // cut, instead of a frame grabbed a moment later from a moving stream.
  const [frozenFrame, setFrozenFrame] = useState<string | null>(null);
  const regionResolverRef = useRef<
    ((rect: RegionSelectRect | null) => void) | null
  >(null);

  const settleRegion = useCallback((rect: RegionSelectRect | null) => {
    regionResolverRef.current?.(rect);
    regionResolverRef.current = null;
    setRegionSelecting(false);
    setFrozenFrame(null);
  }, []);

  /**
   * Drag a rectangle on the mirror; resolves with the ratios plus the frame
   * they were drawn on, so callers cut the pixels the user actually saw.
   */
  const requestRegionRect = useCallback((hintToast: string) => {
    // A pending request is abandoned, not queued: the user just asked for a
    // different one and only the newest can own the mirror.
    regionResolverRef.current?.(null);
    const frame = captureFrameRef.current?.() ?? null;
    setFrozenFrame(frame);
    setRegionSelecting(true);
    toast.info(hintToast);
    return new Promise<{ rect: RegionSelectRect; frame: string | null } | null>(
      (resolve) => {
        regionResolverRef.current = (rect) =>
          resolve(rect ? { rect, frame } : null);
      }
    );
  }, []);

  const regionSelect = useMemo<RegionSelect>(
    () => ({
      active: regionSelecting,
      onComplete: (rect) => settleRegion(rect),
      onCancel: () => settleRegion(null),
      hint: 'Kéo chọn vùng trên màn hình. Nhấn Esc để huỷ.',
      frozenFrame
    }),
    [regionSelecting, settleRegion, frozenFrame]
  );

  // Shared by both step editors on this screen: the graph detail panel gets it
  // as a prop, the step-list one through the image-template context (it sits
  // under FlowEditor, which has no prop for this).
  // Always defined: hiding the button when there is nowhere to save left the
  // user hunting for a control that had silently disappeared. Say why instead.
  const requestCropImage =
    useCallback(async (): Promise<ImageTemplatePick | null> => {
      if (!templateScenarioId) {
        toast.warning(
          'Lưu kịch bản trước đã — ảnh mẫu được lưu kèm theo kịch bản.'
        );
        return null;
      }
      if (!captureFrameRef.current?.()) {
        toast.warning(
          'Chưa lấy được hình từ mirror — đợi hình hiện lên rồi thử lại.'
        );
        return null;
      }
      // Cut on the mirror itself rather than in a dialog: the phone view is right
      // there, and it matches how selector/coordinate picking already works here.
      const picked = await requestRegionRect(
        'Kéo chọn vùng cần nhận diện trên màn hình điện thoại.'
      );
      if (!picked) return null;
      const { rect, frame } = picked;

      // Cut the frozen frame, not a fresh grab: the ratios were drawn against
      // that image, and it covers the whole screen so they index its pixels.
      if (!frame) {
        toast.warning('Chưa lấy được hình từ mirror — thử lại.');
        return null;
      }
      try {
        const img = new Image();
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = () => reject(new Error('decode failed'));
          img.src = frame;
        });
        const x = Math.round(rect.rx1 * img.naturalWidth);
        const y = Math.round(rect.ry1 * img.naturalHeight);
        const w = Math.max(
          1,
          Math.round((rect.rx2 - rect.rx1) * img.naturalWidth)
        );
        const h = Math.max(
          1,
          Math.round((rect.ry2 - rect.ry1) * img.naturalHeight)
        );
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        if (!ctx) throw new Error('no 2d context');
        ctx.drawImage(img, x, y, w, h, 0, 0, w, h);
        const preview = canvas.toDataURL('image/png');
        const blob = await new Promise<Blob | null>((resolve) =>
          canvas.toBlob(resolve, 'image/png')
        );
        if (!blob) throw new Error('encode failed');
        const out = await orgScenariosApi.uploadImageTemplate(
          templateScenarioId,
          blob,
          { w: img.naturalWidth, h: img.naturalHeight }
        );
        toast.success('Đã gắn ảnh mẫu cho bước.');
        return {
          templateKey: out.template_key,
          screenW: out.screen_w ?? img.naturalWidth,
          screenH: out.screen_h ?? img.naturalHeight,
          preview,
          warning: out.warning
        };
      } catch (e) {
        toast.error(
          e instanceof Error ? e.message : 'Không lưu được ảnh mẫu, thử lại.'
        );
        return null;
      }
    }, [requestRegionRect, templateScenarioId]);

  /** Bound an OCR read to one area — same drag, rectangle kept as-is. */
  const requestRegion = useCallback(async (): Promise<MirrorRegion | null> => {
    const picked = await requestRegionRect(
      'Kéo chọn vùng cần đọc chữ trên màn hình điện thoại.'
    );
    if (!picked) return null;
    const { rect } = picked;
    const round = (v: number) => Math.round(v * 1000) / 1000;
    return {
      x1: round(rect.rx1),
      y1: round(rect.ry1),
      x2: round(rect.rx2),
      y2: round(rect.ry2)
    };
  }, [requestRegionRect]);

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
  const activeCampaignName = campaignRecoveryQuery.data?.name ?? null;
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
  const scenarioVariableNames = useMemo(
    () =>
      Object.keys(scenarioVariablesWithDeviceKeys)
        .filter((key) => key.trim())
        .sort((a, b) => a.localeCompare(b)),
    [scenarioVariablesWithDeviceKeys]
  );
  const scenarioVariableReferences = useMemo(
    () => collectScenarioVariableReferences(steps.items),
    [steps.items]
  );
  const pageSummary = useMemo(
    () =>
      buildControlRecordPageSummary(
        scenarioVariablesWithDeviceKeys,
        Boolean(activeCampaignId),
        activeCampaignName,
        scenarioVariableReferences
      ),
    [
      scenarioVariablesWithDeviceKeys,
      activeCampaignId,
      activeCampaignName,
      scenarioVariableReferences
    ]
  );
  const pageSummaryWarningText = useMemo(
    () =>
      [pageSummary?.warning, pageSummary?.usageWarning]
        .filter((message): message is string => Boolean(message))
        .join(' · '),
    [pageSummary]
  );
  useEffect(() => {
    scenarioVariablesRef.current = scenarioVariables;
  }, [scenarioVariables]);
  const handleScenarioVariablesChange = useCallback(
    (next: Record<string, any>) => {
      const rename = detectSingleVariableRename(
        scenarioVariablesRef.current,
        next
      );
      scenarioVariablesRef.current = next;
      setScenarioVariables(next);
      if (!rename) return;

      const nextSteps = replaceScenarioVariableReferences(
        stepsItemsRef.current,
        rename
      ) as typeof steps.items;
      stepsItemsRef.current = nextSteps;
      flowStepsRef.current = nextSteps;
      steps.setItems(nextSteps);
      setFlowDetailStep((current) =>
        current ? replaceScenarioVariableReferences(current, rename) : current
      );
    },
    [steps]
  );
  const syncDeviceVarKeysIntoScenarioVariables = useCallback(() => {
    const next = mergeDeclaredDeviceVarKeys(
      scenarioVariables,
      declaredDeviceVarKeys
    );
    if (next !== scenarioVariables) setScenarioVariables(next);
    return next;
  }, [scenarioVariables, declaredDeviceVarKeys]);
  const canPersistScenarioVariables = Boolean(
    save.templateContext || save.editingContext || save.orgScenarioContext
  );
  const saveScenarioVariablesMutation = useMutation({
    mutationFn: async (draft: Record<string, any>) => {
      const next = mergeDeclaredDeviceVarKeys(draft, declaredDeviceVarKeys);
      const rename = detectSingleVariableRename(
        scenarioVariablesRef.current,
        next
      );
      const renamedSteps = rename
        ? (replaceScenarioVariableReferences(
            flushPendingFlowDetailStep(),
            rename
          ) as typeof steps.items)
        : null;
      const payloadSteps =
        renamedSteps && renamedSteps.length > 0
          ? sanitizeScenarioStepsForApi(renamedSteps)
          : null;

      if (payloadSteps) {
        const check = validateScenarioStepsForApi(payloadSteps);
        if (!check.ok) {
          throw new Error(check.message);
        }
      }

      if (save.templateContext) {
        const payload: Parameters<typeof scenarioTemplatesApi.update>[1] = {
          variables: next,
          ...(payloadSteps ? { steps: payloadSteps } : {})
        };
        await scenarioTemplatesApi.update(
          save.templateContext.templateId,
          payload
        );
        void queryClient.invalidateQueries({
          queryKey: ['scenario-templates']
        });
        void queryClient.invalidateQueries({
          queryKey: ['scenario-templates', save.templateContext.templateId]
        });
        return next;
      }

      if (savingOrgScenario && save.orgScenarioContext) {
        if (activeCampaignId) {
          const detail = await campaignsApi.patchEntity(activeCampaignId, {
            vars: next
          });
          syncCampaignDetailCaches(queryClient, activeCampaignId, detail);
          return next;
        }

        const scenarioId = (initialOrgScenarioId ?? '').trim();
        if (!scenarioId) {
          throw new Error(tVar('saveUnavailable'));
        }
        const bodyPayload = payloadSteps
          ? buildOrgScenarioBodyPayload(payloadSteps, next, save.requirements)
          : await orgScenariosApi.getBody(scenarioId).then((body) => {
              const bodyJson = (body.body_json ?? {}) as Record<string, any>;
              return {
                ...(Array.isArray(bodyJson.steps)
                  ? { steps: bodyJson.steps as Record<string, any>[] }
                  : {}),
                ...(Array.isArray(bodyJson.nodes)
                  ? { nodes: bodyJson.nodes as Record<string, any>[] }
                  : {}),
                ...(Array.isArray(bodyJson.edges)
                  ? { edges: bodyJson.edges as Record<string, any>[] }
                  : {}),
                variables: next,
                requirements:
                  typeof bodyJson.requirements === 'object' &&
                  bodyJson.requirements !== null
                    ? bodyJson.requirements
                    : save.requirements
              };
            });
        const saved = await orgScenariosApi.saveBody(scenarioId, bodyPayload);
        queryClient.setQueryData(['org-scenarios', scenarioId, 'body'], saved);
        void queryClient.invalidateQueries({
          queryKey: ['org-scenarios', scenarioId]
        });
        void queryClient.invalidateQueries({
          queryKey: ['org-scenarios', scenarioId, 'body']
        });
        void queryClient.invalidateQueries({ queryKey: ['org-scenarios'] });
        return next;
      }

      if (save.editingContext) {
        const payload: Parameters<typeof scenariosApi.update>[2] = {
          variables: next,
          requirements: save.requirements
        };
        if (payloadSteps) {
          const payloadGraph = stepsToGraph(payloadSteps);
          payload.steps = payloadSteps;
          payload.nodes = payloadGraph.nodes;
          payload.edges = payloadGraph.edges;
        }
        const updated = await scenariosApi.update(
          save.editingContext.campaignId,
          save.editingContext.scenarioId,
          payload
        );
        syncSavedScenarioCaches(
          queryClient,
          save.editingContext.campaignId,
          updated
        );
        return next;
      }

      return next;
    },
    onSuccess: (next) => {
      handleScenarioVariablesChange(next);
      toast.success(
        canPersistScenarioVariables ? tVar('saveSuccess') : tVar('applySuccess')
      );
    },
    onError: (err) => {
      toast.error(formatFarmApiError(err, tVar('saveFailed')));
    }
  });
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
  const scenarioLintInitialVariables = useMemo(() => {
    const names = new Set<string>();
    for (const key of Object.keys(scenarioVariablesWithDeviceKeys)) {
      if (key.trim()) names.add(key);
    }
    for (const key of Object.keys(inlineScenarioDeviceVars ?? {})) {
      if (key.trim()) names.add(key);
    }
    return Array.from(names);
  }, [scenarioVariablesWithDeviceKeys, inlineScenarioDeviceVars]);
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
  const { data: selectedAccountLinks = [], isLoading: accountLinksLoading } =
    useDeviceAccounts(selectedDeviceId ?? '');
  const selectedPrimaryLink = selectedAccountLinks.find(
    (link) => link.is_primary
  );
  const { data: selectedPrimaryAccount, isLoading: primaryAccountLoading } =
    useAccount(selectedPrimaryLink?.account_id ?? '');
  const {
    data: selectedPlatformSession,
    isLoading: platformSessionLoading,
    isError: platformSessionError
  } = useFacebookPlatformSession(
    selectedPrimaryAccount?.platform === 'facebook'
      ? (selectedDeviceId ?? '')
      : ''
  );
  const sessionGateRuntimeContext = {
    deviceLabel: selectedDeviceLabel || selectedDeviceForControl?.serial || '',
    deviceId: selectedDeviceId ?? null,
    platform: selectedPrimaryAccount?.platform ?? null,
    accountLabel: selectedPrimaryAccount
      ? selectedPrimaryAccount.display_name || selectedPrimaryAccount.username
      : null,
    sessionState:
      selectedPrimaryAccount?.platform === 'facebook'
        ? (selectedPlatformSession?.state ?? null)
        : null,
    loading:
      accountLinksLoading ||
      primaryAccountLoading ||
      (selectedPrimaryAccount?.platform === 'facebook' &&
        platformSessionLoading),
    error: platformSessionError
  };
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
  const flowVariablePreviewValues = useMemo(
    () => ({
      ...deviceVarGlobalPreview,
      ...(inlineScenarioDeviceVars ?? {})
    }),
    [deviceVarGlobalPreview, inlineScenarioDeviceVars]
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
      const key = `campaign:${save.editingContext.campaignId}:${save.editingContext.scenarioId}`;
      if (scenarioVariableHydrationKeyRef.current === key) return;
      scenarioVariableHydrationKeyRef.current = key;
      const next = flattenVarDefs(save.editingContext.variables);
      scenarioVariablesRef.current = next;
      setScenarioVariables(next);
    }
  }, [save.editingContext]);

  useEffect(() => {
    if (save.editingContext?.variables) return;
    if (save.orgScenarioContext?.variables) {
      const key = `org:${save.orgScenarioContext.scenarioId}:${activeCampaignId ?? 'standalone'}`;
      if (scenarioVariableHydrationKeyRef.current === key) return;
      scenarioVariableHydrationKeyRef.current = key;
      const next = flattenVarDefs(save.orgScenarioContext.variables);
      scenarioVariablesRef.current = next;
      setScenarioVariables(next);
    }
  }, [activeCampaignId, save.editingContext, save.orgScenarioContext]);

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
    if (!showFlowUi) return;
    if (flowDetailSyncingRef.current) return;
    if (steps.items === flowStepsRef.current) return;

    const nextSteps = steps.items as FlowStep[];
    const ctx = flowCtxRef.current;
    flowStepsRef.current = steps.items;
    if (!ctx) {
      setFlowCanvasKey((k) => k + 1);
      return;
    }

    try {
      flowDetailSyncingRef.current = true;
      const synced = applyStepsToFlowgramDocument(ctx, nextSteps);
      flowStepsRef.current = synced as typeof steps.items;
      if (synced !== steps.items) steps.setItems(synced as typeof steps.items);
    } catch (e) {
      toast.error(`Không đồng bộ được canvas: ${String(e)}`);
    } finally {
      flowDetailSyncingRef.current = false;
    }
    // steps is a hook handle object; the sync only depends on the item array and setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showFlowUi, steps.items, steps.setItems]);

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

  const formatScenarioLintIssue = useCallback(
    (issue: ScenarioLintPreflightResult['issues'][number], index: number) => {
      return tScenarioLintPreflight(`issues.${issue.kind}`, {
        index: index + 1,
        variable: issue.variable,
        source: issue.source,
        producerStepType: issue.producerStepType ?? '',
        producerPathKey: issue.producerPathKey ?? ''
      });
    },
    [tScenarioLintPreflight]
  );

  const confirmScenarioLintPreflight = useCallback(
    async (result: ScenarioLintPreflightResult, context: string) => {
      if (!result.issues.length) return true;

      if (!result.hasCritical) {
        const summary = scenarioLintSummary(result.warningIssues, {
          moreLabel: (count) =>
            tScenarioLintPreflight('summaryMore', { count }),
          formatIssue: formatScenarioLintIssue
        });
        toast.warning(tScenarioLintPreflight('warningToast', { summary }));
        return true;
      }

      const summary = scenarioLintSummary(result.criticalIssues, {
        moreLabel: (count) => tScenarioLintPreflight('summaryMore', { count }),
        formatIssue: formatScenarioLintIssue
      });
      return confirm({
        title: tScenarioLintPreflight('confirmTitle'),
        description: tScenarioLintPreflight('confirmDescription', {
          context,
          count: result.criticalIssues.length,
          summary
        }),
        confirmText: tScenarioLintPreflight('confirmRun'),
        cancelText: tScenarioLintPreflight('cancelRun'),
        confirmVariant: 'destructive',
        zIndex: 10_000
      });
    },
    [confirm, formatScenarioLintIssue, tScenarioLintPreflight]
  );

  const ensureScenarioCapabilityPreflight = useCallback(
    async (serial: string, scenario: Record<string, unknown>) => {
      setScenarioPreflightChecking(true);
      try {
        const result = await scenarioDeviceCapabilitiesApi.preflight(
          serial,
          scenario
        );
        setScenarioPreflight(result);
        if (!result.preflight.ok) {
          const summary = scenarioCapabilityIssueSummary(result.preflight, {
            moreLabel: (count) => tCapabilityPreflight('summaryMore', { count })
          });
          toast.error(
            summary
              ? tCapabilityPreflight('stepBlockedToast', { summary })
              : tCapabilityPreflight('stepBlockedToastFallback')
          );
          return false;
        }
        const warning = scenarioCapabilityWarningSummary(result.preflight, {
          moreLabel: (count) => tCapabilityPreflight('summaryMore', { count })
        });
        if (warning) {
          toast.warning(
            tCapabilityPreflight('warningToast', { summary: warning })
          );
        }
        return true;
      } catch (error) {
        toast.error(
          formatFarmApiError(error, tCapabilityPreflight('stepFailedFallback'))
        );
        return false;
      } finally {
        setScenarioPreflightChecking(false);
      }
    },
    [tCapabilityPreflight]
  );

  const handleFlowRunLeaf = useCallback(
    async (fgId: string, step: FlowStep) => {
      const serial = selectedDeviceForControl?.serial?.trim();
      if (!serial) {
        toast.warning(t('workbench.noDeviceTitle'));
        return;
      }
      if (flowRunningFgIdsRef.current.has(fgId)) return;
      const payload = preparePreviewStepPayload(step);
      const lintOk = await confirmScenarioLintPreflight(
        scenarioLintPreflightForSteps(
          [payload as FlowStep],
          scenarioLintInitialVariables
        ),
        tScenarioLintPreflight('flowLeafContext')
      );
      if (!lintOk) return;
      flowRunningFgIdsRef.current.add(fgId);
      const preflightOk = await ensureScenarioCapabilityPreflight(serial, {
        steps: [payload]
      });
      if (!preflightOk) {
        flowRunningFgIdsRef.current.delete(fgId);
        setFlowRunStates((s) => ({ ...s, [fgId]: 'error' }));
        setTimeout(() => {
          setFlowRunStates((s) => {
            const n = { ...s };
            if (n[fgId] !== 'running') delete n[fgId];
            return n;
          });
        }, 2800);
        return;
      }
      setFlowRunStates((s) => ({ ...s, [fgId]: 'running' }));
      flowRunLeafAbortRef.current?.abort();
      const ctrl = new AbortController();
      flowRunLeafAbortRef.current = ctrl;
      const runId = previewSession.beginRun();
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
      selectedDeviceForControl?.serial,
      scenarioVariablesWithDeviceKeys,
      inlineScenarioDeviceVars,
      scenarioLintInitialVariables,
      previewSession,
      confirmScenarioLintPreflight,
      t,
      tScenarioLintPreflight,
      ensureScenarioCapabilityPreflight
    ]
  );

  const commitFlowDetailStep = useCallback(
    (fgId: string, latest: FlowStep) => {
      const current = stepsItemsRef.current as FlowStep[];
      const patched = patchStepByFlowgramId(current, fgId, latest);
      const ctx = flowCtxRef.current;
      if (!ctx) {
        flowStepsRef.current = patched as typeof steps.items;
        steps.setItems(patched as typeof steps.items);
        return patched as typeof steps.items;
      }

      try {
        if (!pushScenarioNodeDataUpdate(ctx, fgId, latest)) {
          flowStepsRef.current = patched as typeof steps.items;
          steps.setItems(patched as typeof steps.items);
        }
        return patched as typeof steps.items;
      } catch (e) {
        toast.error(`Không áp dụng được lên canvas: ${String(e)}`);
        return current as typeof steps.items;
      }
    },
    [steps]
  );

  const handleFlowDetailChange = useCallback(
    (next: FlowStep) => {
      const fgId = flowSelectedFgIdRef.current;
      const previousFgId = flowDetailPendingFgIdRef.current;
      const previousStep = flowDetailPendingRef.current;
      if (previousFgId && previousStep && previousFgId !== fgId) {
        if (flowDetailDebounceRef.current) {
          clearTimeout(flowDetailDebounceRef.current);
          flowDetailDebounceRef.current = null;
        }
        commitFlowDetailStep(previousFgId, previousStep);
      }

      const cloned = JSON.parse(JSON.stringify(next)) as FlowStep;
      flowDetailPendingRef.current = cloned;
      flowDetailPendingFgIdRef.current = fgId;
      setFlowDetailStep(cloned);
      if (flowDetailDebounceRef.current) {
        clearTimeout(flowDetailDebounceRef.current);
      }
      flowDetailDebounceRef.current = setTimeout(() => {
        flowDetailDebounceRef.current = null;
        const pendingFgId = flowDetailPendingFgIdRef.current;
        const latest = flowDetailPendingRef.current;
        flowDetailPendingFgIdRef.current = null;
        flowDetailPendingRef.current = null;
        if (!pendingFgId || !latest) return;
        commitFlowDetailStep(pendingFgId, latest);
      }, 240);
    },
    [commitFlowDetailStep]
  );

  const flushPendingFlowDetailStep = useCallback(() => {
    const current = stepsItemsRef.current as FlowStep[];
    if (flowDetailDebounceRef.current) {
      clearTimeout(flowDetailDebounceRef.current);
      flowDetailDebounceRef.current = null;
    }

    const fgId = flowDetailPendingFgIdRef.current;
    const latest = flowDetailPendingRef.current;
    flowDetailPendingFgIdRef.current = null;
    flowDetailPendingRef.current = null;
    if (!fgId || !latest) return current as typeof steps.items;

    return commitFlowDetailStep(fgId, latest);
  }, [commitFlowDetailStep, steps]);

  const lintCurrentScenarioBeforePersist = useCallback(
    async (context: string): Promise<FlowStep[] | null> => {
      const latestSteps = flushPendingFlowDetailStep() as FlowStep[];
      const lintOk = await confirmScenarioLintPreflight(
        scenarioLintPreflightForSteps(
          latestSteps,
          scenarioLintInitialVariables
        ),
        context
      );
      return lintOk ? latestSteps : null;
    },
    [
      confirmScenarioLintPreflight,
      flushPendingFlowDetailStep,
      scenarioLintInitialVariables
    ]
  );

  const flowWorkbench = useMemo(
    () => ({
      deviceSerial: selectedDeviceForControl?.serial ?? null,
      setSelectedFgId: setFlowSelectedFgId,
      runStates: flowRunStates,
      onRunLeafStep: handleFlowRunLeaf
    }),
    [selectedDeviceForControl?.serial, flowRunStates, handleFlowRunLeaf]
  );

  const handleRunStep = useCallback(
    async (step: FlowStep, runKey: string) => {
      const serial = selectedDeviceForControl?.serial?.trim();
      if (!serial) {
        toast.warning(t('workbench.noDeviceTitle'));
        return;
      }
      if (stepRunStates[runKey] === 'running') return;
      const label = /^\d+$/.test(runKey)
        ? `Bước ${Number(runKey) + 1}`
        : 'Bước';
      // Ref synced every render — always read tree after mirror pick, not stale StepCard closure.
      const payload = prepareInlinePreviewStep(
        stepsItemsRef.current as FlowStep[],
        runKey,
        step
      );
      const lintOk = await confirmScenarioLintPreflight(
        scenarioLintPreflightForInlineRun(
          stepsItemsRef.current as FlowStep[],
          runKey,
          payload as FlowStep,
          scenarioLintInitialVariables
        ),
        tScenarioLintPreflight('inlineStepContext')
      );
      if (!lintOk) return;
      const preflightOk = await ensureScenarioCapabilityPreflight(serial, {
        steps: [payload]
      });
      if (!preflightOk) {
        setStepRunStates((s) => ({ ...s, [runKey]: 'error' }));
        setTimeout(
          () =>
            setStepRunStates((s) => {
              const n = { ...s };
              delete n[runKey];
              return n;
            }),
          3000
        );
        return;
      }
      stepRunAbortRef.current?.abort();
      const ctrl = new AbortController();
      stepRunAbortRef.current = ctrl;
      const runId = previewSession.beginRun();
      setStepRunStates((s) => ({ ...s, [runKey]: 'running' }));
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
              // The engine writes machine reasons (`platform_session_gate
              // preflight blocked: …`) into step messages; the author reading
              // this toast cannot act on those.
              const rawMessage = event.message as string | undefined;
              const stepMessage =
                humanizeSessionGateMessage(rawMessage, tGate) ?? rawMessage;
              // Keep what the step produced so the card can show it — a green
              // tick alone never told the author what was actually read.
              setStepRunResults((s) => ({
                ...s,
                [runKey]: {
                  ok: !!event.ok,
                  message: stepMessage,
                  savedAs: event.saved_as as string | undefined,
                  textPreview: event.text_preview as string | undefined,
                  textLength: event.text_length as number | undefined,
                  textTruncated: event.text_truncated as boolean | undefined,
                  boxCount: event.box_count as number | undefined
                }
              }));
              if (!event.ok) toast.error(`${label}: ${stepMessage ?? 'Lỗi'}`);
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
      selectedDeviceForControl?.serial,
      stepRunStates,
      scenarioVariablesWithDeviceKeys,
      inlineScenarioDeviceVars,
      scenarioLintInitialVariables,
      previewSession,
      confirmScenarioLintPreflight,
      ensureScenarioCapabilityPreflight,
      t,
      tScenarioLintPreflight,
      tGate
    ]
  );

  const runDeviceOpStep = useCallback(
    async (step: FlowStep) => {
      const serial = selectedDeviceForControl?.serial?.trim();
      if (!serial) {
        toast.warning(t('workbench.noDeviceTitle'));
        return;
      }
      const payload = preparePreviewStepPayload(step);
      const lintOk = await confirmScenarioLintPreflight(
        scenarioLintPreflightForSteps(
          [payload as FlowStep],
          scenarioLintInitialVariables
        ),
        tScenarioLintPreflight('deviceOpContext')
      );
      if (!lintOk) return;
      const preflightOk = await ensureScenarioCapabilityPreflight(serial, {
        steps: [payload]
      });
      if (!preflightOk) return;
      const runId = previewSession.beginRun();
      try {
        await previewScenarioStream(
          serial,
          [payload],
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
      selectedDeviceForControl?.serial,
      inlineScenarioDeviceVars,
      scenarioLintInitialVariables,
      previewSession,
      confirmScenarioLintPreflight,
      ensureScenarioCapabilityPreflight,
      t,
      tScenarioLintPreflight,
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
    async (rx: number, ry: number) => {
      const needsFreshXml = needsFreshMirrorSelectorXml({
        selectorPickTarget,
        flowSelectorPickFgId
      });
      const interactionXml =
        needsFreshXml && selectedDeviceSerial
          ? await fetchFreshHierarchy(selectedDeviceSerial, true, {
              allowSerialMismatch: true,
              bypassBackoff: true,
              bypassInFlight: true
            }).catch(() => '')
          : hierarchyXml;

      const tree = parseHierarchyTree(interactionXml);
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
          interactionXml,
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
          interactionXml,
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
      fetchFreshHierarchy,
      selectedDeviceSerial,
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
    const selectorPickingFromMirror =
      selectorPickTarget != null || flowSelectorPickFgId != null;
    if (selectorPickingFromMirror) {
      return { hideControls: false, readOnlyPreview: true };
    }
    const pickingFromMirror =
      coordinatePickTarget != null || flowCoordPick != null;
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
    const d = selectedDeviceForControl;
    if (!d) return undefined;
    return {
      disabled: mirrorInputLocked.readOnlyPreview,
      defaultPackage: packageFromCurrentApp(d.current_app),
      onRunStep: runDeviceOpStep,
      onRunShell: (cmd) => runAgentShell(d.serial, cmd),
      // Chạy qua preview-stream như mọi device op khác: REST đồng bộ giữ request
      // mở suốt lúc tải + cài (tới 600s) và bị Cloudflare cắt ở ~100s -> 502.
      // download_url là presigned R2 nên máy tải thẳng, không qua origin.
      onInstallStandardFacebookApk: async () => {
        const { data } = await farmApi.get(
          '/platform-apps/facebook/current/download-url'
        );
        await runDeviceOpStep({
          type: 'install_apk',
          url: data.download_url,
          timeout: 600,
          verify_package: 'com.facebook.katana'
        });
        return data;
      }
    };
  }, [
    selectedDeviceForControl,
    mirrorInputLocked.readOnlyPreview,
    runDeviceOpStep
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
    deviceLabel: t('deviceLabel'),
    deviceCampaignBadge: t('deviceCampaignBadge'),
    wsConnected: t('wsConnected'),
    wsDisconnected: t('wsDisconnected')
  };

  const handlePrimarySave = async () => {
    if (!canPersistScenario(childStepEditorOpen)) {
      toast.info(
        'Đóng trình chỉnh sửa bước để áp dụng thay đổi trước khi lưu.'
      );
      return;
    }
    if (savingOrgScenario) {
      void handleSaveOrgScenario();
      return;
    }

    const latestSteps = await lintCurrentScenarioBeforePersist(
      tScenarioLintPreflight('saveContext')
    );
    if (!latestSteps) return;
    const nextVariables = syncDeviceVarKeysIntoScenarioVariables();
    if (save.templateContext) {
      await save.saveToTemplate(nextVariables);
      return;
    }
    const created = await save.saveAsNewOrgScenario(nextVariables);
    if (!created?.id) return;
    router.push(ROUTES.ORG_SCENARIOS.DETAIL(created.id));
  };

  const handleSaveAsNewCampaignScenario = async () => {
    const latestSteps = await lintCurrentScenarioBeforePersist(
      tScenarioLintPreflight('saveContext')
    );
    if (!latestSteps) return;
    await save.saveAsNew(
      save.selectedCampaignId!,
      syncDeviceVarKeysIntoScenarioVariables(),
      saveAccountGroupId || null
    );
  };

  const handleSaveToCampaignScenario = async (scenarioId: string) => {
    const latestSteps = await lintCurrentScenarioBeforePersist(
      tScenarioLintPreflight('saveContext')
    );
    if (!latestSteps) return;
    await save.saveTo(
      save.selectedCampaignId!,
      scenarioId,
      syncDeviceVarKeysIntoScenarioVariables(),
      saveAccountGroupId || null
    );
  };

  const scenarioPreflightProblem =
    scenarioPreflightChecking || scenarioPreflight
      ? {
          state: scenarioPreflightChecking
            ? ('checking' as const)
            : scenarioPreflight && !scenarioPreflight.preflight.ok
              ? ('blocked' as const)
              : ('ready' as const),
          title: scenarioPreflightChecking
            ? tCapabilityPreflight('checkingTitle')
            : scenarioPreflight?.preflight.ok
              ? tCapabilityPreflight('stepOkTitle')
              : tCapabilityPreflight('stepBlockedTitle'),
          description: scenarioPreflight?.preflight.ok
            ? scenarioCapabilityWarningSummary(scenarioPreflight.preflight, {
                moreLabel: (count) =>
                  tCapabilityPreflight('summaryMore', { count })
              }) || tCapabilityPreflight('stepReadyDescription')
            : scenarioPreflight
              ? scenarioCapabilityIssueSummary(scenarioPreflight.preflight, {
                  moreLabel: (count) =>
                    tCapabilityPreflight('summaryMore', { count })
                }) || tCapabilityPreflight('stepMissingDescription')
              : tCapabilityPreflight('checkingStepDescription')
        }
      : null;
  const workbenchMode = playerMode ? 'run' : 'build';
  const workbenchPhoneTitle = selectedDevice
    ? selectedDevice.name || selectedDevice.serial
    : t('workbench.noDeviceTitle');
  const workbenchPhoneMeta = selectedDevice
    ? `${selectedDevice.serial} · ${selectedDevice.state || 'UNKNOWN'}`
    : undefined;
  const workbenchSequenceTitle = playerMode
    ? t('workbench.runTitle')
    : showFlowUi
      ? t('workbench.flowTitle')
      : t('workbench.listTitle');
  const workbenchSequenceMeta = playerMode
    ? t('workbench.runMeta')
    : showFlowUi
      ? t('workbench.flowMeta', { count: steps.items.length })
      : t('workbench.listMeta', { count: steps.items.length });
  const editorToolbar = (
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
      onSave={() => void handlePrimarySave()}
      saveDisabled={
        steps.items.length === 0 ||
        !canSaveWork ||
        save.saving !== null ||
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
              ? t('workbench.saving')
              : t('workbench.save')
            : save.saving === 'org-new'
              ? t('workbench.saving')
              : t('workbench.save')
      }
      onOpenVariables={() => setVarDialogOpen(true)}
      variableCount={Object.keys(scenarioVariablesWithDeviceKeys).length}
      pageSummary={pageSummary?.contextLabel}
      pageSummaryWarning={pageSummaryWarningText || undefined}
      showRecovery={!editingRecoveryScenario}
      recoveryEnabled={recoveryPolicyEnabled}
      onOpenRecovery={() => setRecoveryDialogOpen(true)}
      onOpenDeviceVars={() => setDeviceVarDialogOpen(true)}
      deviceVarsEnabled={Boolean(
        hasEnabledDeviceVars && canManageDeviceVars && selectedDeviceId
      )}
      deviceVarsDisabled={!canOpenDeviceVarsDialog}
      onOpenRequirements={() => setRequirementsDialogOpen(true)}
      requirementsEnabled={scenarioRequiresPlatformSession(save.requirements)}
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
      variant='workbench'
      labels={{
        closePickerTitle: t('multiControl.closePicker'),
        deviceActionsLabel: t('workbench.deviceActionsLabel'),
        deviceActionsHint: t('workbench.deviceActionsHint'),
        startRecording: t('startRecording'),
        stopRecording: t('stopRecording'),
        tryRun: t('workbench.tryRunOnDevice'),
        busyTitle: t('workbench.deviceBusyTryRun'),
        jsonTooltip: t('workbench.jsonTooltip'),
        variables: t('variablesLabel'),
        variablesTooltip:
          pageSummary?.settingsText ??
          t('workbench.variablesTooltip', { variable: '${VAR}' }),
        recoveryTitle: tRecovery('controlRecordTitle'),
        recoveryEnabledBadge: tRecovery('enabledBadge'),
        recoveryTooltip: activeCampaignId
          ? tRecovery('controlRecordTooltip')
          : tRecovery('controlRecordNoCampaignTooltip'),
        deviceVars: t('workbench.deviceVars'),
        deviceVarsTooltip: !canManageDeviceVars
          ? savingOrgScenario
            ? t('workbench.deviceVarsTooltip.reopenCampaign')
            : t('workbench.deviceVarsTooltip.openInCampaign')
          : !hasCampaignDevices
            ? t('workbench.deviceVarsTooltip.addDeviceFirst')
            : t('workbench.deviceVarsTooltip.attachedTo', {
                device: selectedDeviceLabel
              }),
        requirements: tRequirements('title'),
        requirementsTooltip: tRequirements(
          scenarioRequiresPlatformSession(save.requirements)
            ? 'summarySessionHint'
            : 'summaryNoSessionHint'
        ),
        requirementsEnabledBadge: tRequirements('sessionToggleLabel'),
        helpTooltip: t('tooltipScenarioSection'),
        flowSwitchToList: t('flowSwitchToList'),
        flowSwitchToFlow: t('flowSwitchToFlow'),
        flowListLabel: t('flowListLabel'),
        flowFlowLabel: t('flowFlowLabel'),
        settings: t('settings')
      }}
    />
  );

  const content = (
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
      />

      {!selectedDevice ? (
        <div className='flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-4 py-8'>
          <div className='w-full max-w-3xl text-center'>
            <div className='mx-auto flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/15'>
              <Smartphone className='size-7' />
            </div>
            <h2 className='mt-5 text-xl font-semibold tracking-tight'>
              {t('gettingStarted.title')}
            </h2>
            <p className='mx-auto mt-2 max-w-xl text-sm leading-6 text-muted-foreground'>
              {t('gettingStarted.description')}
            </p>
            {connectedDevicesForControl.length > 0 ? (
              <Button
                className='mt-6 min-w-40'
                onClick={() =>
                  document
                    .getElementById('control-record-device-select')
                    ?.click()
                }
              >
                <Smartphone className='mr-2 size-4' />
                {t('gettingStarted.selectDevice')}
              </Button>
            ) : (
              <Button asChild className='mt-6 min-w-40'>
                <Link href={ROUTES.DEVICES.MANAGE}>
                  <Plus className='mr-2 size-4' />
                  {t('addDevice')}
                </Link>
              </Button>
            )}

            <div className='mx-auto mt-10 grid max-w-2xl gap-3 text-left sm:grid-cols-3'>
              {[
                {
                  icon: Smartphone,
                  title: t('gettingStarted.deviceStepTitle'),
                  description: t('gettingStarted.deviceStepDescription')
                },
                {
                  icon: MousePointer2,
                  title: t('gettingStarted.createStepTitle'),
                  description: t('gettingStarted.createStepDescription')
                },
                {
                  icon: PlayCircle,
                  title: t('gettingStarted.finishStepTitle'),
                  description: t('gettingStarted.finishStepDescription')
                }
              ].map((item, index) => (
                <div
                  key={item.title}
                  className='rounded-xl border border-border/60 bg-card/60 p-4'
                >
                  <div className='flex items-center gap-2 text-sm font-medium'>
                    <span className='flex size-7 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground'>
                      {index + 1}
                    </span>
                    <item.icon className='size-4 text-primary' />
                    {item.title}
                  </div>
                  <p className='mt-2 text-xs leading-5 text-muted-foreground'>
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
            <div className='mt-4 inline-flex items-center gap-2 text-xs text-muted-foreground'>
              <Save className='size-3.5' />
              {t('gettingStarted.saveHint')}
            </div>
          </div>
        </div>
      ) : null}

      {selectedDevice && isMobile ? (
        <div className='flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-5 py-10 md:hidden'>
          <div className='max-w-sm text-center'>
            <div className='mx-auto flex size-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground ring-1 ring-border'>
              <Smartphone className='size-7' />
            </div>
            <h2 className='mt-5 text-lg font-semibold'>
              {t('smallScreen.title')}
            </h2>
            <p className='mt-2 text-sm leading-6 text-muted-foreground'>
              {t('smallScreen.description')}
            </p>
          </div>
        </div>
      ) : null}

      <ScenarioWorkbenchShell
        hasSelectedDevice={Boolean(selectedDevice)}
        showEditorPanel={showEditorPanel}
        hierarchyOpen={treePanelOpen}
        mode={workbenchMode}
        phoneTitle={workbenchPhoneTitle}
        phoneMeta={workbenchPhoneMeta}
        sequenceTitle={workbenchSequenceTitle}
        sequenceMeta={workbenchSequenceMeta}
        toolbar={editorToolbar}
        problem={scenarioPreflightProblem}
        hierarchy={
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
        }
        phone={
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
            captureFrameRef={captureFrameRef}
            regionSelect={regionSelect}
            hasMultiFollowers={hasMultiFollowers}
            multiFocusMode={multiFocusMode}
            selectedMultiFollowerDevices={selectedMultiFollowerDevices}
            onPromoteFollower={promoteMultiFollower}
            onOpenStepPicker={() => setStepPickerOpen(true)}
            fillWidth
            labels={{
              openPicker: t('multiControl.openPicker'),
              selectDevice: t('workbench.selectDeviceFromHeader')
            }}
          />
        }
      >
        <div className='flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background'>
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
                            aria-label={t('workbench.previousCandidate')}
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
                            aria-label={t('workbench.nextCandidate')}
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
                    {t('workbench.cancel')}
                  </button>
                </div>
              )}

              {coordinatePickTarget?.mode === 'tap_point' && (
                <div className='flex shrink-0 items-center gap-2 border-b border-sky-400/35 bg-sky-50/90 px-4 py-2 dark:bg-sky-950/25'>
                  <MousePointerClick className='size-3.5 shrink-0 text-sky-700 dark:text-sky-400' />
                  <p className='flex-1 text-[11px] text-sky-900 dark:text-sky-200'>
                    {t('workbench.tapCoordinateBanner')}
                  </p>
                  <button
                    type='button'
                    className='text-[10px] text-sky-800 underline underline-offset-2 hover:no-underline dark:text-sky-300'
                    onClick={() => setCoordinatePickTarget(null)}
                  >
                    {t('workbench.cancel')}
                  </button>
                </div>
              )}

              {coordinatePickTarget?.mode === 'swipe_segment' && (
                <div className='flex shrink-0 items-center gap-2 border-b border-sky-400/35 bg-sky-50/90 px-4 py-2 dark:bg-sky-950/25'>
                  <Move className='size-3.5 shrink-0 text-sky-700 dark:text-sky-400' />
                  <p className='flex-1 text-[11px] text-sky-900 dark:text-sky-200'>
                    {t('workbench.swipeCoordinateBanner')}
                  </p>
                  <button
                    type='button'
                    className='text-[10px] text-sky-800 underline underline-offset-2 hover:no-underline dark:text-sky-300'
                    onClick={() => setCoordinatePickTarget(null)}
                  >
                    {t('workbench.cancel')}
                  </button>
                </div>
              )}

              {showFlowUi && flowCoordPick && (
                <div className='flex shrink-0 items-center gap-2 border-b border-sky-400/35 bg-sky-50/90 px-4 py-2 dark:bg-sky-950/25'>
                  <MousePointerClick className='size-3.5 shrink-0 text-sky-700 dark:text-sky-400' />
                  <p className='flex-1 text-[11px] text-sky-900 dark:text-sky-200'>
                    {flowCoordPick.kind === 'tap'
                      ? t('workbench.flowTapCoordinateBanner')
                      : t('workbench.flowSwipeCoordinateBanner')}
                  </p>
                  <button
                    type='button'
                    className='text-[10px] text-sky-800 underline underline-offset-2 hover:no-underline dark:text-sky-300'
                    onClick={() => setFlowCoordPick(null)}
                  >
                    {t('workbench.cancel')}
                  </button>
                </div>
              )}

              {showFlowUi && flowSelectorPickFgId && (
                <div className='flex shrink-0 items-center gap-2 border-b border-amber-400/30 bg-amber-50/80 px-4 py-2 dark:bg-amber-950/20'>
                  <Crosshair className='size-3.5 shrink-0 text-amber-600' />
                  <p className='flex-1 text-[11px] text-amber-800 dark:text-amber-300'>
                    {t('workbench.flowSelectorBanner')}
                  </p>
                  <button
                    type='button'
                    className='text-[10px] text-amber-700 underline underline-offset-2 hover:no-underline dark:text-amber-400'
                    onClick={() => setFlowSelectorPickFgId(null)}
                  >
                    {t('workbench.cancel')}
                  </button>
                </div>
              )}

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
                    <div className='flex h-full min-h-[240px] flex-col overflow-hidden bg-background lg:flex-row'>
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
                            const selectedFgId = flowSelectedFgIdRef.current;
                            if (selectedFgId) {
                              const selected = findStepByFlowgramId(
                                newSteps,
                                selectedFgId
                              );
                              setFlowDetailStep(
                                selected
                                  ? (JSON.parse(
                                      JSON.stringify(selected)
                                    ) as FlowStep)
                                  : null
                              );
                            }
                          }}
                        />
                        {!flowDetailStep ? (
                          <div className='pointer-events-none absolute bottom-3 left-3 flex items-center gap-2 rounded-md border border-border/70 bg-background/95 px-3 py-2 text-xs text-muted-foreground shadow-sm backdrop-blur'>
                            <MousePointerClick className='size-3.5 shrink-0' />
                            <span>{t('workbench.selectStepToConfigure')}</span>
                          </div>
                        ) : null}
                      </div>
                      {flowDetailStep ? (
                        <div className='max-h-[min(42vh,360px)] w-full shrink-0 overflow-y-auto border-t border-border bg-background lg:max-h-none lg:w-[min(100%,360px)] lg:border-l lg:border-t-0'>
                          <StepDetailPanel
                            step={flowDetailStep}
                            onChange={handleFlowDetailChange}
                            nodeCapabilities={scenarioSchema?.node_capabilities}
                            deviceCapabilities={selectedDeviceCapabilities}
                            onClose={() => {
                              flushPendingFlowDetailStep();
                              const ctx = flowCtxRef.current;
                              if (ctx) {
                                ctx.selection.selection = [];
                              } else {
                                setFlowSelectedFgId(null);
                              }
                            }}
                            onRequestPickSelector={
                              flowSelectedFgId &&
                              isSelectorPickableStep(flowDetailStep)
                                ? () => {
                                    setFlowSelectorPickFgId(flowSelectedFgId);
                                    setSelectorPickTarget(null);
                                    setFlowCoordPick(null);
                                    setCoordinatePickTarget(null);
                                    toast.info(
                                      t('workbench.pickSelectorToast')
                                    );
                                  }
                                : undefined
                            }
                            onRequestCropImage={requestCropImage}
                            onRequestPickTapCoords={
                              flowSelectedFgId
                                ? () => {
                                    setFlowCoordPick({
                                      fgId: flowSelectedFgId,
                                      kind: 'tap'
                                    });
                                    setCoordinatePickTarget(null);
                                    setFlowSelectorPickFgId(null);
                                    toast.info(t('workbench.pickTapToast'));
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
                                    toast.info(t('workbench.pickSwipeToast'));
                                  }
                                : undefined
                            }
                            availableVariables={scenarioVariableNames}
                          />
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className='flex h-full min-h-0 flex-col overflow-hidden bg-background'>
                      <div className='flex shrink-0 items-center justify-between gap-2 border-b border-border/50 px-2.5 py-1.5'>
                        <div className='min-w-0 truncate text-[11px] font-medium text-muted-foreground'>
                          {flowSortMode
                            ? t('workbench.sorting')
                            : t('stepCount', { count: steps.items.length })}
                        </div>
                        <div className='flex shrink-0 items-center gap-2'>
                          <div className='flex h-7 overflow-hidden rounded-md border border-border/60 bg-background p-0.5'>
                            <button
                              type='button'
                              className={`flex items-center gap-1.5 rounded px-2 text-xs font-medium transition-colors ${
                                flowSortMode
                                  ? 'text-muted-foreground hover:bg-accent/70 hover:text-foreground'
                                  : 'bg-primary text-primary-foreground shadow-sm'
                              }`}
                              onClick={() => setFlowSortMode(false)}
                            >
                              <ListTree className='size-3.5' />
                              {t('workbench.viewMode')}
                            </button>
                            <button
                              type='button'
                              className={`flex items-center gap-1.5 rounded px-2 text-xs font-medium transition-colors ${
                                flowSortMode
                                  ? 'bg-primary text-primary-foreground shadow-sm'
                                  : 'text-muted-foreground hover:bg-accent/70 hover:text-foreground'
                              }`}
                              onClick={() => setFlowSortMode(true)}
                            >
                              <Move className='size-3.5' />
                              {t('workbench.sortMode')}
                            </button>
                          </div>
                          {selectedDevice &&
                            Object.values(stepRunStates).some(
                              (st) => st === 'running'
                            ) && (
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
                                {t('workbench.stopInlineRun')}
                              </Button>
                            )}
                        </div>
                      </div>
                      <div className='min-h-0 flex-1 overflow-hidden [&>div]:h-full'>
                        <FlowEditor
                          steps={steps.items as FlowStep[]}
                          onChange={handleFlowStepsChange}
                          maxHeight='100%'
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
                          stepRunResults={stepRunResults}
                          availableVariables={scenarioVariableNames}
                          variablePreviewValues={flowVariablePreviewValues}
                          nodeCapabilities={scenarioSchema?.node_capabilities}
                          deviceCapabilities={selectedDeviceCapabilities}
                          sessionGateRuntimeContext={sessionGateRuntimeContext}
                          onChildStepEditorOpenChange={setChildStepEditorOpen}
                          enableDragDrop={false}
                          virtualReorderMode={flowSortMode}
                          detailMode='inline'
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </ScenarioWorkbenchShell>

      <ControlRecordVariablesDialog
        open={varDialogOpen}
        onOpenChange={setVarDialogOpen}
        variables={scenarioVariablesWithDeviceKeys}
        onVariablesChange={(next) =>
          saveScenarioVariablesMutation.mutateAsync(next)
        }
        buildPageSummary={(next) =>
          buildControlRecordPageSummary(
            next,
            Boolean(activeCampaignId),
            activeCampaignName,
            scenarioVariableReferences
          )
        }
        getPageSummarySourceDescription={(summary) =>
          tVar(
            summary.sourceKind === 'campaign'
              ? 'targetOverviewCampaignSourceDescription'
              : 'targetOverviewScenarioSourceDescription',
            {
              target:
                summary.targetType === 'group'
                  ? tVar('targetOverviewGroupTarget')
                  : tVar('targetOverviewPageTarget')
            }
          )
        }
        savePending={saveScenarioVariablesMutation.isPending}
        saveDisabled={!canSaveScenarioVariables}
        labels={{
          title: tVar('title'),
          variableCount:
            Object.keys(scenarioVariablesWithDeviceKeys).length > 0
              ? tVar('variableCount', {
                  count: Object.keys(scenarioVariablesWithDeviceKeys).length
                })
              : null,
          headerSubtitleLead: tVar('headerSubtitleLead'),
          headerSubtitleTrail: tVar('headerSubtitleTrail'),
          pageSummaryOverview: pageSummary ?? undefined,
          pageSummaryOverviewLabels: {
            title: tVar('targetOverviewTitle'),
            source: tVar('targetOverviewSource'),
            targets: tVar('targetOverviewTargets'),
            flow: tVar('targetOverviewFlow'),
            flowUsesTarget: tVar('targetOverviewFlowUsesTarget'),
            flowDoesNotUseTarget: tVar('targetOverviewFlowDoesNotUseTarget'),
            bindingVariables: tVar('targetOverviewBindingVariables'),
            unusedVariables: tVar('targetOverviewUnusedVariables'),
            targetValuePreview: tVar('targetOverviewValuePreview'),
            catalogTargetSource: tVar('targetOverviewCatalogSource'),
            manualTargetSource: tVar('targetOverviewManualSource'),
            catalogTargetHint: tVar('targetOverviewCatalogHint'),
            manualTargetHint: tVar('targetOverviewManualHint'),
            pageTarget: tVar('targetOverviewPageTarget'),
            groupTarget: tVar('targetOverviewGroupTarget')
          },
          pageSummaryOverviewSourceDescription: pageSummary
            ? tVar(
                pageSummary.sourceKind === 'campaign'
                  ? 'targetOverviewCampaignSourceDescription'
                  : 'targetOverviewScenarioSourceDescription',
                {
                  target:
                    pageSummary.targetType === 'group'
                      ? tVar('targetOverviewGroupTarget')
                      : tVar('targetOverviewPageTarget')
                }
              )
            : undefined,
          targetTab: tVar('targetTab'),
          manualTab: tVar('manualTab'),
          targetTabTitle: tVar('targetTabTitle'),
          targetTabDescription: tVar('targetTabDescription'),
          manualTabTitle: tVar('manualTabTitle'),
          manualTabDescription: tVar('manualTabDescription'),
          cancel: tVar('cancel'),
          save: canPersistScenarioVariables ? tVar('save') : tVar('apply'),
          saving: tVar('saving')
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

      <ScenarioRequirementsSettingsDialog
        open={requirementsDialogOpen}
        onOpenChange={setRequirementsDialogOpen}
        requirements={save.requirements}
        onChange={save.setRequirements}
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
                  onClick={() => void handleSaveAsNewCampaignScenario()}
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
                        onClick={() => void handleSaveToCampaignScenario(s.id)}
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

  return (
    <ImageTemplateScenarioProvider
      scenarioId={templateScenarioId}
      requestCropImage={requestCropImage}
      requestRegion={requestRegion}
    >
      {content}
    </ImageTemplateScenarioProvider>
  );
}
