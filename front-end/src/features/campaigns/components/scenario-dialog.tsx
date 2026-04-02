'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  useCampaignDevices,
  useCompileCampaignScenario,
  useScenarios,
  useUpdateCampaignScenario,
  useUpdateScenario,
  useCompileScenario,
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
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { FileText, Trash2, Circle, Square, RefreshCw, Sparkles, FolderOpen } from 'lucide-react';
import { fetchHierarchy, previewScenario } from '@/features/devices/services/api';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
import { VariableEditor } from '@/components/variable-editor';
import { FlowEditor } from './flow-editor';
import { validateScenarioStepsForApi } from '../utils/validate-scenario-steps-for-api';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { findSelectorInXml } from '@/features/devices/utils/control-record-xml';

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
  if (lower === 'content-desc' || lower === 'contentdesc' || lower === 'description' || lower === 'accessibilityid') {
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

function sanitizeScenarioStep(step: any): any {
  if (!step || typeof step !== 'object') return step;
  const next: any = { ...step };

  if (next.by != null) {
    next.by = normalizeSelectorBy(next.by);
  }
  if (next.type === 'repeat') {
    const c = Number(next.count);
    if (!Number.isFinite(c) || c < 1) next.count = 3;
  }
  if (next.type === 'random_pick' && Array.isArray(next.branches)) {
    next.branches = next.branches.filter((br: any) => Array.isArray(br?.steps) && br.steps.length > 0);
  }
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
    next.branches = next.branches.map((br: any) => {
      if (!br || typeof br !== 'object') return br;
      return {
        ...br,
        ...(Array.isArray(br.steps) ? { steps: br.steps.map(sanitizeScenarioStep) } : {}),
      };
    });
  }

  return next;
}

