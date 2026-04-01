'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { campaignsApi, scenariosApi } from '@/features/campaigns/services/api';
import type { ScenarioOut } from '@/features/campaigns/types';
import type { ScenarioStep } from '../types/scenario';
import { scenarioToJson } from '../types/scenario';
import { fetchHierarchy, fetchScreenshotB64, cropBase64 } from '../services/api';
import { useDeviceFarm } from './use-device-farm';
import {
  findSelectorInXml,
  getScreenSignature,
  hashXml,
  pollUntilUiChange
} from '../utils/control-record-xml';
import { parseHierarchySelectorNodes } from '../utils/hierarchy-selectors';
import { createDefaultStep } from '@/features/campaigns/components/scenario-steps/types';
import { validateScenarioStepsForApi } from '@/features/campaigns/utils/validate-scenario-steps-for-api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useTranslations } from 'next-intl';

let _stepIdCounter = 0;
function nextStepId() { return `step-${++_stepIdCounter}`; }

export type StepWithId = ScenarioStep & { _id: string };

type SelectorBy =
  | 'resource-id'
  | 'text'
  | 'xpath'
  | 'class name'
  | 'description'
  | 'descriptionContains'
  | 'descriptionStartsWith';

const ALLOWED_SELECTOR_BY: readonly SelectorBy[] = [
  'resource-id',
  'text',
  'xpath',
  'class name',
  'description',
  'descriptionContains',
  'descriptionStartsWith',
];

function normalizeSelectorBy(by: unknown, fallback: SelectorBy = 'text'): SelectorBy {
  const raw = String(by ?? '').trim();
  if (!raw) return fallback;
  if (ALLOWED_SELECTOR_BY.includes(raw as SelectorBy)) return raw as SelectorBy;
  const lower = raw.toLowerCase().replace(/\s+/g, '');
  if (lower === 'content-desc' || lower === 'contentdesc' || lower === 'description' || lower === 'accessibilityid') return 'description';
  if (lower === 'content-desccontains' || lower === 'descriptioncontains') return 'descriptionContains';
  if (lower === 'content-descstartswith' || lower === 'descriptionstartswith') return 'descriptionStartsWith';
  if (lower === 'classname' || lower === 'class-name') return 'class name';
  return fallback;
}

function sanitizeScenarioStep(step: any): any {
  if (!step || typeof step !== 'object') return step;
  const next: any = { ...step };
  if (next.by != null) next.by = normalizeSelectorBy(next.by);
  if (next.selector && typeof next.selector === 'object') {
    next.selector = {
      ...next.selector,
      ...(next.selector.by != null ? { by: normalizeSelectorBy(next.selector.by) } : {}),
    };
  }
  if (next.condition && typeof next.condition === 'object') {
    const cond = { ...(next.condition as Record<string, any>) };
    if (cond.element_exists && typeof cond.element_exists === 'object' && cond.element_exists.by != null) {
      cond.element_exists = { ...cond.element_exists, by: normalizeSelectorBy(cond.element_exists.by) };
    }
    if (cond.element_not_exists && typeof cond.element_not_exists === 'object' && cond.element_not_exists.by != null) {
      cond.element_not_exists = { ...cond.element_not_exists, by: normalizeSelectorBy(cond.element_not_exists.by) };
    }
    next.condition = cond;
  }
  if (Array.isArray(next.then)) next.then = next.then.map(sanitizeScenarioStep);
  if (Array.isArray(next.else)) next.else = next.else.map(sanitizeScenarioStep);
  if (Array.isArray(next.steps)) next.steps = next.steps.map(sanitizeScenarioStep);
  if (Array.isArray(next.branches)) {
    next.branches = next.branches.map((br: any) =>
      br && typeof br === 'object'
        ? { ...br, ...(Array.isArray(br.steps) ? { steps: br.steps.map(sanitizeScenarioStep) } : {}) }
        : br
    );
  }
  return next;
}

function sanitizeScenarioStepsForApi(input: unknown): any[] {
  if (!Array.isArray(input)) return [];
  return input.map(sanitizeScenarioStep);
}

