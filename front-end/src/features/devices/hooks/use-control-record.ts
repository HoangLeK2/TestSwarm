'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { campaignsApi, scenariosApi } from '@/features/campaigns/services/api';
import { scenarioTemplatesApi } from '@/features/scenario-templates/services/api';
import type { ScenarioOut } from '@/features/campaigns/types';
import type { Device } from '../types';
import type { ScenarioStep } from '../types/scenario';
import { scenarioToJson } from '../types/scenario';
import {
  fetchHierarchy,
  fetchScreenshotB64,
  cropBase64
} from '../services/api';
import { useDeviceFarm } from './use-device-farm';
import { useTabNetworkActive } from './use-tab-network-active';
import {
  findSelectorInXml,
  getScreenSignature,
  hashXml,
  pollUntilUiChange
} from '../utils/control-record-xml';
import { parseHierarchySelectorNodes } from '../utils/hierarchy-selectors';
import { createDefaultStep } from '@/features/campaigns/components/scenario-steps/types';
import { validateScenarioStepsForApi } from '@/features/campaigns/utils/validate-scenario-steps-for-api';
import { buildRecordedTapStep } from '../lib/scenario-selector-step';
import { sanitizeScenarioStepsForApi } from '../lib/sanitize-scenario-steps-for-api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useTranslations } from 'next-intl';
import { orgScenariosApi } from '@/features/org-scenarios/services/api';
import { extractPreviewSteps } from '@/features/org-scenarios/lib/parse-scenario-body';
import { normalizeScenarioVariables } from '@/lib/scenario-variables';
import { canApplyDeviceScopedResult } from '../lib/control-record-multi';
import { isControlRecordConnectedDevice } from '../lib/control-record-device-state';

let _stepIdCounter = 0;
function nextStepId() {
  return `step-${++_stepIdCounter}`;
}

export type StepWithId = ScenarioStep & { _id: string };

const HIERARCHY_INTERACTION_PULSE_THROTTLE_MS = 3500;
const HIERARCHY_INTERACTION_FETCH_COOLDOWN_MS = 3500;
const HIERARCHY_BOOTSTRAP_RETRY_MS = 1500;
const HIERARCHY_BOOTSTRAP_MAX_ATTEMPTS = 20;
const RECORD_XML_POLL_INTERVAL_MS = 1200;
const RECORD_XML_POLL_TIMEOUT_MS = 4800;

type SendAndRecordOptions = {
  multiSerials?: string[];
};

function ratio(value: number | undefined, size: number) {
  if (typeof value !== 'number' || !Number.isFinite(value) || size <= 0) {
    return 0;
  }
  return Number(Math.max(0, Math.min(1, value / size)).toFixed(4));
}

function buildMultiAction(
  msg: object,
  primary: Device
): Record<string, unknown> | null {
  const m = msg as Record<string, any>;
  const type = String(m.type ?? '');
  const w = primary.screen_width || 1080;
  const h = primary.screen_height || 1920;

  if (type === 'tap') {
    return {
      type: 'tap_ratio',
      rx: ratio(m.x, w),
      ry: ratio(m.y, h)
    };
  }
  if (type === 'swipe') {
    return {
      type: 'swipe_ratio',
      rx1: ratio(m.x1, w),
      ry1: ratio(m.y1, h),
      rx2: ratio(m.x2, w),
      ry2: ratio(m.y2, h),
      ms: m.ms
    };
  }
  if (type === 'drag') {
    return {
      type: 'drag_ratio',
      rx1: ratio(m.x1, w),
      ry1: ratio(m.y1, h),
      rx2: ratio(m.x2, w),
      ry2: ratio(m.y2, h),
      duration_ms: m.ms ?? m.duration_ms
    };
  }
  if (type === 'double_tap') {
    return {
      type: 'double_tap_ratio',
      rx: ratio(m.x, w),
      ry: ratio(m.y, h)
    };
  }
  if (type === 'long_tap') {
    return {
      type: 'long_tap_ratio',
      rx: ratio(m.x, w),
      ry: ratio(m.y, h),
      duration_ms: m.ms ?? m.duration_ms
    };
  }
  if (type === 'pinch') {
    return {
      type: 'pinch_ratio',
      rcx: ratio(m.cx, w),
      rcy: ratio(m.cy, h),
      scale: m.scale,
      duration_ms: m.ms ?? m.duration_ms
    };
  }
  if (
    [
      'key',
      'tap_selector',
      'input_text',
      'launch_app',
      'open_url',
      'screen_on',
      'screen_off',
      'unlock',
      'swipe_ext'
    ].includes(type)
  ) {
    const { serial: _serial, ...rest } = m;
    return rest;
  }
  return null;
}