function sanitizeScenarioStepsForApi(input: unknown): any[] {
  if (!Array.isArray(input)) return [];
  return input.map(sanitizeScenarioStep);
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
  | { type: 'tap_position'; pos: 'top_center' | 'middle_center' | 'bottom_center' | 'search_bar' }
  | { type: 'tap'; selector?: { by?: SelectorBy; value?: string }; fallback?: { rx?: number; ry?: number }; timeout?: number }
  | { type: 'tap_ratio'; x: number; y: number }
  | { type: 'swipe_ratio'; x1: number; y1: number; x2: number; y2: number; duration_ms?: number }
  | { type: 'tap_selector'; by: SelectorBy; value: string; fallback_rx?: number; fallback_ry?: number; timeout?: number }
  | { type: 'wait_element'; by: SelectorBy; value: string; timeout?: number }
  | { type: 'assert_element'; by: SelectorBy; value: string; timeout?: number }
  | { type: 'input_selector'; by: SelectorBy; value: string; text: string; clear_first?: boolean }
  | { type: 'long_tap_selector'; by: SelectorBy; value: string; duration_ms?: number }
  | { type: 'scroll_to'; by: SelectorBy; value: string; direction?: 'down' | 'up'; max_swipes?: number }
  | { type: 'wait_stable'; timeout?: number; stable_duration?: number }
  | { type: 'dismiss_popup'; retries?: number }
  | { type: 'input_text'; via: 'u2' | 'a11y_key'; text: string }
  | { type: 'key'; key: string }
  | { type: 'scroll_down'; repeats: number; start_x_ratio?: number | string }
  | { type: 'set_variable'; name: string; value?: string; from_list?: string[]; increment?: number }
  | { type: 'run_scenario'; scenario_id?: string; scenario_name?: string; variables?: Record<string, any> };

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
          package: (s.package != null && String(s.package).trim()) ? String(s.package).trim() : undefined
        };
      case 'wait':
        return { type: 'wait', seconds: Number(s.seconds || 0) };
      case 'tap_position':
        return {
          type: 'tap_position',
          pos: (s.pos === 'top_center' || s.pos === 'bottom_center' || s.pos === 'middle_center' || s.pos === 'search_bar')
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
                  ...(s.selector.value != null ? { value: String(s.selector.value) } : {}),
                },
              }
            : {}),
          ...(s.fallback && typeof s.fallback === 'object'
            ? {
                fallback: {
                  ...(s.fallback.rx != null ? { rx: Number(s.fallback.rx) } : {}),
                  ...(s.fallback.ry != null ? { ry: Number(s.fallback.ry) } : {}),
                },
              }
            : {}),
          ...(s.timeout != null ? { timeout: Number(s.timeout) } : {}),
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
      case 'tap_selector':
        return {
          type: 'tap_selector',
          by: (['resource-id','text','xpath','class name'].includes(s.by) ? s.by : 'text') as SelectorBy,
          value: String(s.value ?? ''),
          ...(s.fallback_rx != null ? { fallback_rx: Number(s.fallback_rx) } : {}),
          ...(s.fallback_ry != null ? { fallback_ry: Number(s.fallback_ry) } : {}),
        };
      case 'wait_element':
        return {
          type: 'wait_element',
          by: (['resource-id','text','xpath','class name'].includes(s.by) ? s.by : 'text') as SelectorBy,
          value: String(s.value ?? ''),
          timeout: Number(s.timeout ?? 10),
        };
      case 'assert_element':
        return {
          type: 'assert_element',
          by: (['resource-id','text','xpath','class name'].includes(s.by) ? s.by : 'text') as SelectorBy,
          value: String(s.value ?? ''),
          timeout: Number(s.timeout ?? 5),
        };
      case 'input_selector':
        return {
          type: 'input_selector',
          by: (['resource-id','text','xpath','class name'].includes(s.by) ? s.by : 'resource-id') as SelectorBy,
          value: String(s.value ?? ''),
          text: String(s.text ?? ''),
          clear_first: s.clear_first !== false,
        };
      case 'long_tap_selector':
        return {
          type: 'long_tap_selector',
          by: (['resource-id','text','xpath','class name'].includes(s.by) ? s.by : 'text') as SelectorBy,
          value: String(s.value ?? ''),
          duration_ms: Number(s.duration_ms ?? 800),
        };
      case 'scroll_to':
        return {
          type: 'scroll_to',
          by: (['resource-id','text','xpath','class name'].includes(s.by) ? s.by : 'text') as SelectorBy,
          value: String(s.value ?? ''),
          direction: s.direction === 'up' ? 'up' : 'down',
          max_swipes: Number(s.max_swipes ?? 5),
        };
      case 'wait_stable':
        return {
          type: 'wait_stable',
          ...(s.timeout != null ? { timeout: Number(s.timeout) } : {}),
          ...(s.stable_duration != null ? { stable_duration: Number(s.stable_duration) } : {}),
        };
      case 'dismiss_popup':
        return {
          type: 'dismiss_popup',
          ...(s.retries != null ? { retries: Number(s.retries) } : {}),
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
          ...(Array.isArray(s.from_list) ? { from_list: s.from_list.map(String) } : {}),
          ...(s.increment != null ? { increment: Number(s.increment) } : {})
        };
      default:
        // Keep unknown step types visible instead of silently converting to wait(0).
        // This preserves DB data and avoids misleading UI.
        return s as Step;
    }
  });
}