export function useControlRecord(initialSerial?: string | null, initialCampaignId?: string | null, initialScenarioId?: string | null) {
  const t = useTranslations('devicesControlRecord');
  const errorPrefix = t('errorPrefix');
  const {
    devices,
    logs,
    wsSend,
    modes,
    handleToggleMode,
    handleRestart,
    wsConnected,
    error
  } = useDeviceFarm();

  // ── Device ───────────────────────────────────────────────────────────────
  const [selectedSerial, setSelectedSerial] = useState<string | null>(null);

  const connectedDevices = useMemo(
    () => devices.filter((d) => ['READY', 'BUSY'].includes((d.state ?? '').toUpperCase())),
    [devices]
  );

  const selectedDevice = useMemo(
    () => connectedDevices.find((d) => d.serial === selectedSerial) ?? connectedDevices[0] ?? null,
    [connectedDevices, selectedSerial]
  );

  useEffect(() => {
    if (connectedDevices.length === 0) return;
    if (initialSerial && connectedDevices.some((d) => d.serial === initialSerial)) {
      setSelectedSerial(initialSerial);
      return;
    }
    if (!selectedSerial) setSelectedSerial(connectedDevices[0].serial);
  }, [connectedDevices, selectedSerial, initialSerial]);

  // ── Recording ────────────────────────────────────────────────────────────
  const [recording, setRecording] = useState(false);
  const recordingRef = useRef(false);
  /** While true, taps still go to device but do not append recorded steps (selector pick mode). */
  const skipTapRecordingWhilePickRef = useRef(false);
  const recordXmlRef = useRef<string | null>(null);
  const [recordXml, setRecordXml] = useState<string | null>(null);
  const [pollingXml, setPollingXml] = useState(false);
  const pollingXmlRef = useRef(false);
  const togglingRecordingRef = useRef(false);

  useEffect(() => { recordingRef.current = recording; }, [recording]);
  useEffect(() => { recordXmlRef.current = recordXml; }, [recordXml]);

  const refreshRecordXml = useCallback(async (serial: string) => {
    try {
      const xml = await fetchHierarchy(serial, true);
      if (xml?.trim()) {
        setRecordXml(xml);
        recordXmlRef.current = xml;
        return xml;
      }
    } catch { /* ignore */ }
    return null;
  }, []);

  const setSkipTapRecordingWhilePick = useCallback((v: boolean) => {
    skipTapRecordingWhilePickRef.current = v;
  }, []);

  const toggleRecording = useCallback(async () => {
    if (togglingRecordingRef.current) return;
    togglingRecordingRef.current = true;
    try {
      const next = !recordingRef.current;
      if (next && selectedDevice) {
        toast.info(t('toast.fetchingXml'));
        const xml = await refreshRecordXml(selectedDevice.serial);
        if (xml) toast.success(t('toast.xmlReady'));
        else toast.warning(t('toast.xmlFetchFailedFallback'));
      } else {
        setRecordXml(null);
        recordXmlRef.current = null;
      }
      setRecording(next);
    } finally {
      togglingRecordingRef.current = false;
    }
  }, [selectedDevice, refreshRecordXml, t]);

  // ── Steps ────────────────────────────────────────────────────────────────
  const [steps, setSteps] = useState<StepWithId[]>([]);
  const pendingScreenshotTasksRef = useRef(new Set<Promise<unknown>>());
  const [pendingScreenshotCount, setPendingScreenshotCount] = useState(0);

  const recordStep = useCallback((step: ScenarioStep) => {
    const stepId = nextStepId();
    setSteps((s) => [...s, { ...step, _id: stepId }]);
    return stepId;
  }, []);

  const trackScreenshotTask = useCallback(<T,>(task: Promise<T>) => {
    pendingScreenshotTasksRef.current.add(task);
    setPendingScreenshotCount(pendingScreenshotTasksRef.current.size);
    task.finally(() => {
      pendingScreenshotTasksRef.current.delete(task);
      setPendingScreenshotCount(pendingScreenshotTasksRef.current.size);
    });
    return task;
  }, []);

  const waitForPendingScreenshots = useCallback(async (timeoutMs = 4000) => {
    if (pendingScreenshotTasksRef.current.size <= 0) return true;

    const deadline = Date.now() + timeoutMs;
    while (pendingScreenshotTasksRef.current.size > 0) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) return false;
      const pending = Array.from(pendingScreenshotTasksRef.current);
      await Promise.race([
        Promise.allSettled(pending),
        new Promise((resolve) => setTimeout(resolve, Math.min(remaining, 250))),
      ]);
    }
    return true;
  }, []);

  const sendAndRecord = useCallback(
    (msg: object) => {
      wsSend(msg);
      const m0 = msg as { type?: string };
      if (skipTapRecordingWhilePickRef.current && m0.type === 'tap') {
        return;
      }
      if (!recordingRef.current || !selectedDevice) return;
      const m = msg as {
        type?: string; serial?: string;
        x?: number; y?: number; key?: string;
        x1?: number; y1?: number; x2?: number; y2?: number; ms?: number;
      };
      if (m.serial !== selectedDevice.serial) return;
      const w = selectedDevice.screen_width || 1080;
      const h = selectedDevice.screen_height || 1920;

      if (m.type === 'tap' && typeof m.x === 'number' && typeof m.y === 'number') {
        const rx = parseFloat((m.x / w).toFixed(4));
        const ry = parseFloat((m.y / h).toFixed(4));
        const xml = pollingXmlRef.current ? null : recordXmlRef.current;

        if (xml) {
          const sel = findSelectorInXml(xml, rx, ry);
          const sig = getScreenSignature(xml);
          const screen: Record<string, unknown> = {
            package: sig.package || undefined,
            hash: hashXml(xml).toString(16),
            texts: sig.texts.length ? sig.texts : undefined
          };
          const elemBounds = sel?.bounds;

          let recordedStepId: string;
          if (sel) {
            recordedStepId = recordStep({ type: 'tap', selector: { by: sel.by, value: sel.value }, fallback: { rx, ry }, screen } as ScenarioStep);
            toast.success(t('toast.tapRecorded', { by: sel.by, value: sel.value.slice(0, 40) }), { duration: 2000 });
          } else {
            recordedStepId = recordStep({ type: 'tap', fallback: { rx, ry }, screen } as ScenarioStep);
            toast.warning(t('toast.elementNotFound'), { duration: 3000 });
          }

          const stepSerial = selectedDevice.serial;
          const ratioCrop = elemBounds?.rx2 != null && elemBounds.rx2 > elemBounds.rx1 && elemBounds.ry2 > elemBounds.ry1
            ? { rx1: elemBounds.rx1, ry1: elemBounds.ry1, rx2: elemBounds.rx2, ry2: elemBounds.ry2 }
            : undefined;
          trackScreenshotTask(
            fetchScreenshotB64(stepSerial).then(async (imgData) => {
              if (!recordingRef.current) return;
              // Crop element_image client-side from the same screenshot —
              // avoids a second round-trip and ensures template matches the
              // exact frame stored in screen.screenshot.
              const elementImage = ratioCrop
                ? await cropBase64(imgData.screenshot, ratioCrop)
                : undefined;
              setSteps((prev) => {
                const idxById = prev.findIndex((step) => step._id === recordedStepId);
                if (idxById < 0 || prev[idxById].type !== 'tap') return prev;
                const updated = [...prev];
                const s = { ...updated[idxById] };
                const sc = { ...(s as Record<string, unknown>).screen as Record<string, unknown> };
                sc.screenshot = imgData.screenshot;
                if (elementImage) sc.element_image = elementImage;
                (s as Record<string, unknown>).screen = sc;
                updated[idxById] = s as StepWithId;
                return updated;
              });
            }).catch(() => {
              toast.warning(t('toast.screenshotCaptureFailed'), { duration: 2500 });
            })
          );

          if (recordingRef.current) {
            const oldHash = hashXml(xml);
            pollingXmlRef.current = true;
            setPollingXml(true);
            pollUntilUiChange(selectedDevice.serial, oldHash).then((newXml) => {
              if (!recordingRef.current) return;
              if (newXml) { setRecordXml(newXml); recordXmlRef.current = newXml; }
              pollingXmlRef.current = false;
              setPollingXml(false);
            });
          }
          return;
        }

        recordStep({ type: 'tap_ratio', x: rx, y: ry });
        toast.info(t('toast.xmlMissing'), { duration: 3000 });

      } else if (m.type === 'key' && m.key) {
        recordStep({ type: 'key', key: m.key });

      } else if (m.type === 'swipe' && typeof m.x1 === 'number' && typeof m.y1 === 'number' && typeof m.x2 === 'number' && typeof m.y2 === 'number') {
        recordStep({
          type: 'swipe_ratio',
          x1: parseFloat((m.x1 / w).toFixed(4)),
          y1: parseFloat((m.y1 / h).toFixed(4)),
          x2: parseFloat((m.x2 / w).toFixed(4)),
          y2: parseFloat((m.y2 / h).toFixed(4)),
          duration_ms: m.ms ?? 300
        });
      }
    },
    [wsSend, selectedDevice, recordStep, t, trackScreenshotTask]
  );

  const addWaitStep = useCallback(() => {
    setSteps((s) => [...s, { type: 'wait', seconds: 2, _id: nextStepId() }]);
  }, []);

  const addFlowStep = useCallback((type: string) => {
    setSteps((s) => [...s, { ...createDefaultStep(type), _id: nextStepId() } as StepWithId]);
  }, []);

  const cleanSteps = useCallback(() => steps.map(({ _id, ...rest }) => rest), [steps]);

  const copyJson = useCallback(() => {
    navigator.clipboard.writeText(scenarioToJson(cleanSteps())).then(
      () => toast.success(t('toast.copyJsonSuccess')),
      () => toast.error(t('toast.copyJsonError'))
    );
  }, [cleanSteps, t]);

  // ── Editing context (pre-loaded from URL params) ─────────────────────────
  const [editingContext, setEditingContext] = useState<{
    campaignId: string;
    scenarioId: string;
    name: string;
  } | null>(null);

  useEffect(() => {
    if (!initialCampaignId || !initialScenarioId) return;
    scenariosApi.get(initialCampaignId, initialScenarioId).then((sc) => {
      const loaded = Array.isArray(sc.steps)
        ? sc.steps.map((s: any) => ({ ...s, _id: nextStepId() }) as StepWithId)
        : [];
      setSteps(loaded);
      setEditingContext({ campaignId: initialCampaignId, scenarioId: initialScenarioId, name: sc.name });
      if (loaded.length > 0) toast.info(t('toast.loadedScenario', { name: sc.name, count: loaded.length }));
    }).catch(() => toast.error(t('toast.loadScenarioFailed')));
  // intentionally runs once on mount
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Save dialog ──────────────────────────────────────────────────────────
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [campaigns, setCampaigns] = useState<{ id: string; name: string }[]>([]);
  const [savingCampaignId, setSavingCampaignId] = useState<string | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [campaignScenarios, setCampaignScenarios] = useState<ScenarioOut[]>([]);

  const openSaveDialog = useCallback(() => {
    setSaveDialogOpen(true);
    if (editingContext) {
      // Pre-select the campaign and load its scenarios so the user can directly overwrite
      setSelectedCampaignId(editingContext.campaignId);
      setCampaignScenarios([]);
      scenariosApi.list(editingContext.campaignId).then(setCampaignScenarios).catch(() => setCampaignScenarios([]));
      setCampaigns([]);
    } else {
      setSelectedCampaignId(null);
      setCampaignScenarios([]);
      campaignsApi.list()
        .then((list) => setCampaigns(list.map((c) => ({ id: c.id, name: c.name }))))
        .catch(() => setCampaigns([]));
    }
  }, [editingContext]);

  const handlePickCampaign = useCallback((campaignId: string) => {
    setSelectedCampaignId(campaignId);
    setCampaignScenarios([]);
    scenariosApi.list(campaignId).then(setCampaignScenarios).catch(() => setCampaignScenarios([]));
  }, []);

  const saveToScenario = useCallback(
    async (campaignId: string, scenarioId: string) => {
      if (pendingScreenshotCount > 0) {
        toast.info(t('toast.waitingScreenshotBeforeSave', { count: pendingScreenshotCount }));
      }
      const ready = await waitForPendingScreenshots();
      if (!ready) {
        toast.warning(t('toast.waitingScreenshotTimeout'));
        return;
      }
      const payloadSteps = sanitizeScenarioStepsForApi(cleanSteps());
      const check = validateScenarioStepsForApi(payloadSteps);
      if (!check.ok) {
        toast.error(check.message);
        return;
      }
      setSavingCampaignId(scenarioId);
      scenariosApi.update(campaignId, scenarioId, { steps: payloadSteps })
        .then(() => { toast.success(t('toast.saveStepsSuccess')); setSaveDialogOpen(false); setSelectedCampaignId(null); })
        .catch((err) => toast.error(formatFarmApiError(err, t('toast.saveFailed'))))
        .finally(() => setSavingCampaignId(null));
    },
    [cleanSteps, pendingScreenshotCount, t, waitForPendingScreenshots]
  );

  const saveAsNewScenario = useCallback(
    async (campaignId: string) => {
      if (pendingScreenshotCount > 0) {
        toast.info(t('toast.waitingScreenshotBeforeSave', { count: pendingScreenshotCount }));
      }
      const ready = await waitForPendingScreenshots();
      if (!ready) {
        toast.warning(t('toast.waitingScreenshotTimeout'));
        return;
      }
      const payloadSteps = sanitizeScenarioStepsForApi(cleanSteps());
      const check = validateScenarioStepsForApi(payloadSteps);
      if (!check.ok) {
        toast.error(check.message);
        return;
      }
      setSavingCampaignId('new');
      scenariosApi.create(campaignId, {
        name: t('newScenarioName', { time: new Date().toLocaleTimeString('vi-VN') }),
        steps: payloadSteps,
      })
        .then(() => { toast.success(t('toast.createScenarioSuccess')); setSaveDialogOpen(false); setSelectedCampaignId(null); })
        .catch((err) => toast.error(formatFarmApiError(err, t('toast.createScenarioFailed'))))
        .finally(() => setSavingCampaignId(null));
    },
    [cleanSteps, pendingScreenshotCount, t, waitForPendingScreenshots]
  );

  // ── Hierarchy / Inspector ────────────────────────────────────────────────
  const [hierarchyXml, setHierarchyXml] = useState<string>('');
  const [hierarchyLoading, setHierarchyLoading] = useState(false);
  const [autoRefreshHierarchy, setAutoRefreshHierarchy] = useState(true);
  const [hierarchyPaused, setHierarchyPaused] = useState(false);

  const refreshHierarchy = useCallback(() => {
    if (!selectedDevice) return;
    setHierarchyLoading(true);
    fetchHierarchy(selectedDevice.serial, true)
      .then(setHierarchyXml)
      .catch((e) => setHierarchyXml(`${errorPrefix} ${String(e)}`))
      .finally(() => setHierarchyLoading(false));
  }, [selectedDevice, errorPrefix]);

  useEffect(() => {
    if (!autoRefreshHierarchy || !selectedDevice || hierarchyPaused) return;
    fetchHierarchy(selectedDevice.serial, true).then(setHierarchyXml).catch(() => {});
    const id = setInterval(() => {
      fetchHierarchy(selectedDevice.serial)
        .then(setHierarchyXml)
        .catch((e) => setHierarchyXml((prev) => (prev.startsWith(errorPrefix) ? prev : `${errorPrefix} ${String(e)}`)));
    }, 3000);
    return () => clearInterval(id);
  }, [autoRefreshHierarchy, selectedDevice, hierarchyPaused, errorPrefix]);

  const parsedHierarchyNodes = useMemo(() => parseHierarchySelectorNodes(hierarchyXml), [hierarchyXml]);

  // ── Selector (manual tap) ────────────────────────────────────────────────
  const [selectorBy, setSelectorBy] = useState<
    'resource-id' | 'text' | 'xpath' | 'class name' | 'description' | 'descriptionContains' | 'descriptionStartsWith'
  >('text');
  const [selectorValue, setSelectorValue] = useState('');

  const handleTapSelector = useCallback(() => {
    if (!selectedDevice || !selectorValue.trim()) return;
    const by = selectorBy;
    const value = selectorValue.trim();
    wsSend({ type: 'tap_selector', serial: selectedDevice.serial, by, value });
    if (recording) {
      recordStep({ type: 'tap', selector: { by, value } } as ScenarioStep);
    }
    toast.success(t('toast.tapSelectorSuccess', { by, value: value.slice(0, 30) }));
  }, [selectedDevice, selectorBy, selectorValue, wsSend, recording, recordStep, t]);

  // ── Return (grouped) ─────────────────────────────────────────────────────
  const mode = selectedDevice ? (modes[selectedDevice.serial] ?? 'tap') : 'tap';

  return {
    error,

    device: {
      connectedDevices,
      wsConnected,
      selectedDevice,
      selectedSerial,
      setSelectedSerial,
      mode,
      logs,
    },

    record: {
      recording,
      toggleRecording,
      pollingXml,
      sendAndRecord,
      setSkipTapRecordingWhilePick,
      handleToggleMode,
      handleRestart,
    },

    steps: {
      items: steps,
      setItems: setSteps,
      addWait: addWaitStep,
      addFlow: addFlowStep,
      copyJson,
      openSave: openSaveDialog,
    },

    save: {
      dialogOpen: saveDialogOpen,
      setDialogOpen: setSaveDialogOpen,
      campaigns,
      saving: savingCampaignId,
      selectedCampaignId,
      setSelectedCampaignId,
      campaignScenarios,
      pickCampaign: handlePickCampaign,
      saveTo: saveToScenario,
      saveAsNew: saveAsNewScenario,
      editingContext,
    },

    hierarchy: {
      xml: hierarchyXml,
      loading: hierarchyLoading,
      autoRefresh: autoRefreshHierarchy,
      setAutoRefresh: setAutoRefreshHierarchy,
      refresh: refreshHierarchy,
      nodes: parsedHierarchyNodes,
      setPaused: setHierarchyPaused,
    },

    selector: {
      by: selectorBy,
      setBy: setSelectorBy,
      value: selectorValue,
      setValue: setSelectorValue,
      tap: handleTapSelector,
    },
  };
}
