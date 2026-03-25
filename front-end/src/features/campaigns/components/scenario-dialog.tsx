'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  useCampaignDevices,
  useCompileCampaignScenario,
  useUpdateCampaignScenario,
  useUpdateScenario,
  useCompileScenario,
} from '../hooks/use-campaigns';
import type { CampaignOut, ScenarioOut } from '../types';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { FileText, Trash2, Play, Circle, Square, RefreshCw, Sparkles } from 'lucide-react';
import { fetchHierarchy, previewScenario } from '@/features/devices/services/api';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';

/** Parse Android uiautomator2 XML in the browser, find best selector at (rx,ry) ratios. */
function findSelectorInXml(
  xmlStr: string,
  rx: number,
  ry: number
): { by: 'resource-id' | 'text' | 'xpath' | 'class name'; value: string } | null {
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xmlStr, 'text/xml');
  } catch {
    return null;
  }

  // Infer screen dimensions from root node bounds [0,0][dw][dh]
  const rootNode = doc.querySelector('node');
  const rootBounds = rootNode?.getAttribute('bounds') ?? '';
  const rootM = /\[0,0\]\[(\d+),(\d+)\]/.exec(rootBounds);
  const dw = rootM ? parseInt(rootM[1]) : 1080;
  const dh = rootM ? parseInt(rootM[2]) : 1920;

  const px = rx * dw;
  const py = ry * dh;

  const BOUNDS = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/;
  let best: { by: 'resource-id' | 'text' | 'xpath' | 'class name'; value: string } | null = null;
  let bestArea = Infinity;

  for (const node of Array.from(doc.getElementsByTagName('node'))) {
    const m = BOUNDS.exec(node.getAttribute('bounds') ?? '');
    if (!m) continue;
    const [x1, y1, x2, y2] = [+m[1], +m[2], +m[3], +m[4]];
    if (!(x1 <= px && px <= x2 && y1 <= py && py <= y2)) continue;
    const area = (x2 - x1) * (y2 - y1);
    if (area >= bestArea) continue;

    const text = (node.getAttribute('text') ?? '').trim();
    const rid = (node.getAttribute('resource-id') ?? '').trim();
    const desc = (node.getAttribute('content-desc') ?? '').trim();

    let sel: { by: 'resource-id' | 'text' | 'xpath' | 'class name'; value: string } | null = null;
    if (text && text.length < 80) {
      sel = { by: 'text' as const, value: text };
    } else if (rid && rid.includes('/')) {
      sel = { by: 'resource-id' as const, value: rid };
    } else if (desc && desc.length < 80) {
      sel = { by: 'xpath' as const, value: `//*[@content-desc="${desc.replace(/"/g, '\\"')}"]` };
    } else if (rid) {
      sel = { by: 'resource-id' as const, value: rid };
    }

    if (sel) { best = sel; bestArea = area; }
  }
  return best;
}