export function ScenarioDialog({ campaign, scenario: scenarioProp, children }: Props) {
  const [open, setOpen] = useState(false);
  const [instructions, setInstructions] = useState('');
  const [steps, setSteps] = useState<Step[]>([]);
  const [variables, setVariables] = useState<Record<string, any>>({});
  const [rawJson, setRawJson] = useState('');
  const [deviceModel, setDeviceModel] = useState('');
  const [androidVersion, setAndroidVersion] = useState('');
  const [browserApp, setBrowserApp] = useState('');
  const [deviceNotes, setDeviceNotes] = useState('');
  // Legacy (campaign.scenario field)
  const { mutate: saveScenario, isPending: savingLegacy } = useUpdateCampaignScenario();
  const { mutate: compileScenario, isPending: compilingLegacy } = useCompileCampaignScenario();
  // New (scenario row)
  const { mutate: saveScenarioRow, isPending: savingRow } = useUpdateScenario();
  const { mutate: compileScenarioRow, isPending: compilingRow } = useCompileScenario();
  const isPending = scenarioProp ? savingRow : savingLegacy;
  const compiling = scenarioProp ? compilingRow : compilingLegacy;
  const { data: devices = [] } = useCampaignDevices(campaign.id);
  const [previewSerial, setPreviewSerial] = useState('');
  const [xmlSerial, setXmlSerial] = useState('');
  /** Nhiều màn hình: mỗi lần "Thu thập XML" = 1 snapshot từ màn hình hiện tại */
  const [collectedXmls, setCollectedXmls] = useState<Array<{ id: string; xml: string }>>([]);
  const [previewingAll, setPreviewingAll] = useState(false);
  const [fetchingXml, setFetchingXml] = useState(false);
  const [recording, setRecording] = useState(false);
  const recordingRef = useRef(false);
  /** XML cached from device — used for instant tap→selector without backend roundtrip */
  const [recordXml, setRecordXml] = useState<string | null>(null);
  const recordXmlRef = useRef<string | null>(null);
  const [refreshingXml, setRefreshingXml] = useState(false);

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
        toast.success(`Đã thêm màn hình #${collectedXmls.length + 1} (${trimmed.length.toLocaleString()} ký tự)`);
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

  useEffect(() => { recordingRef.current = recording; }, [recording]);
  useEffect(() => { recordXmlRef.current = recordXml; }, [recordXml]);

  const refreshRecordXml = useCallback(async (serial: string) => {
    if (!serial) return;
    setRefreshingXml(true);
    try {
      const xml = await fetchHierarchy(serial, true);
      if (xml?.trim()) {
        setRecordXml(xml.trim());
        return xml.trim();
      } else {
        toast.error('Thiết bị không trả XML — kiểm tra u2/uiautomator2 có đang chạy không');
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
  const handleRecordTap = useCallback((serial: string, rx: number, ry: number) => {
    if (!recordingRef.current) return;
    const xml = recordXmlRef.current;
    const rx3 = parseFloat(rx.toFixed(3));
    const ry3 = parseFloat(ry.toFixed(3));

    if (xml) {
      const sel = findSelectorInXml(xml, rx, ry);
      if (sel) {
        setSteps((prev) => [...prev, { type: 'tap_selector', by: sel.by, value: sel.value, fallback_rx: rx3, fallback_ry: ry3 }]);
        toast.success(`tap_selector by=${sel.by}: "${sel.value}"`, { duration: 2000 });
      } else {
        // XML có nhưng không tìm thấy element có text/id — flat XML (STF u2 limitation)
        setSteps((prev) => [...prev, { type: 'tap_ratio', x: rx3, y: ry3 }]);
        toast.warning(
          'XML không có UI elements — dùng tap_ratio. Cần bật Accessibility Service trên thiết bị để ghi tap_selector.',
          { duration: 5000 }
        );
      }
      setTimeout(() => { if (recordingRef.current) refreshRecordXml(serial); }, 1000);
    } else {
      setSteps((prev) => [...prev, { type: 'tap_ratio', x: rx3, y: ry3 }]);
      toast.info('Thêm tap_ratio — bấm "Ghi kịch bản" để lấy XML trước', { duration: 3000 });
    }
  }, [refreshRecordXml]);

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
    if (!open) return;
    let currentInstructions = '';
    let currentSteps: Step[] = [];
    let currentDeviceModel = '';
    let currentAndroidVersion = '';
    let currentBrowserApp = '';
    let currentDeviceNotes = '';

    let currentVariables: Record<string, any> = {};

    if (scenarioProp) {
      // New 3-level: load from scenario row
      currentInstructions = scenarioProp.instructions ?? '';
      currentSteps = Array.isArray(scenarioProp.steps) ? coerceSteps(scenarioProp.steps) : [];
      currentVariables = (scenarioProp as any).variables ?? {};
    } else {
      // Legacy: load from campaign.scenario field
      const sc: any = campaign.scenario ?? {};
      currentInstructions = sc.instructions ?? '';
      currentSteps = Array.isArray(sc.steps) ? coerceSteps(sc.steps) : [];
      currentVariables = sc.variables ?? campaign.variables ?? {};
      const ctx: any = sc.device_context ?? {};
      currentDeviceModel = ctx.device_model ?? '';
      currentAndroidVersion = ctx.android_version ?? '';
      currentBrowserApp = ctx.browser_app ?? '';
      currentDeviceNotes = ctx.notes ?? '';
    }

    setInstructions(currentInstructions);
    setSteps(currentSteps);
    setVariables(currentVariables);
    setDeviceModel(currentDeviceModel);
    setAndroidVersion(currentAndroidVersion);
    setBrowserApp(currentBrowserApp);
    setDeviceNotes(currentDeviceNotes);
    setRawJson(
      JSON.stringify({ instructions: currentInstructions, steps: currentSteps }, null, 2)
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, campaign.scenario, scenarioProp]);

  // Initialize xmlSerial once per dialog open when devices are available.
  // Separate from the form-reset effect so that device selection does not
  // trigger a form reset.
  const xmlSerialInitedRef = useRef(false);
  useEffect(() => {
    if (!open) { xmlSerialInitedRef.current = false; return; }
    if (!xmlSerialInitedRef.current && devices.length > 0 && !xmlSerial) {
      xmlSerialInitedRef.current = true;
      setXmlSerial(devices[0].serial);
    }
  }, [open, devices, xmlSerial]);

  // Khi đổi thiết bị thì xóa toàn bộ XML đã thu (mỗi thiết bị một bộ snapshot)
  useEffect(() => {
    setCollectedXmls([]);
  }, [xmlSerial]);

  const handleSave = () => {
    const sanitizedSteps = sanitizeScenarioStepsForApi(steps);
    const check = validateScenarioStepsForApi(sanitizedSteps);
    if (!check.ok) {
      toast.error(check.message);
      return;
    }
    if (scenarioProp) {
      // New 3-level: save to scenario row
      saveScenarioRow(
        { campaignId: campaign.id, scenarioId: scenarioProp.id, data: { instructions, steps: sanitizedSteps, variables } },
        {
          onSuccess: () => { toast.success('Lưu kịch bản thành công'); setOpen(false); },
          onError: (err) => { toast.error(formatFarmApiError(err, 'Lưu kịch bản thất bại')); },
        }
      );
    } else {
      // Legacy: save to campaign.scenario field
      const existing = (campaign.scenario as any) ?? {};
      const deviceContext = { device_model: deviceModel, android_version: androidVersion, browser_app: browserApp, notes: deviceNotes };
      const next: Record<string, any> = { ...existing, instructions, steps: sanitizedSteps, variables, device_context: deviceContext };
      saveScenario(
        { id: campaign.id, scenario: next },
        {
          onSuccess: () => { toast.success('Lưu kịch bản thành công'); setOpen(false); },
          onError: (err) => { toast.error(formatFarmApiError(err, 'Lưu kịch bản thất bại')); },
        }
      );
    }
  };

  const handlePreviewAll = async () => {
    if (!previewSerial) {
      toast.error('Chọn thiết bị để test kịch bản');
      return;
    }
    const sanitizedSteps = sanitizeScenarioStepsForApi(steps);
    if (!sanitizedSteps.length) {
      toast.error('Chưa có bước nào để test');
      return;
    }
    setPreviewingAll(true);
    try {
      const res = await previewScenario(previewSerial, sanitizedSteps);
      const failed =
        res.step_results?.filter((r) => r && typeof r.ok === 'boolean' && !r.ok) ?? [];
      if (failed.length > 0) {
        const idxList = failed.map((r) => `#${(r.index ?? 0) + 1}`).join(', ');
        toast.error(`Một số bước lỗi: ${idxList}`);
      } else {
        toast.success('Đã gửi toàn bộ kịch bản lên thiết bị (backend không báo lỗi step)');
      }
    } catch {
      toast.error('Test kịch bản thất bại');
    } finally {
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
          (s, i) =>
            `\n\n--- UI hierarchy (màn hình ${i + 1}) ---\n\n${s.xml}`
        )
        .join('');
      toast.info(`Đang gửi ${collectedXmls.length} màn hình vào prompt AI…`);
    } else if (xmlSerial) {
      deviceSerial = xmlSerial;
      toast.info('Backend sẽ gọi uiautomator2 lấy XML từ thiết bị, đang gọi AI…');
    }
    if (scenarioProp) {
      // New: compile and save to scenario row
      compileScenarioRow(
        { campaignId: campaign.id, scenarioId: scenarioProp.id, instructions: text, uiXml, deviceSerial, deviceContext },
        {
          onSuccess: (data) => {
            setInstructions(data.instructions ?? text);
            setSteps(Array.isArray(data.steps) ? coerceSteps(data.steps) : []);
            toast.success('AI đã tạo kịch bản từ mô tả');
          },
          onError: () => { toast.error('Gọi AI sinh kịch bản thất bại'); },
        }
      );
    } else {
      // Legacy: compile and save to campaign.scenario
      compileScenario(
        { id: campaign.id, instructions: text, uiXml, deviceSerial, deviceContext },
        {
          onSuccess: (data) => {
            const sc: any = data.scenario ?? {};
            setInstructions(sc.instructions ?? text);
            const currentSteps = Array.isArray(sc.steps) ? coerceSteps(sc.steps) : [];
            setSteps(currentSteps);
            toast.success('AI đã tạo kịch bản từ mô tả');
          },
          onError: () => { toast.error('Gọi AI sinh kịch bản thất bại'); },
        }
      );
    }
  };

  const handleApplyJson = () => {
    const text = rawJson.trim();
    if (!text) {
      toast.error('JSON rỗng');
      return;
    }
    try {
      const parsed = JSON.parse(text);
      const sc: any =
        parsed.scenario && Array.isArray(parsed.scenario?.steps)
          ? parsed.scenario
          : parsed;

      if (!Array.isArray(sc.steps) || sc.steps.length === 0) {
        toast.error('JSON phải có steps là một mảng không rỗng');
        return;
      }
      const nextInstructions = String(sc.instructions ?? '');
      const nextSteps = coerceSteps(sc.steps);
      const ctx: any = sc.device_context ?? {};
      setDeviceModel(String(ctx.device_model ?? ''));
      setAndroidVersion(String(ctx.android_version ?? ''));
      setBrowserApp(String(ctx.browser_app ?? ''));
      setDeviceNotes(String(ctx.notes ?? ''));
      setInstructions(nextInstructions);
      setSteps(nextSteps);
      setRawJson(JSON.stringify({ instructions: nextInstructions, steps: nextSteps }, null, 2));
      toast.success('Đã áp dụng JSON vào kịch bản');
    } catch {
      toast.error('JSON không hợp lệ');
    }
  };

  const handleAddStep = () => {
    setSteps((prev) => [
      ...prev,
      { type: 'launch_app', package: '' }
    ]);
  };


  /** Other scenarios in the campaign — used for the "load from template" picker. */
  const { data: allScenarios = [] } = useScenarios(campaign.id);
  const loadableScenarios = useMemo(
    () => allScenarios.filter((s) => s.id !== scenarioProp?.id && Array.isArray(s.steps) && s.steps.length > 0),
    [allScenarios, scenarioProp?.id]
  );

  const handleLoadFromScenario = (scenarioId: string) => {
    const source = allScenarios.find((s) => s.id === scenarioId);
    if (!source) return;
    if (steps.length > 0 && !window.confirm(`Kịch bản hiện tại có ${steps.length} bước. Tải từ "${source.name}" sẽ ghi đè — tiếp tục?`)) return;
    setSteps(Array.isArray(source.steps) ? coerceSteps(source.steps) : []);
    if (source.instructions) setInstructions(source.instructions);
    toast.success(`Đã tải ${(source.steps as any[]).length} bước từ "${source.name}"`);
  };

  /** Luôn có thiết bị xem trước khi campaign có device — tránh cột phải trống khi chọn "Không gửi XML". */
  const embedSerial = xmlSerial || devices[0]?.serial || '';

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {children ?? (
          <Button size="sm" variant="outline" className="gap-1 text-[10px]">
            <FileText size={12} strokeWidth={2} className="opacity-80" />
            Kịch bản
          </Button>
        )}
      </DialogTrigger>
      <DialogContent
        className="z-[1000] max-w-5xl lg:max-w-6xl max-h-[92vh] min-h-0 md:min-h-[48vh] overflow-hidden flex flex-col rounded-lg p-3 sm:p-4 gap-0 sm:max-w-[min(100%-2rem,72rem)] [&>button.absolute]:right-3 [&>button.absolute]:top-3 [&>button.absolute]:h-7 [&>button.absolute]:w-7 [&>button.absolute_svg]:!size-3.5"
      >
        <DialogHeader className="shrink-0">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <DialogTitle className="text-base">
              {scenarioProp ? `Kịch bản: ${scenarioProp.name}` : 'Kịch bản campaign'}
            </DialogTitle>
            {loadableScenarios.length > 0 && (
              <div className="flex items-center gap-1.5">
                <FolderOpen size={12} className="text-muted-foreground shrink-0" />
                <span className="text-[11px] text-muted-foreground whitespace-nowrap">Tải từ kịch bản:</span>
                <Select onValueChange={handleLoadFromScenario}>
                  <SelectTrigger className="h-7 text-[11px] w-[160px]">
                    <SelectValue placeholder="Chọn kịch bản…" />
                  </SelectTrigger>
                  <SelectContent>
                    {loadableScenarios.map((s) => (
                      <SelectItem key={s.id} value={s.id} className="text-[11px]">
                        {s.name} ({(s.steps as any[]).length} bước)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </DialogHeader>
        <Separator className="shrink-0" />
        <div
          className="flex flex-col lg:flex-row gap-4 pt-2 min-h-0 flex-1 overflow-hidden"
        >
          <div
            className="min-w-0 flex-1 min-h-[12rem] overflow-y-auto overflow-x-hidden space-y-4 order-1"
          >
          <div className="space-y-1">
            <p className="text-xs font-medium">Mô tả (ngôn ngữ tự nhiên)</p>
            <p className="text-[11px] text-muted-foreground">
              Ví dụ: &quot;Vào Google, tìm tin tức công nghệ hôm nay, mở kết quả đầu tiên và kéo xuống cuối trang&quot;.
            </p>
            <Textarea
              className="h-24 text-[11px]"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
            />
            {devices.length > 0 && (
              <p className="text-[11px] text-muted-foreground">
                Để AI sinh đúng selector (tap_selector, input_text): chọn thiết bị → <strong>Mở điều khiển</strong> → vào đúng màn hình cần automation (tap, mở app…) → quay lại đây bấm <strong>Sinh kịch bản bằng AI</strong> (sẽ lấy XML từ màn hình hiện tại).
              </p>
            )}
            <div className="flex flex-wrap items-center justify-between pt-1 gap-2">
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                {devices.length > 0 && (
                  <>
                    <span>Thiết bị để lấy UI XML:</span>
                    <Select value={xmlSerial || '_none'} onValueChange={(v) => setXmlSerial(v === '_none' ? '' : v)}>
                      <SelectTrigger className="h-6 text-[11px] w-[140px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="_none" className="text-[11px]">Không gửi XML</SelectItem>
                        {devices.map((d) => (
                          <SelectItem key={d.id} value={d.serial} className="text-[11px]">
                            {d.name || d.serial}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {xmlSerial && (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={handleFetchXml}
                          disabled={fetchingXml}
                        >
                          {fetchingXml ? 'Đang thu thập…' : 'Thu thập XML'}
                        </Button>
                        <span className="text-[10px] text-muted-foreground">
                          Mỗi lần bấm = 1 màn hình. Điều khiển bên phải, chuyển màn rồi thu thập. Sinh kịch bản sẽ gửi tất cả vào prompt AI.
                        </span>
                        {collectedXmls.length > 0 && (
                          <>
                            <span className="text-[11px] text-green-600 dark:text-green-400 font-medium">
                              Đã thu {collectedXmls.length} màn hình
                            </span>
                            <Button size="sm" variant="ghost" className="h-7 text-[10px]" onClick={clearAllCollectedXmls}>
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
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {collectedXmls.map((s, i) => (
                    <span
                      key={s.id}
                      className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-[11px]"
                    >
                      Màn hình {i + 1} ({(s.xml.length / 1000).toFixed(1)}k)
                      <button
                        type="button"
                        className="p-0.5 text-destructive hover:bg-destructive/10 rounded"
                        onClick={() => removeCollectedXml(s.id)}
                        title="Xóa màn hình này"
                      >
                        <Trash2 size={10} />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <Button
                size="sm"
                variant="default"
                className="gap-1.5 bg-[#10a37f] hover:bg-[#0d8f6f] text-white border-0"
                onClick={handleCompile}
                disabled={compiling}
                title="Gửi mô tả + XML lên OpenAI (ChatGPT) để sinh kịch bản"
              >
                <Sparkles size={12} strokeWidth={2} className="shrink-0 opacity-90" />
                {compiling ? 'ChatGPT đang sinh…' : 'Sinh bằng ChatGPT'}
              </Button>
            </div>
          </div>

          <div className="space-y-1">
            <p className="text-xs font-medium">Thông tin thiết bị (tùy chọn)</p>
            <p className="text-[11px] text-muted-foreground">
              Gợi ý cho AI về loại máy sẽ chạy campaign này (không bắt buộc, chỉ là hint).
            </p>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <p className="text-[11px] text-muted-foreground">Model / dòng máy</p>
                <Input
                  className="h-7 text-[11px]"
                  value={deviceModel}
                  onChange={(e) => setDeviceModel(e.target.value)}
                  placeholder="Galaxy S23, Pixel 8…"
                />
              </div>
              <div className="space-y-1">
                <p className="text-[11px] text-muted-foreground">Android version</p>
                <Input
                  className="h-7 text-[11px]"
                  value={androidVersion}
                  onChange={(e) => setAndroidVersion(e.target.value)}
                  placeholder="Android 13, 14…"
                />
              </div>
              <div className="space-y-1">
                <p className="text-[11px] text-muted-foreground">Ưu tiên browser / app</p>
                <Input
                  className="h-7 text-[11px]"
                  value={browserApp}
                  onChange={(e) => setBrowserApp(e.target.value)}
                  placeholder="Chrome, Facebook…"
                />
              </div>
              <div className="space-y-1">
                <p className="text-[11px] text-muted-foreground">Ghi chú khác</p>
                <Input
                  className="h-7 text-[11px]"
                  value={deviceNotes}
                  onChange={(e) => setDeviceNotes(e.target.value)}
                  placeholder="màn hình nhỏ, ưu tiên tap bằng text…"
                />
              </div>
            </div>
          </div>

          <div className="space-y-1">
            <p className="text-xs font-medium">Raw scenario JSON (optional)</p>
            <p className="text-[11px] text-muted-foreground">
              Paste <code className="rounded bg-muted px-1">{'{"scenario": {...}}'}</code> or{' '}
              <code className="rounded bg-muted px-1">{'{"instructions": ..., "steps": [...]}'}</code>. Sẽ ghi đè form bên dưới.
            </p>
            <Textarea
              className="h-32 font-mono text-[11px]"
              value={rawJson}
              onChange={(e) => setRawJson(e.target.value)}
              placeholder='{"instructions": "...", "steps": [...]}'
            />
            <div className="flex justify-end pt-1">
              <Button size="sm" variant="outline" onClick={handleApplyJson}>
                Áp dụng JSON
              </Button>
            </div>
          </div>

          {/* DF-001: Variables */}
          <div className="space-y-2">
            <details className="group">
              <summary className="cursor-pointer text-xs font-medium flex items-center gap-1">
                <span>Biến (Variables)</span>
                <span className="text-muted-foreground font-normal">
                  — {'${VAR}'} trong steps sẽ được thay thế khi chạy
                </span>
              </summary>
              <div className="pt-2 space-y-2">
                <VariableEditor
                  variables={variables}
                  onChange={setVariables}
                />
                <p className="text-[10px] text-muted-foreground leading-relaxed">
                  Crawl nhóm FB (ví dụ):{' '}
                  <code className="rounded bg-muted px-1 font-mono">GROUP_NAME</code>,{' '}
                  <code className="rounded bg-muted px-1 font-mono">GROUP_XPATH</code>,{' '}
                  <code className="rounded bg-muted px-1 font-mono">MAX_SCROLLS</code>,{' '}
                  <code className="rounded bg-muted px-1 font-mono">SCROLL_X_RATIO</code>{' '}
                  (dùng trong <code className="rounded bg-muted px-1 font-mono">scroll_down.start_x_ratio</code>),{' '}
                  <code className="rounded bg-muted px-1 font-mono">SAVE_COLLECTION</code>.
                </p>
              </div>
            </details>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium">Các bước thực thi</p>
              <div className="flex items-center gap-2">
                {devices.length > 0 && (
                  <>
                    <Select value={previewSerial || '_none'} onValueChange={(v) => setPreviewSerial(v === '_none' ? '' : v)}>
                      <SelectTrigger className="h-6 text-[11px] w-[140px]">
                        <SelectValue placeholder="Chọn device để test" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="_none" className="text-[11px]">Chọn device để test</SelectItem>
                        {devices.map((d) => (
                          <SelectItem key={d.id} value={d.serial} className="text-[11px]">
                            {d.name || d.serial}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handlePreviewAll}
                      disabled={previewingAll || !steps.length || !previewSerial}
                    >
                      {previewingAll ? 'Đang test…' : 'Test toàn bộ'}
                    </Button>
                  </>
                )}
                <Button size="sm" variant="outline" onClick={handleAddStep}>
                  Thêm bước
                </Button>
              </div>
            </div>

            {steps.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">
                Chưa có bước nào. Bạn có thể dùng AI để sinh hoặc tự thêm step thủ công.
              </p>
            ) : (
              <div>
                <FlowEditor
                  steps={steps as any[]}
                  onChange={(newSteps) => setSteps(newSteps as Step[])}
                  maxHeight="min(380px, 42vh)"
                  compact
                />
              </div>
            )}
          </div>


          <div className="flex justify-end gap-2 pt-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={isPending || compiling}
            >
              Đóng
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={isPending}
            >
              {isPending ? 'Đang lưu…' : 'Lưu kịch bản'}
            </Button>
          </div>
          </div>
          {devices.length > 0 && embedSerial && (
            <div className="flex min-h-0 w-full shrink-0 flex-col self-stretch border-t border-border pt-3 order-2 lg:w-[320px] lg:min-w-[320px] lg:border-l lg:border-t-0 lg:pt-0 lg:pl-3 overflow-y-auto lg:max-h-full max-h-[min(52vh,520px)]">
              {!xmlSerial && (
                <p className="mb-2 rounded-md bg-muted/50 px-2 py-1 text-[10px] text-muted-foreground">
                  Đang xem <span className="font-mono text-foreground">{embedSerial.slice(0, 12)}…</span>
                  . Chọn thiết bị ở &quot;Thiết bị để lấy UI XML&quot; nếu cần XML khác cho AI.
                </p>
              )}
              <div className="flex items-center justify-between mb-2 shrink-0 gap-2">
                <p className="text-[11px] font-medium text-muted-foreground">Điều khiển</p>
                <Button
                  size="sm"
                  variant={recording ? 'destructive' : 'outline'}
                  className="h-7 gap-1 text-[10px] px-2"
                  onClick={async () => {
                    const next = !recording;
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
                  title={recording ? 'Dừng ghi kịch bản' : 'Bật ghi: lấy XML → mỗi tap tự thêm tap_selector'}
                >
                  {recording ? (
                    <>
                      <Square size={9} className="fill-current" /> Dừng ghi
                    </>
                  ) : (
                    <>
                      <Circle size={9} className="text-red-500 fill-red-500" /> Ghi
                    </>
                  )}
                </Button>
              </div>
              {recording && (
                <div className="mb-1.5 flex items-center justify-between gap-1 rounded bg-amber-50 px-2 py-1 dark:bg-amber-950/30">
                  <p className="text-[10px] text-amber-800 dark:text-amber-400">
                    {recordXml ? (
                      <>
                        Đang ghi — tap → <code className="text-[9px]">tap_selector</code>. Đổi màn → làm mới XML.
                      </>
                    ) : (
                      <span className="text-destructive">Chưa có XML — tap → tap_ratio</span>
                    )}
                  </p>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 shrink-0 gap-0.5 px-1.5 text-[10px]"
                    disabled={refreshingXml}
                    onClick={() => {
                      const s = xmlSerial || devices[0]?.serial;
                      if (s) void refreshRecordXml(s);
                    }}
                    title="Làm mới XML sau khi đổi màn hình"
                  >
                    <RefreshCw size={10} className={refreshingXml ? 'animate-spin' : ''} />
                    {refreshingXml ? '…' : 'Làm mới'}
                  </Button>
                </div>
              )}
              <DeviceControlEmbed
                initialSerial={embedSerial}
                compact
                onTap={recording ? (serial, rx, ry) => handleRecordTap(serial, rx, ry) : undefined}
              />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}