export function useControlRecord(
  initialSerial?: string | null,
  initialCampaignId?: string | null,
  initialScenarioId?: string | null,
  initialTemplateId?: string | null,
  initialOrgScenarioId?: string | null
) {
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
  const tabActive = useTabNetworkActive();

  // ── Device ───────────────────────────────────────────────────────────────
  const [selectedSerial, setSelectedSerial] = useState<string | null>(null);
  const initialSerialAppliedRef = useRef(false);

  const connectedDevices = useMemo(
    () => devices.filter(isControlRecordConnectedDevice),
    [devices]
  );

  const selectedDevice = useMemo(
    () =>
      connectedDevices.find((d) => d.serial === selectedSerial) ??
      connectedDevices[0] ??
      null,
    [connectedDevices, selectedSerial]
  );
  const selectedDeviceSerial = selectedDevice?.serial ?? null;
  const selectedDeviceSerialRef = useRef<string | null>(selectedDeviceSerial);
  selectedDeviceSerialRef.current = selectedDeviceSerial;
  const selectedDeviceRef = useRef(selectedDevice);
  selectedDeviceRef.current = selectedDevice;

  useEffect(() => {
    if (connectedDevices.length === 0) return;
    // Apply initialSerial only once on first hydrated device list.
    // Otherwise each WS device refresh would force selection back and
    // user could not switch to another device from the dropdown.
    if (
      !initialSerialAppliedRef.current &&
      initialSerial &&
      connectedDevices.some((d) => d.serial === initialSerial)
    ) {
      setSelectedSerial(initialSerial);
      initialSerialAppliedRef.current = true;
      return;
    }
    if (!selectedSerial) setSelectedSerial(connectedDevices[0].serial);
  }, [connectedDevices, selectedSerial, initialSerial]);

  // ── Recording ────────────────────────────────────────────────────────────
  const [recording, setRecording] = useState(false);
  const recordingRef = useRef(false);
  /** While true, tap/swipe/drag still go to device but do not append recorded steps (selector / coordinate pick). */
  const skipTapRecordingWhilePickRef = useRef(false);
  const recordXmlRef = useRef<string | null>(null);
  const recordXmlSerialRef = useRef<string | null>(null);
  const [recordXml, setRecordXml] = useState<string | null>(null);
  const [pollingXml, setPollingXml] = useState(false);
  const pollingXmlRef = useRef(false);
  const togglingRecordingRef = useRef(false);
  const [hierarchyRefreshPulse, setHierarchyRefreshPulse] = useState(0);
  const lastHierarchyPulseAtRef = useRef(0);

  useEffect(() => {
    recordingRef.current = recording;
  }, [recording]);
  useEffect(() => {
    recordXmlRef.current = recordXml;
  }, [recordXml]);

  const refreshRecordXml = useCallback(async (serial: string) => {
    try {
      const xml = await fetchHierarchy(serial, true);
      if (
        !canApplyDeviceScopedResult(serial, selectedDeviceSerialRef.current)
      ) {
        return null;
      }
      if (xml?.trim()) {
        setRecordXml(xml);
        recordXmlRef.current = xml;
        recordXmlSerialRef.current = serial;
        return xml;
      }
    } catch {
      /* ignore */
    }
    return null;
  }, []);

  const setSkipTapRecordingWhilePick = useCallback((v: boolean) => {
    skipTapRecordingWhilePickRef.current = v;
  }, []);

  const pulseHierarchyRefresh = useCallback(() => {
    const now = Date.now();
    // Collapse burst actions (tap/swipe spam) into one refresh pulse.
    if (
      now - lastHierarchyPulseAtRef.current <
      HIERARCHY_INTERACTION_PULSE_THROTTLE_MS
    )
      return;
    lastHierarchyPulseAtRef.current = now;
    setHierarchyRefreshPulse((v) => v + 1);
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
        recordXmlSerialRef.current = null;
        pollingXmlRef.current = false;
        setPollingXml(false);
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

  const trackScreenshotTask = useCallback(<T>(task: Promise<T>) => {
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
        new Promise((resolve) => setTimeout(resolve, Math.min(remaining, 250)))
      ]);
    }
    return true;
  }, []);

  const sendAndRecord = useCallback(
    (msg: object, options?: SendAndRecordOptions) => {
      const selectedDevice = selectedDeviceRef.current;
      const m0 = msg as { type?: string; serial?: string };
      const multiSerials = Array.from(
        new Set(
          (options?.multiSerials ?? [])
            .map((serial) => serial.trim())
            .filter(Boolean)
        )
      );
      const multiAction =
        selectedDevice &&
        m0.serial === selectedDevice.serial &&
        multiSerials.length > 1
          ? buildMultiAction(msg, selectedDevice)
          : null;

      // Pre-fetch screenshot BEFORE sending the tap so we capture the screen
      // state at tap-time (before any UI transition the tap triggers).
      // `device.take_screenshot()` on the backend returns the last cached frame,
      // so fetching before the tap gives us the exact screen the user saw.
      const preTapScreenshotPromise =
        !skipTapRecordingWhilePickRef.current &&
        recordingRef.current &&
        selectedDevice &&
        m0.type === 'tap' &&
        m0.serial === selectedDevice.serial
          ? fetchScreenshotB64(selectedDevice.serial)
          : undefined;

      // Fresh hierarchy at tap-time — recordXmlRef is often stale after navigation
      // (search list → group page) and would map coords to the wrong row.
      const preTapHierarchyPromise =
        !skipTapRecordingWhilePickRef.current &&
        recordingRef.current &&
        selectedDevice &&
        m0.type === 'tap' &&
        m0.serial === selectedDevice.serial
          ? fetchHierarchy(selectedDevice.serial, true).catch(() => null)
          : undefined;

      if (multiAction && selectedDevice) {
        wsSend({
          type: 'multi_action',
          request_id: `control-${Date.now()}-${Math.random()
            .toString(36)
            .slice(2, 8)}`,
          primary_serial: selectedDevice.serial,
          serials: multiSerials,
          action: multiAction
        });
      } else {
        wsSend(msg);
      }
      if (
        selectedDevice &&
        m0.serial === selectedDevice.serial &&
        [
          'tap',
          'swipe',
          'drag',
          'double_tap',
          'tap_selector',
          'input_text',
          'open_url',
          'launch_app'
        ].includes(String(m0.type ?? ''))
      ) {
        pulseHierarchyRefresh();
      }
      if (
        skipTapRecordingWhilePickRef.current &&
        (m0.type === 'tap' || m0.type === 'swipe' || m0.type === 'drag')
      ) {
        return;
      }
      if (!recordingRef.current || !selectedDevice) return;
      const m = msg as {
        type?: string;
        serial?: string;
        x?: number;
        y?: number;
        key?: string;
        x1?: number;
        y1?: number;
        x2?: number;
        y2?: number;
        ms?: number;
      };
      if (m.serial !== selectedDevice.serial) return;
      const w = selectedDevice.screen_width || 1080;
      const h = selectedDevice.screen_height || 1920;

      if (
        m.type === 'tap' &&
        typeof m.x === 'number' &&
        typeof m.y === 'number'
      ) {
        const rx = parseFloat((m.x / w).toFixed(4));
        const ry = parseFloat((m.y / h).toFixed(4));
        const stepSerial = selectedDevice.serial;

        const recordTapWithXml = (xmlRaw: string | null | undefined) => {
          if (!recordingRef.current) return;
          if (
            !canApplyDeviceScopedResult(
              stepSerial,
              selectedDeviceSerialRef.current
            )
          ) {
            return;
          }

          const xml = xmlRaw?.trim() ?? '';
          if (!xml) {
            recordStep({ type: 'tap_ratio', x: rx, y: ry });
            toast.info(t('toast.xmlMissing'), { duration: 3000 });
            return;
          }

          setRecordXml(xml);
          recordXmlRef.current = xml;
          recordXmlSerialRef.current = stepSerial;

          const sig = getScreenSignature(xml);
          const sel = findSelectorInXml(xml, rx, ry, {
            targetPackage:
              sig.package || selectedDevice.current_app || undefined,
            screenDims: { dw: w, dh: h }
          });
          const screen: Record<string, unknown> = {
            package: sig.package || undefined,
            hash: hashXml(xml).toString(16),
            texts: sig.texts.length ? sig.texts : undefined
          };
          const elemBounds = sel?.bounds;

          let recordedStepId: string;
          if (sel) {
            recordedStepId = recordStep(
              buildRecordedTapStep({
                by: sel.by,
                value: sel.value,
                selector: sel.selector,
                rx,
                ry,
                screen
              }) as ScenarioStep
            );
            toast.success(
              t('toast.tapRecorded', {
                by: sel.by,
                value: sel.value.slice(0, 40)
              }),
              { duration: 2000 }
            );
          } else {
            recordedStepId = recordStep({
              type: 'tap',
              fallback: { rx, ry },
              screen
            } as ScenarioStep);
            toast.warning(t('toast.elementNotFound'), { duration: 3000 });
          }

          const ratioCrop =
            elemBounds?.rx2 != null &&
            elemBounds.rx2 > elemBounds.rx1 &&
            elemBounds.ry2 > elemBounds.ry1
              ? {
                  rx1: elemBounds.rx1,
                  ry1: elemBounds.ry1,
                  rx2: elemBounds.rx2,
                  ry2: elemBounds.ry2
                }
              : undefined;

          const needFullScreenshot = !sel;

          if (needFullScreenshot || ratioCrop) {
            trackScreenshotTask(
              (preTapScreenshotPromise ?? fetchScreenshotB64(stepSerial))
                .then(async (imgData) => {
                  if (!recordingRef.current) return;
                  const elementImage = ratioCrop
                    ? await cropBase64(imgData.screenshot, ratioCrop)
                    : undefined;
                  setSteps((prev) => {
                    const idxById = prev.findIndex(
                      (step) => step._id === recordedStepId
                    );
                    if (idxById < 0 || prev[idxById].type !== 'tap')
                      return prev;
                    const updated = [...prev];
                    const s = { ...updated[idxById] };
                    const sc = {
                      ...((s as Record<string, unknown>).screen as Record<
                        string,
                        unknown
                      >)
                    };
                    if (needFullScreenshot) sc.screenshot = imgData.screenshot;
                    if (elementImage) sc.element_image = elementImage;
                    (s as Record<string, unknown>).screen = sc;
                    updated[idxById] = s as StepWithId;
                    return updated;
                  });
                })
                .catch(() => {
                  toast.warning(t('toast.screenshotCaptureFailed'), {
                    duration: 2500
                  });
                })
            );
          }

          if (recordingRef.current) {
            const oldHash = hashXml(xml);
            pollingXmlRef.current = true;
            setPollingXml(true);
            pollUntilUiChange(
              stepSerial,
              oldHash,
              RECORD_XML_POLL_INTERVAL_MS,
              RECORD_XML_POLL_TIMEOUT_MS
            )
              .then((newXml) => {
                if (!recordingRef.current) return;
                if (
                  !canApplyDeviceScopedResult(
                    stepSerial,
                    selectedDeviceSerialRef.current
                  )
                )
                  return;
                if (newXml) {
                  setRecordXml(newXml);
                  recordXmlRef.current = newXml;
                  recordXmlSerialRef.current = stepSerial;
                }
              })
              .catch(() => {
                /* keep recording usable even when hierarchy refresh fails */
              })
              .finally(() => {
                if (
                  !canApplyDeviceScopedResult(
                    stepSerial,
                    selectedDeviceSerialRef.current
                  )
                )
                  return;
                pollingXmlRef.current = false;
                setPollingXml(false);
              });
          }
        };

        if (preTapHierarchyPromise) {
          void preTapHierarchyPromise.then((freshXml) => {
            recordTapWithXml(freshXml ?? recordXmlRef.current);
          });
        } else {
          recordTapWithXml(recordXmlRef.current);
        }
        return;
      } else if (m.type === 'key' && m.key) {
        recordStep({ type: 'key', key: m.key });
      } else if (
        m.type === 'swipe' &&
        typeof m.x1 === 'number' &&
        typeof m.y1 === 'number' &&
        typeof m.x2 === 'number' &&
        typeof m.y2 === 'number'
      ) {
        recordStep({
          type: 'swipe_ratio',
          x1: parseFloat((m.x1 / w).toFixed(4)),
          y1: parseFloat((m.y1 / h).toFixed(4)),
          x2: parseFloat((m.x2 / w).toFixed(4)),
          y2: parseFloat((m.y2 / h).toFixed(4)),
          duration_ms: m.ms ?? 300
        });
      } else if (
        m.type === 'double_tap' &&
        typeof m.x === 'number' &&
        typeof m.y === 'number'
      ) {
        const rx = parseFloat((m.x / w).toFixed(4));
        const ry = parseFloat((m.y / h).toFixed(4));
        recordStep({ type: 'double_tap', rx, ry });
      } else if (
        m.type === 'drag' &&
        typeof m.x1 === 'number' &&
        typeof m.y1 === 'number' &&
        typeof m.x2 === 'number' &&
        typeof m.y2 === 'number'
      ) {
        recordStep({
          type: 'drag',
          rx1: parseFloat((m.x1 / w).toFixed(4)),
          ry1: parseFloat((m.y1 / h).toFixed(4)),
          rx2: parseFloat((m.x2 / w).toFixed(4)),
          ry2: parseFloat((m.y2 / h).toFixed(4)),
          duration_ms: m.ms ?? 1000
        });
      }
    },
    [wsSend, recordStep, t, trackScreenshotTask, pulseHierarchyRefresh]
  );

  const addWaitStep = useCallback(() => {
    setSteps((s) => [...s, { type: 'wait', seconds: 2, _id: nextStepId() }]);
  }, []);

  const addFlowStep = useCallback((type: string) => {
    setSteps((s) => [
      ...s,
      { ...createDefaultStep(type), _id: nextStepId() } as StepWithId
    ]);
  }, []);

  // Append an array of steps loaded from a template. Each step gets a fresh
  // internal id so React keys stay unique across multiple loads of the same
  // template. Invalid or non-object entries are dropped defensively — template
  // data may come from the server in a shape that predates the current schema.
  const appendSteps = useCallback((incoming: any[]) => {
    if (!Array.isArray(incoming) || incoming.length === 0) return 0;
    const mapped = incoming
      .filter((s) => s && typeof s === 'object')
      .map(
        (s) => ({ ...(s as ScenarioStep), _id: nextStepId() }) as StepWithId
      );
    if (mapped.length === 0) return 0;
    setSteps((prev) => [...prev, ...mapped]);
    return mapped.length;
  }, []);

  const cleanSteps = useCallback(
    () => steps.map(({ _id, ...rest }) => rest),
    [steps]
  );

  const copyJson = useCallback(() => {
    const text = scenarioToJson(cleanSteps());
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(
        () => toast.success(t('toast.copyJsonSuccess')),
        () => toast.error(t('toast.copyJsonError'))
      );
      return;
    }
    // Fallback for non-HTTPS (HTTP dev server accessed via IP)
    const el = document.createElement('textarea');
    el.value = text;
    el.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
    document.body.appendChild(el);
    el.focus();
    el.select();
    try {
      document.execCommand('copy');
      toast.success(t('toast.copyJsonSuccess'));
    } catch {
      toast.error(t('toast.copyJsonError'));
    }
    document.body.removeChild(el);
  }, [cleanSteps, t]);

  // ── Editing context (pre-loaded from URL params) ─────────────────────────
  const [editingContext, setEditingContext] = useState<{
    campaignId: string;
    scenarioId: string;
    name: string;
    variables?: Record<string, any>;
    /** Pre-loaded binding from the scenario so `saveTo` can round-trip it back. */
    accountGroupId?: string | null;
  } | null>(null);

  // Template editing context — separate from campaign/scenario. Only one of
  // the two is active at a time; the page-level URL params route the user
  // into exactly one mode (campaignId+scenarioId OR templateId).
  const [templateContext, setTemplateContext] = useState<{
    templateId: string;
    name: string;
    description: string;
    category: string;
    tags: string;
    variables?: Record<string, any>;
  } | null>(null);
  const [savingTemplate, setSavingTemplate] = useState(false);

  const [orgScenarioContext, setOrgScenarioContext] = useState<{
    scenarioId: string;
    name: string;
    kind: string;
    isRecoveryScenario?: boolean;
    recoveryUsageCount?: number;
    variables?: Record<string, any>;
  } | null>(null);

  useEffect(() => {
    if (initialOrgScenarioId || initialTemplateId) return;
    if (!initialCampaignId || !initialScenarioId) {
      setEditingContext(null);
      return;
    }

    let cancelled = false;
    Promise.all([
      scenariosApi.get(initialCampaignId, initialScenarioId),
      campaignsApi.get(initialCampaignId).catch(() => null)
    ])
      .then(([sc, campaign]) => {
        if (cancelled) return;
        setOrgScenarioContext(null);
        setTemplateContext(null);
        const loaded = Array.isArray(sc.steps)
          ? sc.steps.map(
              (s: any) => ({ ...s, _id: nextStepId() }) as StepWithId
            )
          : [];
        setSteps(loaded);
        const mergedVars = {
          ...((campaign as { variables?: Record<string, any> } | null)
            ?.variables ?? {}),
          ...(sc.variables ?? {})
        };
        setEditingContext({
          campaignId: initialCampaignId,
          scenarioId: initialScenarioId,
          name: sc.name,
          variables: mergedVars,
          accountGroupId:
            (sc as { account_group_id?: string | null }).account_group_id ??
            null
        });
        if (loaded.length > 0)
          toast.info(
            t('toast.loadedScenario', { name: sc.name, count: loaded.length })
          );
      })
      .catch(() => {
        if (!cancelled) toast.error(t('toast.loadScenarioFailed'));
      });

    return () => {
      cancelled = true;
    };
  }, [
    initialCampaignId,
    initialScenarioId,
    initialOrgScenarioId,
    initialTemplateId,
    t
  ]);

  // Load scenario template when ?templateId=... is present in the URL.
  // Mutually exclusive with campaign/scenario — the UI should only expose
  // one save target per session.
  useEffect(() => {
    if (
      !initialTemplateId ||
      initialOrgScenarioId ||
      initialCampaignId ||
      initialScenarioId
    ) {
      if (!initialTemplateId) setTemplateContext(null);
      return;
    }

    let cancelled = false;
    scenarioTemplatesApi
      .get(initialTemplateId)
      .then((tpl) => {
        if (cancelled) return;
        setEditingContext(null);
        setOrgScenarioContext(null);
        const loaded = Array.isArray(tpl.steps)
          ? tpl.steps.map(
              (s: any) => ({ ...s, _id: nextStepId() }) as StepWithId
            )
          : [];
        setSteps(loaded);
        setTemplateContext({
          templateId: tpl.id,
          name: tpl.name,
          description: tpl.description ?? '',
          category: tpl.category ?? '',
          tags: tpl.tags ?? '',
          variables: tpl.variables ?? {}
        });
        if (loaded.length > 0)
          toast.info(
            t('toast.loadedTemplate', { name: tpl.name, count: loaded.length })
          );
      })
      .catch(() => {
        if (!cancelled) toast.error(t('toast.loadTemplateFailed'));
      });

    return () => {
      cancelled = true;
    };
  }, [
    initialTemplateId,
    initialOrgScenarioId,
    initialCampaignId,
    initialScenarioId,
    t
  ]);

  useEffect(() => {
    if (!initialOrgScenarioId || initialTemplateId) {
      if (!initialOrgScenarioId) setOrgScenarioContext(null);
      return;
    }

    let cancelled = false;
    Promise.all([
      orgScenariosApi.get(initialOrgScenarioId),
      orgScenariosApi.getBody(initialOrgScenarioId)
    ])
      .then(([meta, bodyOut]) => {
        if (cancelled) return;
        setEditingContext(null);
        setTemplateContext(null);
        const bodyJson = (bodyOut.body_json ?? {}) as Record<string, unknown>;
        const previewSteps = extractPreviewSteps(bodyJson);
        const loaded = previewSteps.map(
          (s) => ({ ...s, _id: nextStepId() }) as StepWithId
        );
        setSteps(loaded);
        setOrgScenarioContext({
          scenarioId: initialOrgScenarioId,
          name: meta.name,
          kind: meta.kind,
          isRecoveryScenario:
            meta.is_recovery_scenario === true ||
            (meta.recovery_usage_count ?? 0) > 0,
          recoveryUsageCount: meta.recovery_usage_count ?? 0,
          variables: normalizeScenarioVariables(
            bodyJson.variables as Record<string, unknown> | undefined
          )
        });
        if (loaded.length > 0) {
          toast.info(
            t('toast.loadedOrgScenario', {
              name: meta.name,
              count: loaded.length
            })
          );
        }
      })
      .catch(() => {
        if (!cancelled) toast.error(t('toast.loadOrgScenarioFailed'));
      });

    return () => {
      cancelled = true;
    };
  }, [initialOrgScenarioId, initialTemplateId, t]);

  const saveToTemplate = useCallback(
    async (variables?: Record<string, any>) => {
      if (!templateContext) return;
      if (pendingScreenshotCount > 0) {
        toast.info(
          t('toast.waitingScreenshotBeforeSave', {
            count: pendingScreenshotCount
          })
        );
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
      setSavingTemplate(true);
      try {
        await scenarioTemplatesApi.update(templateContext.templateId, {
          steps: payloadSteps,
          variables: variables ?? templateContext.variables ?? {}
        });
        toast.success(t('toast.saveTemplateSuccess'));
      } catch (err) {
        toast.error(formatFarmApiError(err, t('toast.saveFailed')));
      } finally {
        setSavingTemplate(false);
      }
    },
    // cleanSteps closes over `steps` — eslint is happy once it's listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      templateContext,
      pendingScreenshotCount,
      t,
      waitForPendingScreenshots,
      cleanSteps
    ]
  );

  // ── Save dialog ──────────────────────────────────────────────────────────
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [campaigns, setCampaigns] = useState<{ id: string; name: string }[]>(
    []
  );
  const [savingCampaignId, setSavingCampaignId] = useState<string | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(
    null
  );
  const [campaignScenarios, setCampaignScenarios] = useState<ScenarioOut[]>([]);

  const openSaveDialog = useCallback(() => {
    setSaveDialogOpen(true);
    if (editingContext) {
      // Pre-select the campaign and load its scenarios so the user can directly overwrite
      setSelectedCampaignId(editingContext.campaignId);
      setCampaignScenarios([]);
      scenariosApi
        .list(editingContext.campaignId)
        .then(setCampaignScenarios)
        .catch(() => setCampaignScenarios([]));
      setCampaigns([]);
    } else {
      setSelectedCampaignId(null);
      setCampaignScenarios([]);
      campaignsApi
        .list()
        .then((list) =>
          setCampaigns(list.map((c) => ({ id: c.id, name: c.name })))
        )
        .catch(() => setCampaigns([]));
    }
  }, [editingContext]);

  const handlePickCampaign = useCallback((campaignId: string) => {
    setSelectedCampaignId(campaignId);
    setCampaignScenarios([]);
    scenariosApi
      .list(campaignId)
      .then(setCampaignScenarios)
      .catch(() => setCampaignScenarios([]));
  }, []);

  const saveToScenario = useCallback(
    async (
      campaignId: string,
      scenarioId: string,
      variables?: Record<string, any>,
      accountGroupIdOverride?: string | null
    ) => {
      if (pendingScreenshotCount > 0) {
        toast.info(
          t('toast.waitingScreenshotBeforeSave', {
            count: pendingScreenshotCount
          })
        );
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
      // account_group_id resolution:
      // - override provided → use it (empty string clears the binding)
      // - else editingContext for this scenario → preserve existing value
      // - else do not send the field (unrelated save)
      let accountGroupForEdit: string | undefined;
      if (accountGroupIdOverride !== undefined) {
        accountGroupForEdit = accountGroupIdOverride ?? '';
      } else if (editingContext && editingContext.scenarioId === scenarioId) {
        accountGroupForEdit = editingContext.accountGroupId ?? '';
      }
      const payload: Parameters<typeof scenariosApi.update>[2] = {
        steps: payloadSteps,
        variables,
        ...(accountGroupForEdit !== undefined
          ? { account_group_id: accountGroupForEdit }
          : {})
      };
      scenariosApi
        .update(campaignId, scenarioId, payload)
        .then((updated) => {
          setEditingContext({
            campaignId,
            scenarioId: updated.id,
            name: updated.name,
            variables: {
              ...(variables ?? {})
            },
            accountGroupId:
              (updated as { account_group_id?: string | null })
                .account_group_id ?? null
          });
          toast.success(t('toast.saveStepsSuccess'));
          setSaveDialogOpen(false);
          setSelectedCampaignId(null);
        })
        .catch((err) =>
          toast.error(formatFarmApiError(err, t('toast.saveFailed')))
        )
        .finally(() => setSavingCampaignId(null));
    },
    [
      cleanSteps,
      pendingScreenshotCount,
      t,
      waitForPendingScreenshots,
      editingContext
    ]
  );

  const saveAsNewScenario = useCallback(
    async (
      campaignId: string,
      variables?: Record<string, any>,
      accountGroupIdOverride?: string | null
    ) => {
      if (pendingScreenshotCount > 0) {
        toast.info(
          t('toast.waitingScreenshotBeforeSave', {
            count: pendingScreenshotCount
          })
        );
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
      const createBody: Parameters<typeof scenariosApi.create>[1] = {
        name: t('newScenarioName', {
          time: new Date().toLocaleTimeString('vi-VN')
        }),
        steps: payloadSteps,
        variables,
        ...(accountGroupIdOverride
          ? { account_group_id: accountGroupIdOverride }
          : {})
      };
      scenariosApi
        .create(campaignId, createBody)
        .then((created) => {
          setEditingContext({
            campaignId,
            scenarioId: created.id,
            name: created.name,
            variables: {
              ...(variables ?? {})
            },
            accountGroupId:
              (created as { account_group_id?: string | null })
                .account_group_id ?? null
          });
          toast.success(t('toast.createScenarioSuccess'));
          setSaveDialogOpen(false);
          setSelectedCampaignId(null);
        })
        .catch((err) =>
          toast.error(formatFarmApiError(err, t('toast.createScenarioFailed')))
        )
        .finally(() => setSavingCampaignId(null));
    },
    [cleanSteps, pendingScreenshotCount, t, waitForPendingScreenshots]
  );

  // ── Hierarchy / Inspector ────────────────────────────────────────────────
  const [autoRefreshHierarchy, setAutoRefreshHierarchy] = useState(true);
  const [hierarchyPaused, setHierarchyPaused] = useState(false);
  const lastHierarchyFetchAtRef = useRef(0);
  const lastHierarchyAppRef = useRef<string>('');
  const selectedHierarchySerial = selectedDevice?.serial ?? null;
  const selectedHierarchyApp = selectedDevice?.current_app ?? '';
  const queryClient = useQueryClient();
  const hierarchyQueryKey = useMemo(
    () => ['device-hierarchy', selectedHierarchySerial ?? 'none'] as const,
    [selectedHierarchySerial]
  );
  const hierarchyQuery = useQuery({
    queryKey: hierarchyQueryKey,
    queryFn: () => fetchHierarchy(selectedHierarchySerial as string, false),
    enabled: false,
    refetchOnWindowFocus: false,
    staleTime: 1500,
    gcTime: 1000 * 60
  });
  const hierarchyXml = useMemo(
    () => hierarchyQuery.data ?? '',
    [hierarchyQuery.data]
  );
  const hierarchyLoading = hierarchyQuery.isFetching;

  const fetchAndSetHierarchy = useCallback(
    async (serial: string, refresh: boolean): Promise<string> => {
      if (!tabActive) return '';
      const xml = (await fetchHierarchy(serial, refresh)) ?? '';
      if (
        !canApplyDeviceScopedResult(serial, selectedDeviceSerialRef.current)
      ) {
        return '';
      }
      queryClient.setQueryData(['device-hierarchy', serial], xml);
      return xml;
    },
    [queryClient, tabActive]
  );

  useEffect(() => {
    setRecordXml(null);
    recordXmlRef.current = null;
    recordXmlSerialRef.current = null;
    pollingXmlRef.current = false;
    setPollingXml(false);
    lastHierarchyFetchAtRef.current = 0;
    lastHierarchyAppRef.current = '';
    if (selectedHierarchySerial) {
      queryClient.setQueryData(
        ['device-hierarchy', selectedHierarchySerial],
        ''
      );
    }
  }, [queryClient, selectedHierarchySerial]);

  const refreshHierarchy = useCallback(() => {
    if (!selectedHierarchySerial) return;
    fetchAndSetHierarchy(selectedHierarchySerial, true).catch((e) => {
      queryClient.setQueryData(
        hierarchyQueryKey,
        `${errorPrefix} ${String(e)}`
      );
    });
  }, [
    selectedHierarchySerial,
    fetchAndSetHierarchy,
    queryClient,
    hierarchyQueryKey,
    errorPrefix
  ]);

  // Bootstrap hierarchy on device select / app change. u2 may not be ready on the
  // first request after client-side navigation — retry until XML arrives instead
  // of leaving the tree blank until a full page refresh.
  useEffect(() => {
    if (
      !tabActive ||
      !autoRefreshHierarchy ||
      !selectedHierarchySerial ||
      hierarchyPaused
    )
      return;
    if (hierarchyXml?.trim()) return;
    lastHierarchyAppRef.current = selectedHierarchyApp;

    let cancelled = false;
    let attempts = 0;

    const bootstrap = async () => {
      while (!cancelled && attempts < HIERARCHY_BOOTSTRAP_MAX_ATTEMPTS) {
        attempts += 1;
        try {
          const xml = await fetchAndSetHierarchy(selectedHierarchySerial, true);
          if (xml?.trim() || cancelled) return;
        } catch {
          /* retry */
        }
        await new Promise((resolve) =>
          setTimeout(resolve, HIERARCHY_BOOTSTRAP_RETRY_MS)
        );
      }
    };

    const startBootstrap = () => {
      void bootstrap();
    };
    let idleId: number | undefined;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    if (typeof requestIdleCallback !== 'undefined') {
      idleId = requestIdleCallback(startBootstrap, { timeout: 2500 });
    } else {
      timeoutId = setTimeout(startBootstrap, 150);
    }

    return () => {
      cancelled = true;
      if (idleId !== undefined && typeof cancelIdleCallback !== 'undefined') {
        cancelIdleCallback(idleId);
      }
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [
    autoRefreshHierarchy,
    tabActive,
    selectedHierarchySerial,
    selectedHierarchyApp,
    hierarchyPaused,
    hierarchyXml,
    wsConnected,
    fetchAndSetHierarchy
  ]);

  // Refresh hierarchy when the foreground app changes.
  useEffect(() => {
    if (
      !tabActive ||
      !autoRefreshHierarchy ||
      !selectedHierarchySerial ||
      hierarchyPaused
    )
      return;
    const app = selectedHierarchyApp;
    if (lastHierarchyAppRef.current === app) return;
    lastHierarchyAppRef.current = app;
    const tid = setTimeout(() => {
      hierarchyQuery.refetch().catch((e) => {
        queryClient.setQueryData(
          hierarchyQueryKey,
          `${errorPrefix} ${String(e)}`
        );
      });
    }, 220);
    return () => clearTimeout(tid);
  }, [
    autoRefreshHierarchy,
    tabActive,
    selectedHierarchySerial,
    selectedHierarchyApp,
    hierarchyPaused,
    errorPrefix,
    hierarchyQuery,
    queryClient,
    hierarchyQueryKey
  ]);

  // Refresh hierarchy on interaction pulses (tap/swipe/drag/key...).
  useEffect(() => {
    if (
      !tabActive ||
      !autoRefreshHierarchy ||
      !selectedHierarchySerial ||
      hierarchyPaused
    )
      return;
    if (hierarchyRefreshPulse <= 0) return;
    const now = Date.now();
    if (
      now - lastHierarchyFetchAtRef.current <
      HIERARCHY_INTERACTION_FETCH_COOLDOWN_MS
    )
      return;
    const tid = setTimeout(() => {
      hierarchyQuery
        .refetch()
        .then(() => {
          lastHierarchyFetchAtRef.current = Date.now();
        })
        .catch((e) => {
          queryClient.setQueryData(
            hierarchyQueryKey,
            `${errorPrefix} ${String(e)}`
          );
        });
    }, 220);
    return () => clearTimeout(tid);
  }, [
    hierarchyRefreshPulse,
    tabActive,
    autoRefreshHierarchy,
    selectedHierarchySerial,
    hierarchyPaused,
    errorPrefix,
    hierarchyQuery,
    queryClient,
    hierarchyQueryKey
  ]);

  const parsedHierarchyNodes = useMemo(
    () => parseHierarchySelectorNodes(hierarchyXml),
    [hierarchyXml]
  );

  // ── Selector (manual tap) ────────────────────────────────────────────────
  const [selectorBy, setSelectorBy] = useState<
    | 'resource-id'
    | 'text'
    | 'xpath'
    | 'class name'
    | 'description'
    | 'descriptionContains'
    | 'descriptionStartsWith'
  >('text');
  const [selectorValue, setSelectorValue] = useState('');

  const handleTapSelector = useCallback(
    (options?: SendAndRecordOptions) => {
      const selectedDevice = selectedDeviceRef.current;
      if (!selectedDevice || !selectorValue.trim()) return;
      const by = selectorBy;
      const value = selectorValue.trim();
      sendAndRecord(
        { type: 'tap_selector', serial: selectedDevice.serial, by, value },
        options
      );
      if (recording) {
        recordStep(
          buildRecordedTapStep({
            by,
            value,
            rx: 0.5,
            ry: 0.5,
            selector: { by: by as any, value }
          }) as ScenarioStep
        );
      }
      toast.success(
        t('toast.tapSelectorSuccess', { by, value: value.slice(0, 30) })
      );
    },
    [selectorBy, selectorValue, sendAndRecord, recording, recordStep, t]
  );

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
      logs
    },

    record: {
      recording,
      toggleRecording,
      pollingXml,
      sendAndRecord,
      wsSend,
      setSkipTapRecordingWhilePick,
      handleToggleMode,
      handleRestart
    },

    steps: {
      items: steps,
      setItems: setSteps,
      addWait: addWaitStep,
      addFlow: addFlowStep,
      appendSteps,
      copyJson,
      openSave: openSaveDialog
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
      templateContext,
      orgScenarioContext,
      savingTemplate,
      saveToTemplate
    },

    hierarchy: {
      xml: hierarchyXml,
      loading: hierarchyLoading,
      autoRefresh: autoRefreshHierarchy,
      setAutoRefresh: setAutoRefreshHierarchy,
      refresh: refreshHierarchy,
      nodes: parsedHierarchyNodes,
      setPaused: setHierarchyPaused
    },

    selector: {
      by: selectorBy,
      setBy: setSelectorBy,
      value: selectorValue,
      setValue: setSelectorValue,
      tap: handleTapSelector
    }
  };
}