type SelectorBy = 'resource-id' | 'text' | 'xpath' | 'class name';

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
  | 'scroll_down';

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
  | { type: 'scroll_down'; repeats: number };

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
      case 'scroll_down':
        return { type: 'scroll_down', repeats: Number(s.repeats || 1) };
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
  const [previewingIndex, setPreviewingIndex] = useState<number | null>(null);
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

    if (scenarioProp) {
      // New 3-level: load from scenario row
      currentInstructions = scenarioProp.instructions ?? '';
      currentSteps = Array.isArray(scenarioProp.steps) ? coerceSteps(scenarioProp.steps) : [];
    } else {
      // Legacy: load from campaign.scenario field
      const sc: any = campaign.scenario ?? {};
      currentInstructions = sc.instructions ?? '';
      currentSteps = Array.isArray(sc.steps) ? coerceSteps(sc.steps) : [];
      const ctx: any = sc.device_context ?? {};
      currentDeviceModel = ctx.device_model ?? '';
      currentAndroidVersion = ctx.android_version ?? '';
      currentBrowserApp = ctx.browser_app ?? '';
      currentDeviceNotes = ctx.notes ?? '';
    }

    setInstructions(currentInstructions);
    setSteps(currentSteps);
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
    if (scenarioProp) {
      // New 3-level: save to scenario row
      saveScenarioRow(
        { campaignId: campaign.id, scenarioId: scenarioProp.id, data: { instructions, steps } },
        {
          onSuccess: () => { toast.success('Lưu kịch bản thành công'); setOpen(false); },
          onError: () => { toast.error('Lưu kịch bản thất bại'); },
        }
      );
    } else {
      // Legacy: save to campaign.scenario field
      const existing = (campaign.scenario as any) ?? {};
      const deviceContext = { device_model: deviceModel, android_version: androidVersion, browser_app: browserApp, notes: deviceNotes };
      const next: Record<string, any> = { ...existing, instructions, steps, device_context: deviceContext };
      saveScenario(
        { id: campaign.id, scenario: next },
        {
          onSuccess: () => { toast.success('Lưu kịch bản thành công'); setOpen(false); },
          onError: () => { toast.error('Lưu kịch bản thất bại'); },
        }
      );
    }
  };

  const handlePreviewAll = async () => {
    if (!previewSerial) {
      toast.error('Chọn thiết bị để test kịch bản');
      return;
    }
    if (!steps.length) {
      toast.error('Chưa có bước nào để test');
      return;
    }
    setPreviewingAll(true);
    try {
      const res = await previewScenario(previewSerial, steps as any[]);
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

  const handlePreviewUntil = async (index: number) => {
    if (!previewSerial) {
      toast.error('Chọn thiết bị để test');
      return;
    }
    if (!steps.length) return;
    const subset = steps.slice(0, index + 1);
    setPreviewingIndex(index);
    try {
      const res = await previewScenario(previewSerial, subset as any[]);
      const last =
        res.step_results && res.step_results.length
          ? res.step_results[res.step_results.length - 1]
          : null;
      if (last && !last.ok) {
        toast.error(last.message || `Bước #${index + 1} backend báo lỗi`);
      } else {
        toast.success(`Đã chạy kịch bản tới bước #${index + 1}`);
      }
    } catch {
      toast.error('Test bước thất bại');
    } finally {
      setPreviewingIndex(null);
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

  const handleRemoveStep = (index: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== index));
  };

  const handleStepTypeChange = (index: number, type: StepType) => {
    setSteps((prev) =>
      prev.map((s, i) => {
        if (i !== index) return s;
        switch (type) {
          case 'launch_app':
            return { type: 'launch_app', package: '' };
          case 'open_url':
            return { type: 'open_url', url: '', package: undefined };
          case 'wait':
            return { type: 'wait', seconds: 1 };
          case 'tap_position':
            return { type: 'tap_position', pos: 'middle_center' };
          case 'tap':
            return { type: 'tap', selector: { by: 'text', value: '' }, fallback: { rx: 0.5, ry: 0.5 }, timeout: 5 };
          case 'tap_ratio':
            return { type: 'tap_ratio', x: 0.5, y: 0.5 };
          case 'swipe_ratio':
            return { type: 'swipe_ratio', x1: 0.5, y1: 0.8, x2: 0.5, y2: 0.2, duration_ms: 300 };
          case 'tap_selector':
            return { type: 'tap_selector', by: 'text' as SelectorBy, value: '' };
          case 'wait_element':
            return { type: 'wait_element', by: 'text' as SelectorBy, value: '', timeout: 10 };
          case 'assert_element':
            return { type: 'assert_element', by: 'text' as SelectorBy, value: '', timeout: 5 };
          case 'input_selector':
            return { type: 'input_selector', by: 'resource-id' as SelectorBy, value: '', text: '', clear_first: true };
          case 'long_tap_selector':
            return { type: 'long_tap_selector', by: 'text' as SelectorBy, value: '', duration_ms: 800 };
          case 'scroll_to':
            return { type: 'scroll_to', by: 'text' as SelectorBy, value: '', direction: 'down', max_swipes: 5 };
          case 'wait_stable':
            return { type: 'wait_stable', timeout: 5, stable_duration: 0.4 };
          case 'dismiss_popup':
            return { type: 'dismiss_popup', retries: 3 };
          case 'input_text':
            return { type: 'input_text', via: 'u2', text: '' };
          case 'key':
            return { type: 'key', key: 'enter' };
          case 'scroll_down':
            return { type: 'scroll_down', repeats: 1 };
          default:
            return s;
        }
      })
    );
  };

  const updateStepField = (index: number, patch: Partial<Step>) => {
    setSteps((prev) =>
      prev.map((s, i) => (i === index ? { ...s, ...patch } as Step : s))
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {children ?? (
          <Button size="sm" variant="outline" className="gap-1 text-[10px]">
            <FileText size={10} />
            Kịch bản
          </Button>
        )}
      </DialogTrigger>
      <DialogContent
        className="z-[1000] max-w-5xl lg:max-w-6xl max-h-[90vh] overflow-hidden flex flex-col rounded-lg p-4"
      >
        <DialogHeader>
          <DialogTitle>
            {scenarioProp ? `Kịch bản: ${scenarioProp.name}` : 'Kịch bản campaign'}
          </DialogTitle>
        </DialogHeader>
        <div
          className="flex flex-col lg:flex-row gap-4 pt-2 min-h-0 flex-1 overflow-hidden"
        >
          <div
            className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden space-y-4 order-1"
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
                    <select
                      className="border bg-background px-1 py-0.5 rounded text-[11px]"
                      value={xmlSerial}
                      onChange={(e) => setXmlSerial(e.target.value)}
                    >
                      <option value="">Không gửi XML</option>
                      {devices.map((d) => (
                        <option key={d.id} value={d.serial}>
                          {d.name || d.serial}
                        </option>
                      ))}
                    </select>
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
                <Sparkles size={13} />
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
                <input
                  className="w-full border rounded px-1 py-0.5 bg-background text-[11px]"
                  value={deviceModel}
                  onChange={(e) => setDeviceModel(e.target.value)}
                  placeholder="Ví dụ: Galaxy S23, Pixel 8..."
                />
              </div>
              <div className="space-y-1">
                <p className="text-[11px] text-muted-foreground">Android version</p>
                <input
                  className="w-full border rounded px-1 py-0.5 bg-background text-[11px]"
                  value={androidVersion}
                  onChange={(e) => setAndroidVersion(e.target.value)}
                  placeholder="Ví dụ: Android 13, 14..."
                />
              </div>
              <div className="space-y-1">
                <p className="text-[11px] text-muted-foreground">Ưu tiên browser / app</p>
                <input
                  className="w-full border rounded px-1 py-0.5 bg-background text-[11px]"
                  value={browserApp}
                  onChange={(e) => setBrowserApp(e.target.value)}
                  placeholder="Ví dụ: Chrome, app Facebook..."
                />
              </div>
              <div className="space-y-1">
                <p className="text-[11px] text-muted-foreground">Ghi chú khác</p>
                <input
                  className="w-full border rounded px-1 py-0.5 bg-background text-[11px]"
                  value={deviceNotes}
                  onChange={(e) => setDeviceNotes(e.target.value)}
                  placeholder="Ví dụ: màn hình nhỏ, ưu tiên tap bằng text..."
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

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium">Các bước thực thi</p>
              <div className="flex items-center gap-2">
                {devices.length > 0 && (
                  <>
                    <select
                      className="border bg-background text-[11px] px-1 py-0.5 rounded"
                      value={previewSerial}
                      onChange={(e) => setPreviewSerial(e.target.value)}
                    >
                      <option value="">Chọn device để test</option>
                      {devices.map((d) => (
                        <option key={d.id} value={d.serial}>
                          {d.name || d.serial}
                        </option>
                      ))}
                    </select>
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
              <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {steps.map((step, index) => (
                  <div
                    key={index}
                    className="rounded border p-2 space-y-1 bg-muted/40"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-medium">
                        Bước #{index + 1}
                      </span>
                      <div className="flex items-center gap-2">
                        {previewSerial && (
                          <button
                            type="button"
                            className="p-1 text-primary hover:bg-primary/10 rounded disabled:opacity-50"
                            title="Chạy kịch bản tới bước này trên thiết bị đã chọn"
                            onClick={() => handlePreviewUntil(index)}
                            disabled={previewingIndex === index || previewingAll}
                          >
                            <Play size={12} />
                          </button>
                        )}
                        <select
                          className="border bg-background text-[11px] px-1 py-0.5 rounded"
                          value={step.type}
                          onChange={(e) =>
                            handleStepTypeChange(index, e.target.value as StepType)
                          }
                        >
                          <option value="launch_app">launch_app</option>
                          <option value="open_url">open_url</option>
                          <option value="wait">wait (cố định)</option>
                          <option value="tap_position">tap_position</option>
                          <option value="tap">tap ⚡ unified</option>
                          <option value="tap_ratio">tap_ratio</option>
                          <option value="swipe_ratio">swipe_ratio</option>
                          <optgroup label="── uiautomator2 ──">
                          <option value="tap_selector">tap_selector</option>
                          <option value="wait_element">wait_element ⚡</option>
                          <option value="assert_element">assert_element ✓</option>
                          <option value="input_selector">input_selector</option>
                          <option value="long_tap_selector">long_tap_selector</option>
                          <option value="scroll_to">scroll_to</option>
                          <option value="wait_stable">wait_stable</option>
                          <option value="dismiss_popup">dismiss_popup</option>
                          </optgroup>
                          <option value="input_text">input_text</option>
                          <option value="key">key</option>
                          <option value="scroll_down">scroll_down</option>
                        </select>
                        <button
                          type="button"
                          className="p-1 text-destructive hover:bg-destructive/10 rounded"
                          onClick={() => handleRemoveStep(index)}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>

                    {step.type === 'launch_app' && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="shrink-0">package:</span>
                        <input
                          className="flex-1 border rounded px-1 py-0.5 bg-background"
                          value={step.package}
                          onChange={(e) =>
                            updateStepField(index, { package: e.target.value } as any)
                          }
                          placeholder="com.android.chrome"
                        />
                      </div>
                    )}

                    {step.type === 'open_url' && (
                      <>
                        <div className="flex items-center gap-2 text-[11px]">
                          <span className="shrink-0">url:</span>
                          <input
                            className="flex-1 border rounded px-1 py-0.5 bg-background"
                            value={step.url}
                            onChange={(e) =>
                              updateStepField(index, { url: e.target.value } as any)
                            }
                            placeholder="https://www.google.com"
                          />
                        </div>
                        <div className="flex items-center gap-2 text-[11px]">
                          <span className="shrink-0">package (optional):</span>
                          <input
                            className="flex-1 border rounded px-1 py-0.5 bg-background"
                            value={step.package ?? ''}
                            onChange={(e) =>
                              updateStepField(index, { package: e.target.value || undefined } as any)
                            }
                            placeholder="com.android.chrome"
                          />
                        </div>
                      </>
                    )}
                    {step.type === 'wait' && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="shrink-0">seconds:</span>
                        <input
                          type="number"
                          min={0}
                          step={0.5}
                          className="w-20 border rounded px-1 py-0.5 bg-background"
                          value={step.seconds}
                          onChange={(e) =>
                            updateStepField(index, { seconds: Number(e.target.value) } as any)
                          }
                        />
                      </div>
                    )}

                    {step.type === 'tap_position' && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="shrink-0">pos:</span>
                        <select
                          className="border rounded px-1 py-0.5 bg-background"
                          value={step.pos}
                          onChange={(e) =>
                            updateStepField(index, { pos: e.target.value as any })
                          }
                        >
                          <option value="top_center">top_center</option>
                          <option value="search_bar">search_bar</option>
                          <option value="middle_center">middle_center</option>
                          <option value="bottom_center">bottom_center</option>
                        </select>
                      </div>
                    )}

                    {step.type === 'tap_ratio' && (
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <span className="shrink-0">x:</span>
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          className="w-20 border rounded px-1 py-0.5 bg-background"
                          value={step.x}
                          onChange={(e) =>
                            updateStepField(index, { x: Number(e.target.value) } as any)
                          }
                        />
                        <span className="shrink-0">y:</span>
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          className="w-20 border rounded px-1 py-0.5 bg-background"
                          value={step.y}
                          onChange={(e) =>
                            updateStepField(index, { y: Number(e.target.value) } as any)
                          }
                        />
                      </div>
                    )}

                    {step.type === 'tap' && (
                      <div className="space-y-1 text-[11px]">
                        <div className="flex items-center gap-2">
                          <span className="shrink-0">selector by:</span>
                          <select
                            className="border rounded px-1 py-0.5 bg-background"
                            value={step.selector?.by ?? 'text'}
                            onChange={(e) =>
                              updateStepField(index, {
                                selector: { ...(step.selector ?? {}), by: e.target.value as SelectorBy },
                              } as any)
                            }
                          >
                            <option value="text">text</option>
                            <option value="resource-id">resource-id</option>
                            <option value="xpath">xpath</option>
                            <option value="class name">class name</option>
                          </select>
                          <span className="shrink-0">timeout:</span>
                          <input
                            type="number"
                            min={1}
                            className="w-14 border rounded px-1 py-0.5 bg-background"
                            value={step.timeout ?? 5}
                            onChange={(e) => updateStepField(index, { timeout: Number(e.target.value) } as any)}
                          />
                          <span className="text-muted-foreground">s</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="shrink-0">selector value:</span>
                          <input
                            className="flex-1 border rounded px-1 py-0.5 bg-background font-mono"
                            value={step.selector?.value ?? ''}
                            onChange={(e) =>
                              updateStepField(index, {
                                selector: { ...(step.selector ?? {}), value: e.target.value },
                              } as any)
                            }
                            placeholder="Text/id/xpath để tap"
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="shrink-0">fallback rx,ry:</span>
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.05}
                            className="w-16 border rounded px-1 py-0.5 bg-background"
                            value={step.fallback?.rx ?? 0.5}
                            onChange={(e) =>
                              updateStepField(index, {
                                fallback: { ...(step.fallback ?? {}), rx: Number(e.target.value) },
                              } as any)
                            }
                          />
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.05}
                            className="w-16 border rounded px-1 py-0.5 bg-background"
                            value={step.fallback?.ry ?? 0.5}
                            onChange={(e) =>
                              updateStepField(index, {
                                fallback: { ...(step.fallback ?? {}), ry: Number(e.target.value) },
                              } as any)
                            }
                          />
                        </div>
                      </div>
                    )}

                    {step.type === 'tap_selector' && (
                      <div className="space-y-1 text-[11px]">
                        <div className="flex items-center gap-2">
                          <span className="shrink-0">by:</span>
                          <select
                            className="border rounded px-1 py-0.5 bg-background"
                            value={step.by}
                            onChange={(e) =>
                              updateStepField(index, { by: e.target.value as 'text' | 'resource-id' | 'xpath' | 'class name' } as any)
                            }
                          >
                            <option value="text">text</option>
                            <option value="resource-id">resource-id</option>
                            <option value="xpath">xpath</option>
                            <option value="class name">class name</option>
                          </select>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="shrink-0">value:</span>
                          <input
                            className="flex-1 border rounded px-1 py-0.5 bg-background font-mono"
                            value={step.value}
                            onChange={(e) =>
                              updateStepField(index, { value: e.target.value } as any)
                            }
                            placeholder="Đăng nhập | id/btn_ok | //node[@text='OK']"
                          />
                        </div>
                      </div>
                    )}

                    {(step.type === 'wait_element' || step.type === 'assert_element') && (
                      <div className="space-y-1 text-[11px]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="shrink-0 text-primary font-medium">{step.type === 'wait_element' ? '⚡ Smart wait' : '✓ Assert'}</span>
                          <select
                            className="border rounded px-1 py-0.5 bg-background"
                            value={step.by}
                            onChange={(e) => updateStepField(index, { by: e.target.value } as any)}
                          >
                            <option value="text">text</option>
                            <option value="resource-id">resource-id</option>
                            <option value="xpath">xpath</option>
                          </select>
                          <input
                            className="flex-1 min-w-[120px] border rounded px-1 py-0.5 bg-background font-mono"
                            value={step.value}
                            onChange={(e) => updateStepField(index, { value: e.target.value } as any)}
                            placeholder="Tên element cần đợi/kiểm tra"
                          />
                          <span className="shrink-0">timeout:</span>
                          <input
                            type="number" min={1} max={60}
                            className="w-12 border rounded px-1 py-0.5 bg-background"
                            value={step.timeout ?? (step.type === 'wait_element' ? 10 : 5)}
                            onChange={(e) => updateStepField(index, { timeout: Number(e.target.value) } as any)}
                          />
                          <span className="text-muted-foreground">s</span>
                        </div>
                      </div>
                    )}

                    {step.type === 'input_selector' && (
                      <div className="space-y-1 text-[11px]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <select
                            className="border rounded px-1 py-0.5 bg-background"
                            value={step.by}
                            onChange={(e) => updateStepField(index, { by: e.target.value } as any)}
                          >
                            <option value="resource-id">resource-id</option>
                            <option value="text">text</option>
                            <option value="xpath">xpath</option>
                          </select>
                          <input
                            className="flex-1 min-w-[100px] border rounded px-1 py-0.5 bg-background font-mono"
                            value={step.value}
                            onChange={(e) => updateStepField(index, { value: e.target.value } as any)}
                            placeholder="id/edit_text hoặc 'Search'"
                          />
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="shrink-0">text:</span>
                          <input
                            className="flex-1 border rounded px-1 py-0.5 bg-background"
                            value={step.text}
                            onChange={(e) => updateStepField(index, { text: e.target.value } as any)}
                            placeholder="Nội dung gõ vào"
                          />
                        </div>
                      </div>
                    )}

                    {step.type === 'long_tap_selector' && (
                      <div className="space-y-1 text-[11px]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <select
                            className="border rounded px-1 py-0.5 bg-background"
                            value={step.by}
                            onChange={(e) => updateStepField(index, { by: e.target.value } as any)}
                          >
                            <option value="text">text</option>
                            <option value="resource-id">resource-id</option>
                            <option value="xpath">xpath</option>
                          </select>
                          <input
                            className="flex-1 min-w-[100px] border rounded px-1 py-0.5 bg-background font-mono"
                            value={step.value}
                            onChange={(e) => updateStepField(index, { value: e.target.value } as any)}
                            placeholder="Element để long press"
                          />
                          <span className="shrink-0">ms:</span>
                          <input
                            type="number" min={300}
                            className="w-16 border rounded px-1 py-0.5 bg-background"
                            value={step.duration_ms ?? 800}
                            onChange={(e) => updateStepField(index, { duration_ms: Number(e.target.value) } as any)}
                          />
                        </div>
                      </div>
                    )}

                    {step.type === 'scroll_to' && (
                      <div className="space-y-1 text-[11px]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <select
                            className="border rounded px-1 py-0.5 bg-background"
                            value={step.by}
                            onChange={(e) => updateStepField(index, { by: e.target.value } as any)}
                          >
                            <option value="text">text</option>
                            <option value="resource-id">resource-id</option>
                            <option value="xpath">xpath</option>
                          </select>
                          <input
                            className="flex-1 min-w-[100px] border rounded px-1 py-0.5 bg-background font-mono"
                            value={step.value}
                            onChange={(e) => updateStepField(index, { value: e.target.value } as any)}
                            placeholder="Element cần tìm"
                          />
                          <select
                            className="border rounded px-1 py-0.5 bg-background"
                            value={step.direction ?? 'down'}
                            onChange={(e) => updateStepField(index, { direction: e.target.value } as any)}
                          >
                            <option value="down">scroll xuống</option>
                            <option value="up">scroll lên</option>
                          </select>
                          <input
                            type="number" min={1} max={20}
                            className="w-12 border rounded px-1 py-0.5 bg-background"
                            value={step.max_swipes ?? 5}
                            onChange={(e) => updateStepField(index, { max_swipes: Number(e.target.value) } as any)}
                          />
                          <span className="text-muted-foreground">lần</span>
                        </div>
                      </div>
                    )}

                    {step.type === 'wait_stable' && (
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <span className="shrink-0">timeout:</span>
                        <input
                          type="number"
                          min={0.5}
                          step={0.1}
                          className="w-16 border rounded px-1 py-0.5 bg-background"
                          value={step.timeout ?? 5}
                          onChange={(e) => updateStepField(index, { timeout: Number(e.target.value) } as any)}
                        />
                        <span className="shrink-0">stable_duration:</span>
                        <input
                          type="number"
                          min={0.1}
                          step={0.1}
                          className="w-16 border rounded px-1 py-0.5 bg-background"
                          value={step.stable_duration ?? 0.4}
                          onChange={(e) => updateStepField(index, { stable_duration: Number(e.target.value) } as any)}
                        />
                      </div>
                    )}

                    {step.type === 'dismiss_popup' && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="shrink-0">retries:</span>
                        <input
                          type="number"
                          min={1}
                          max={10}
                          className="w-16 border rounded px-1 py-0.5 bg-background"
                          value={step.retries ?? 3}
                          onChange={(e) => updateStepField(index, { retries: Number(e.target.value) } as any)}
                        />
                      </div>
                    )}

                    {step.type === 'swipe_ratio' && (
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <span className="shrink-0">x1,y1:</span>
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          className="w-14 border rounded px-1 py-0.5 bg-background"
                          value={step.x1}
                          onChange={(e) =>
                            updateStepField(index, { x1: Number(e.target.value) } as any)
                          }
                        />
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          className="w-14 border rounded px-1 py-0.5 bg-background"
                          value={step.y1}
                          onChange={(e) =>
                            updateStepField(index, { y1: Number(e.target.value) } as any)
                          }
                        />
                        <span className="shrink-0">x2,y2:</span>
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          className="w-14 border rounded px-1 py-0.5 bg-background"
                          value={step.x2}
                          onChange={(e) =>
                            updateStepField(index, { x2: Number(e.target.value) } as any)
                          }
                        />
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          className="w-14 border rounded px-1 py-0.5 bg-background"
                          value={step.y2}
                          onChange={(e) =>
                            updateStepField(index, { y2: Number(e.target.value) } as any)
                          }
                        />
                        <span className="shrink-0">ms:</span>
                        <input
                          type="number"
                          min={50}
                          className="w-16 border rounded px-1 py-0.5 bg-background"
                          value={step.duration_ms ?? 300}
                          onChange={(e) =>
                            updateStepField(index, { duration_ms: Number(e.target.value) } as any)
                          }
                        />
                      </div>
                    )}

                    {step.type === 'input_text' && (
                      <div className="space-y-1 text-[11px]">
                        <div className="flex items-center gap-2">
                          <span className="shrink-0">via:</span>
                          <select
                            className="border rounded px-1 py-0.5 bg-background"
                            value={step.via}
                            onChange={(e) =>
                              updateStepField(index, { via: e.target.value as any })
                            }
                          >
                            <option value="u2">u2</option>
                            <option value="a11y_key">a11y_key</option>
                          </select>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="shrink-0">text:</span>
                          <input
                            className="flex-1 border rounded px-1 py-0.5 bg-background"
                            value={step.text}
                            onChange={(e) =>
                              updateStepField(index, { text: e.target.value } as any)
                            }
                            placeholder="nội dung cần nhập..."
                          />
                        </div>
                      </div>
                    )}

                    {step.type === 'key' && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="shrink-0">key:</span>
                        <input
                          className="w-32 border rounded px-1 py-0.5 bg-background"
                          value={step.key}
                          onChange={(e) =>
                            updateStepField(index, { key: e.target.value } as any)
                          }
                          placeholder="enter / back / home"
                        />
                      </div>
                    )}

                    {step.type === 'scroll_down' && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="shrink-0">repeats:</span>
                        <input
                          type="number"
                          min={1}
                          className="w-20 border rounded px-1 py-0.5 bg-background"
                          value={step.repeats}
                          onChange={(e) =>
                            updateStepField(index, { repeats: Number(e.target.value) } as any)
                          }
                        />
                      </div>
                    )}
                  </div>
                ))}
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
          {xmlSerial && (
            <div className="flex shrink-0 w-[360px] min-w-[360px] flex-col border-l border-border pl-4 overflow-y-auto order-2 self-start">
              <div className="flex items-center justify-between mb-2 shrink-0">
                <p className="text-xs font-medium text-muted-foreground">Điều khiển thiết bị</p>
                <Button
                  size="sm"
                  variant={recording ? 'destructive' : 'outline'}
                  className="h-6 gap-1 text-[11px] px-2"
                  onClick={async () => {
                    const next = !recording;
                    if (next && xmlSerial) {
                      // Fetch XML immediately when starting recording
                      toast.info('Đang lấy XML màn hình hiện tại…');
                      const xml = await refreshRecordXml(xmlSerial);
                      if (!xml) return; // Don't start recording if no XML
                      toast.success('XML sẵn sàng — bắt đầu ghi kịch bản');
                    } else {
                      setRecordXml(null);
                    }
                    setRecording(next);
                  }}
                  title={recording ? 'Dừng ghi kịch bản' : 'Bật ghi: lấy XML → mỗi tap tự thêm tap_selector'}
                >
                  {recording
                    ? <><Square size={10} className="fill-current" /> Dừng ghi</>
                    : <><Circle size={10} className="text-red-500 fill-red-500" /> Ghi kịch bản</>
                  }
                </Button>
              </div>
              {recording && (
                <div className="flex items-center justify-between mb-1.5 rounded bg-amber-50 dark:bg-amber-950/30 px-2 py-1">
                  <p className="text-[10px] text-amber-700 dark:text-amber-400">
                    {recordXml
                      ? <>Đang ghi — tap để thêm <code>tap_selector</code>. Sau khi chuyển màn hình bấm làm mới.</>
                      : <span className="text-destructive">Chưa có XML — tap sẽ ra tap_ratio</span>
                    }
                  </p>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-5 gap-1 text-[10px] px-1.5 shrink-0"
                    disabled={refreshingXml}
                    onClick={() => xmlSerial && refreshRecordXml(xmlSerial)}
                    title="Làm mới XML sau khi chuyển sang màn hình mới"
                  >
                    <RefreshCw size={9} className={refreshingXml ? 'animate-spin' : ''} />
                    {refreshingXml ? 'Đang lấy…' : 'Làm mới XML'}
                  </Button>
                </div>
              )}
              <DeviceControlEmbed
                initialSerial={xmlSerial}
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


