'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { campaignsApi, scenariosApi } from '@/features/campaigns/services/api';
import type { ScenarioOut } from '@/features/campaigns/types';
import type { ScenarioStep } from '../types/scenario';
import { scenarioToJson } from '../types/scenario';
import { fetchHierarchy } from '../services/api';
import { useDeviceFarm } from './use-device-farm';
import {
  findSelectorInXml,
  getScreenSignature,
  hashXml,
  pollUntilUiChange
} from '../utils/control-record-xml';
import { parseHierarchySelectorNodes } from '../utils/hierarchy-selectors';
import { useTranslations } from 'next-intl';

export function useControlRecord(initialSerial?: string | null) {
  const t = useTranslations('devicesControlRecord');
  const loadingLabel = t('loading');
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

  const [selectedSerial, setSelectedSerial] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const recordingRef = useRef(false);
  const recordXmlRef = useRef<string | null>(null);
  const [recordXml, setRecordXml] = useState<string | null>(null);
  const [steps, setSteps] = useState<ScenarioStep[]>([]);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [campaigns, setCampaigns] = useState<{ id: string; name: string }[]>([]);
  const [savingCampaignId, setSavingCampaignId] = useState<string | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [campaignScenarios, setCampaignScenarios] = useState<ScenarioOut[]>([]);
  const [pollingXml, setPollingXml] = useState(false);
  const pollingXmlRef = useRef(false);
  const [hierarchyOpen, setHierarchyOpen] = useState(false);
  const [hierarchyXml, setHierarchyXml] = useState<string>('');
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

  useEffect(() => {
    recordingRef.current = recording;
  }, [recording]);
  useEffect(() => {
    recordXmlRef.current = recordXml;
  }, [recordXml]);

  const refreshRecordXml = useCallback(async (serial: string) => {
    try {
      const xml = await fetchHierarchy(serial, true);
      if (xml?.trim()) {
        setRecordXml(xml);
        recordXmlRef.current = xml;
        return xml;
      }
    } catch {
      /* ignore */
    }
    return null;
  }, []);

  const recordStep = useCallback((step: ScenarioStep) => {
    setSteps((s) => [...s, step]);
  }, []);

  const sendAndRecord = useCallback(
    (msg: object) => {
      wsSend(msg);
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
      if (m.type === 'tap' && typeof m.x === 'number' && typeof m.y === 'number') {
        const rx = parseFloat((m.x / w).toFixed(4));
        const ry = parseFloat((m.y / h).toFixed(4));
        const xml = pollingXmlRef.current ? null : recordXmlRef.current;

        if (xml) {
          const sel = findSelectorInXml(xml, rx, ry);
          const sig = getScreenSignature(xml);
          const screen = {
            package: sig.package || undefined,
            hash: hashXml(xml).toString(16),
            texts: sig.texts.length ? sig.texts : undefined
          };

          if (sel) {
            recordStep({
              type: 'tap',
              selector: { by: sel.by, value: sel.value },
              fallback: { rx, ry },
              screen
            } as ScenarioStep);
            toast.success(`tap ${sel.by}: "${sel.value.slice(0, 40)}"`, { duration: 2000 });
          } else {
            recordStep({ type: 'tap', fallback: { rx, ry }, screen } as ScenarioStep);
            toast.warning(t('toast.elementNotFound'), { duration: 3000 });
          }

          if (recordingRef.current) {
            const oldHash = hashXml(xml);
            pollingXmlRef.current = true;
            setPollingXml(true);
            pollUntilUiChange(selectedDevice.serial, oldHash).then((newXml) => {
              if (!recordingRef.current) return;
              if (newXml) {
                setRecordXml(newXml);
                recordXmlRef.current = newXml;
              }
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
      }
    },
    [wsSend, selectedDevice, recordStep]
  );

  const mode = selectedDevice ? (modes[selectedDevice.serial] ?? 'tap') : 'tap';

  const addWaitStep = useCallback(() => {
    setSteps((s) => [...s, { type: 'wait', seconds: 2 }]);
  }, []);

  const removeStep = useCallback((index: number) => {
    setSteps((s) => s.filter((_, i) => i !== index));
  }, []);

  const copyJson = useCallback(() => {
    const json = scenarioToJson(steps);
    navigator.clipboard.writeText(json).then(
      () => toast.success(t('toast.copyJsonSuccess')),
      () => toast.error(t('toast.copyJsonError'))
    );
  }, [steps]);

  const openSaveDialog = useCallback(() => {
    setSaveDialogOpen(true);
    setSelectedCampaignId(null);
    setCampaignScenarios([]);
    campaignsApi
      .list()
      .then((list) => setCampaigns(list.map((c) => ({ id: c.id, name: c.name }))))
      .catch(() => setCampaigns([]));
  }, []);

  const handlePickCampaign = useCallback((campaignId: string) => {
    setSelectedCampaignId(campaignId);
    setCampaignScenarios([]);
    scenariosApi
      .list(campaignId)
      .then(setCampaignScenarios)
      .catch(() => setCampaignScenarios([]));
  }, []);

  const saveToScenario = useCallback(
    (campaignId: string, scenarioId: string) => {
      setSavingCampaignId(scenarioId);
      scenariosApi
        .update(campaignId, scenarioId, { steps })
        .then(() => {
          toast.success(t('toast.saveStepsSuccess'));
          setSaveDialogOpen(false);
          setSelectedCampaignId(null);
        })
        .catch(() => toast.error(t('toast.saveFailed')))
        .finally(() => setSavingCampaignId(null));
    },
    [steps]
  );

  const saveAsNewScenario = useCallback(
    (campaignId: string) => {
      setSavingCampaignId('new');
      scenariosApi
        .create(campaignId, { name: t('newScenarioName', { time: new Date().toLocaleTimeString('vi-VN') }), steps })
        .then(() => {
          toast.success(t('toast.createScenarioSuccess'));
          setSaveDialogOpen(false);
          setSelectedCampaignId(null);
        })
        .catch(() => toast.error(t('toast.createScenarioFailed')))
        .finally(() => setSavingCampaignId(null));
    },
    [steps]
  );

  const loadHierarchy = useCallback(() => {
    if (!selectedDevice) return;
    setHierarchyOpen(true);
    setHierarchyXml(loadingLabel);
    fetchHierarchy(selectedDevice.serial, true)
      .then(setHierarchyXml)
      .catch((e) => {
        setHierarchyXml(`${errorPrefix} ${String(e)}`);
      });
  }, [selectedDevice]);

  const refreshHierarchy = useCallback(() => {
    if (!selectedDevice) return;
    setHierarchyXml((prev) => (prev === loadingLabel ? prev : loadingLabel));
    fetchHierarchy(selectedDevice.serial, true)
      .then(setHierarchyXml)
      .catch((e) => {
        setHierarchyXml(`${errorPrefix} ${String(e)}`);
      });
  }, [selectedDevice]);

  useEffect(() => {
    if (!hierarchyOpen || !selectedDevice) return;
    const id = setInterval(() => {
      fetchHierarchy(selectedDevice.serial)
        .then(setHierarchyXml)
        .catch((e) =>
          setHierarchyXml((prev) => (prev.startsWith(errorPrefix) ? prev : `${errorPrefix} ${String(e)}`))
        );
    }, 2000);
    return () => clearInterval(id);
  }, [hierarchyOpen, selectedDevice]);

  const parsedHierarchyNodes = useMemo(
    () => parseHierarchySelectorNodes(hierarchyXml),
    [hierarchyXml]
  );

  const handleTapSelector = useCallback(() => {
    if (!selectedDevice || !selectorValue.trim()) return;
    const by = selectorBy;
    const value = selectorValue.trim();
    wsSend({ type: 'tap_selector', serial: selectedDevice.serial, by, value });
    if (recording) {
      recordStep({ type: 'tap_selector', by, value });
    }
    toast.success(t('toast.tapSelectorSuccess', { by, value: value.slice(0, 30) }));
  }, [selectedDevice, selectorBy, selectorValue, wsSend, recording, recordStep]);

  const toggleRecording = useCallback(async () => {
    const next = !recording;
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
  }, [recording, selectedDevice, refreshRecordXml]);

  return {
    error,
    connectedDevices,
    selectedDevice,
    selectedSerial,
    setSelectedSerial,
    logs,
    sendAndRecord,
    modes,
    handleToggleMode,
    handleRestart,
    wsConnected,
    recording,
    pollingXml,
    refreshRecordXml,
    steps,
    mode,
    addWaitStep,
    removeStep,
    copyJson,
    openSaveDialog,
    saveDialogOpen,
    setSaveDialogOpen,
    campaigns,
    savingCampaignId,
    selectedCampaignId,
    setSelectedCampaignId,
    campaignScenarios,
    handlePickCampaign,
    saveToScenario,
    saveAsNewScenario,
    hierarchyOpen,
    setHierarchyOpen,
    hierarchyXml,
    loadHierarchy,
    refreshHierarchy,
    parsedHierarchyNodes,
    selectorBy,
    setSelectorBy,
    selectorValue,
    setSelectorValue,
    handleTapSelector,
    toggleRecording
  };
}
