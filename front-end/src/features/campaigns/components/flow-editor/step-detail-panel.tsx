'use client';

import { useEffect, useState } from 'react';
import { Crosshair, MousePointerClick, Move } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { VariableEditor } from '@/components/variable-editor';
import { RunScenarioFields, type RunScenarioCampaignOption } from '../scenario-steps/run-scenario-editor';
import type { FlowStep } from '../scenario-steps/types';
import { getStepTypeName } from './constants';
import { StepIcon } from './step-icon';
interface Props {
  step: FlowStep;
  onChange: (step: FlowStep) => void;
  onClose: () => void;
  availableVariables?: string[];
  /** Called when user wants to pick a selector from the device screen/tree. Should close the panel first. */
  onRequestPickSelector?: () => void;
  /** Pick single tap ratios on mirror (tap_ratio / tap fallback). */
  onRequestPickTapCoords?: () => void;
  /** Pick swipe segment on mirror (swipe_ratio). */
  onRequestPickSwipeCoords?: () => void;
  /** Other scenarios in the campaign — for run_scenario picker (templates always loaded inside RunScenarioFields). */
  campaignScenarios?: RunScenarioCampaignOption[];
}

const SELECTOR_OPTIONS = [
  'text',
  'resource-id',
  'xpath',
  'class name',
  'description',
  'descriptionContains',
  'descriptionStartsWith',
  'content-desc',
] as const;

function F({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className='space-y-1.5'>
      <Label className='text-xs font-medium leading-none text-foreground'>{label}</Label>
      {children}
    </div>
  );
}

/** Value field + variable insert: stacks on narrow widths so the select never squeezes the input. */
function valueInsertRowClassName() {
  return 'flex min-w-0 flex-col gap-2 sm:flex-row sm:items-stretch sm:gap-2';
}

function JsonTextarea({
  label,
  value,
  onCommit,
  placeholder,
}: {
  label: string;
  value: unknown;
  onCommit: (next: unknown | undefined) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(value == null ? '' : JSON.stringify(value, null, 2));

  useEffect(() => {
    setDraft(value == null ? '' : JSON.stringify(value, null, 2));
  }, [value]);

  return (
    <F label={label}>
      <textarea
        className='min-h-[92px] w-full rounded border bg-background px-2 py-1.5 text-xs font-mono'
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const trimmed = draft.trim();
          if (!trimmed) return onCommit(undefined);
          try {
            onCommit(JSON.parse(trimmed));
          } catch {
            // keep draft while invalid JSON
          }
        }}
      />
    </F>
  );
}

const BUILTIN_VARIABLE_TOKENS = [
  '${__NOW__}',
  '${__DATE__}',
  '${__TIME__}',
  '${__DEVICE_SERIAL__}',
  '${__DEVICE_MODEL__}',
  '${__RANDOM_INT_1_100__}',
  '${__RANDOM_UUID__}',
  '${__STEP_INDEX__}',
  // Account rotation — injected when the scenario is bound to an account group.
  // Password is resolved at Temporal runtime from __ACCOUNT_ID__ so plaintext
  // never lands in the workflow event history.
  '${__ACCOUNT_ID__}',
  '${__ACCOUNT_USERNAME__}',
  '${__ACCOUNT_PASSWORD__}',
  '${__ACCOUNT_DISPLAY_NAME__}',
  '${__ACCOUNT_PLATFORM__}',
] as const;

function insertToken(raw: string, token: string): string {
  const current = raw ?? '';
  if (!current.trim()) return token;
  const m = current.match(/\$\{[^}]+\}/g);
  const existingTokens: string[] = m ? [...m] : [];
  if (existingTokens.includes(token)) return current;
  return `${current} ${token}`.trim();
}

function VariableInsertSelect({
  availableVariables,
  onInsert,
  t,
}: {
  availableVariables: string[];
  onInsert: (token: string) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  const [selection, setSelection] = useState('');
  return (
    <select
      className='h-9 w-full shrink-0 rounded-md border border-input bg-background px-2 py-1.5 text-xs shadow-sm sm:w-[13rem]'
      value={selection}
      onChange={(e) => {
        const token = e.target.value;
        if (!token) return;
        onInsert(token);
        setSelection('');
      }}
    >
      <option value=''>{t('variableInsert.placeholder')}</option>
      {availableVariables.length > 0 && (
        <optgroup label={t('variableInsert.availableVariables')}>
          {availableVariables.map((name) => {
            const token = `\${${name}}`;
            return (
              <option key={name} value={token}>
                {token}
              </option>
            );
          })}
        </optgroup>
      )}
      <optgroup label={t('variableInsert.builtinVariables')}>
        {BUILTIN_VARIABLE_TOKENS.map((token) => (
          <option key={token} value={token}>
            {token}
          </option>
        ))}
      </optgroup>
    </select>
  );
}

function SelectorFields({ step, onChange, onRequestPickSelector, availableVariables, t }: {
  step: FlowStep;
  onChange: (s: FlowStep) => void;
  onRequestPickSelector?: () => void;
  availableVariables: string[];
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <>
      <div className='flex items-center justify-between'>
        <Label className='text-[11px]'>Selector</Label>
        {onRequestPickSelector && (
          <Button
            size='sm'
            variant='outline'
            className='h-6 gap-1 px-2 text-[10px] text-amber-700 border-amber-400/50 hover:bg-amber-50 dark:text-amber-400 dark:hover:bg-amber-950/30'
            onClick={onRequestPickSelector}
          >
            <Crosshair size={10} />
            Chọn từ màn hình
          </Button>
        )}
      </div>
      <F label='Loại selector'>
        <select className='w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.by ?? 'text'} onChange={(e) => onChange({ ...step, by: e.target.value })}>
          {SELECTOR_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </F>
      <F label='Giá trị selector'>
        <div className={valueInsertRowClassName()}>
          <Input className='h-9 min-w-0 flex-1 text-xs' value={step.value ?? ''} onChange={(e) => onChange({ ...step, value: e.target.value })} placeholder='VD: Đăng nhập hoặc com.app:id/btn' />
          <VariableInsertSelect
            availableVariables={availableVariables}
            t={t}
            onInsert={(token) => onChange({ ...step, value: insertToken(step.value ?? '', token) })}
          />
        </div>
      </F>
    </>
  );
}

export function StepDetailPanel({
  step,
  onChange,
  onClose: _onClose,
  availableVariables = [],
  onRequestPickSelector,
  onRequestPickTapCoords,
  onRequestPickSwipeCoords,
  campaignScenarios = [],
}: Props) {
  const t = useTranslations('campaignsFeature.stepEditor');
  const typeName = getStepTypeName(step.type);
  const update = (fields: Partial<FlowStep>) => onChange({ ...step, ...fields });
  const isVarRef = (v: string) => /^\$\{[^}]+\}$/.test(v);
  const parseNumOrVar = (raw: string, fallback: number): number | string => {
    const v = raw.trim();
    if (!v) return fallback;
    if (isVarRef(v)) return v;
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  };
  const extractParentMode = step.parent_post_id_var ? 'custom' : 'auto';
  const parentLinkMode =
    step.parent_id_var === '_active_comment_parent_hash'
      ? 'auto'
      : step.parent_id_var
        ? 'custom'
        : 'none';
  const doubleTapCoordMode = step.rx != null && step.ry != null ? 'ratio' : 'absolute';
  const pinchCoordMode = step.rx != null && step.ry != null ? 'ratio' : 'absolute';
  const dragCoordMode =
    step.rx1 != null && step.ry1 != null && step.rx2 != null && step.ry2 != null
      ? 'ratio'
      : 'absolute';

  return (
    <div className='flex flex-col bg-card'>
      <div className='flex items-center gap-2.5 border-b px-3 py-2.5'>
        <StepIcon type={step.type} size={16} />
        <span className='min-w-0 truncate text-sm font-semibold tracking-tight'>{typeName}</span>
      </div>

      <div className='max-h-[70vh] space-y-3 overflow-y-auto p-3 sm:p-4'>
        {/* Title & description — user-defined labels for any step */}
        <F label={t('common.titleOptional')}>
          <Input
            className='h-9 text-sm'
            placeholder={t('common.titlePlaceholder')}
            value={(step as any).title ?? ''}
            onChange={(e) => update({ title: e.target.value || undefined } as any)}
          />
        </F>
        <F label={t('common.descriptionOptional')}>
          <Input
            className='h-9 text-sm'
            placeholder={t('common.descriptionPlaceholder')}
            value={(step as any).description ?? ''}
            onChange={(e) => update({ description: e.target.value || undefined } as any)}
          />
        </F>
        {step.type === 'tap' && (
          <>
            <p className='rounded bg-muted/60 px-2 py-1.5 text-[11px] text-muted-foreground'>
              Bước ghi tự động. Gắn selector để chạm đúng phần tử; tọa độ là dự phòng khi không tìm thấy selector.
            </p>

            <div className='space-y-2 rounded-md border border-border/60 p-2.5'>
              <div className='flex items-center justify-between'>
                <span className='text-[11px] font-semibold text-foreground'>Selector phần tử</span>
                {onRequestPickSelector && (
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-6 gap-1 px-2 text-[10px] text-amber-700 border-amber-400/50 hover:bg-amber-50 dark:text-amber-400 dark:hover:bg-amber-950/30'
                    onClick={onRequestPickSelector}
                  >
                    <Crosshair size={10} />
                    Chọn từ màn hình
                  </Button>
                )}
              </div>
              <F label='Loại selector'>
                <select className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                  value={step.selector?.by ?? 'text'}
                  onChange={(e) => update({ selector: { ...(step.selector ?? {}), by: e.target.value } })}>
                  {SELECTOR_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </F>
              <F label='Giá trị'>
                <Input className='h-8 text-xs' placeholder='VD: Đăng nhập hoặc com.app:id/btn_login'
                  value={step.selector?.value ?? ''}
                  onChange={(e) => update({ selector: { ...(step.selector ?? {}), value: e.target.value } })} />
              </F>
            </div>

            {/* Fallback coords */}
            <div className='space-y-2 rounded-md border border-border/60 p-2.5'>
              <div className='flex items-center justify-between'>
                <span className='text-[11px] font-semibold text-foreground'>Tọa độ dự phòng</span>
                {onRequestPickTapCoords && (
                  <Button
                    size='sm'
                    variant='outline'
                    className='h-6 gap-1 px-2 text-[10px] text-sky-800 border-sky-400/50 hover:bg-sky-50 dark:text-sky-300 dark:hover:bg-sky-950/30'
                    onClick={onRequestPickTapCoords}
                  >
                    <MousePointerClick size={10} />
                    Chạm mirror lấy tọa độ
                  </Button>
                )}
              </div>
              <div className='grid grid-cols-2 gap-2'>
                <div><Label className='text-[10px] text-muted-foreground'>X (0–1)</Label>
                  <Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs'
                    value={step.fallback?.rx ?? 0.5}
                    onChange={(e) => update({ fallback: { ...(step.fallback ?? {}), rx: parseFloat(e.target.value) || 0 } })} /></div>
                <div><Label className='text-[10px] text-muted-foreground'>Y (0–1)</Label>
                  <Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs'
                    value={step.fallback?.ry ?? 0.5}
                    onChange={(e) => update({ fallback: { ...(step.fallback ?? {}), ry: parseFloat(e.target.value) || 0 } })} /></div>
              </div>
            </div>

            <F label='Timeout tap (giây)'>
              <Input type='number' min={0.1} step={0.1} className='h-8 w-28 text-xs' value={step.timeout ?? 4} onChange={(e) => update({ timeout: Math.max(0.1, Number(e.target.value) || 0.1) })} />
            </F>
          </>
        )}

        {step.type === 'launch_app' && (
          <>
            <F label='Tên package'>
              <Input className='h-8 text-xs font-mono' value={step.package ?? ''} onChange={(e) => update({ package: e.target.value })} placeholder='com.android.chrome' />
            </F>
            <F label='Wait sau khi mở app (giây)'>
              <Input type='number' min={0} step={0.1} className='h-8 w-28 text-xs' value={step.wait_after ?? 2} onChange={(e) => update({ wait_after: Number(e.target.value) || 0 })} />
            </F>
          </>
        )}

        {step.type === 'open_url' && (
          <>
            <F label='URL'>
              <div className={valueInsertRowClassName()}>
                <Input className='h-9 min-w-0 flex-1 text-xs' value={step.url ?? ''} onChange={(e) => update({ url: e.target.value })} />
                <VariableInsertSelect
                  availableVariables={availableVariables}
                  t={t}
                  onInsert={(token) => update({ url: insertToken(step.url ?? '', token) })}
                />
              </div>
            </F>
            <F label='Package trình duyệt'><Input className='h-8 text-xs font-mono' value={step.package ?? ''} onChange={(e) => update({ package: e.target.value || undefined })} /></F>
          </>
        )}

        {step.type === 'wait' && <F label='Thời gian (giây)'><Input type='number' min={0} step={0.5} className='h-8 w-24 text-xs' value={step.seconds ?? 1} onChange={(e) => update({ seconds: Number(e.target.value) || 0 })} /></F>}

        {['tap_selector', 'wait_element', 'assert_element', 'scroll_to', 'long_tap_selector'].includes(step.type) && (
          <>
            <SelectorFields
              step={step}
              onChange={onChange}
              onRequestPickSelector={onRequestPickSelector}
              availableVariables={availableVariables}
              t={t}
            />
            {step.type !== 'long_tap_selector' && (
              <F label='Timeout (giây)'>
                <Input type='number' min={0.1} step={0.1} className='h-8 w-24 text-xs' value={step.timeout ?? (step.type === 'wait_element' ? 10 : step.type === 'assert_element' ? 5 : 8)} onChange={(e) => update({ timeout: Math.max(0.1, Number(e.target.value) || 0.1) })} />
              </F>
            )}
            {(step.type === 'wait_element' || step.type === 'assert_element') && (
              <F label='Poll interval (giây)'>
                <Input type='number' min={0.1} step={0.1} className='h-8 w-24 text-xs' value={step.poll ?? 0.5} onChange={(e) => update({ poll: Math.max(0.1, Number(e.target.value) || 0.1) })} />
              </F>
            )}
            {step.type === 'tap_selector' && (
              <div className='grid grid-cols-2 gap-2'>
                <F label='fallback_rx (0-1)'>
                  <Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.fallback_rx ?? 0.5} onChange={(e) => update({ fallback_rx: Number(e.target.value) || 0 })} />
                </F>
                <F label='fallback_ry (0-1)'>
                  <Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.fallback_ry ?? 0.5} onChange={(e) => update({ fallback_ry: Number(e.target.value) || 0 })} />
                </F>
              </div>
            )}
            {step.type === 'scroll_to' && (
              <div className='grid grid-cols-2 gap-2'>
                <F label='Hướng cuộn'>
                  <select className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.direction ?? 'down'} onChange={(e) => update({ direction: e.target.value })}>
                    <option value='down'>down</option>
                    <option value='up'>up</option>
                  </select>
                </F>
                <F label='max_swipes'>
                  <Input type='number' min={1} className='h-8 text-xs' value={step.max_swipes ?? 5} onChange={(e) => update({ max_swipes: Number(e.target.value) || 1 })} />
                </F>
              </div>
            )}
            {step.type === 'long_tap_selector' && <F label='Thời gian giữ (ms)'><Input type='number' min={100} className='h-8 w-24 text-xs' value={step.duration_ms ?? 800} onChange={(e) => update({ duration_ms: Number(e.target.value) })} /></F>}
          </>
        )}

        {step.type === 'tap_ratio' && (
          <div className='space-y-2'>
            {onRequestPickTapCoords && (
              <Button
                size='sm'
                variant='outline'
                className='h-7 w-full gap-1.5 text-[10px] text-sky-800 border-sky-400/50 hover:bg-sky-50 dark:text-sky-300 dark:hover:bg-sky-950/30'
                onClick={onRequestPickTapCoords}
              >
                <MousePointerClick size={12} />
                Chạm trên mirror để lấy tọa độ (CHẠM TỌA ĐỘ)
              </Button>
            )}
            <div className='grid grid-cols-2 gap-2'>
              <F label='X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.x ?? 0.5} onChange={(e) => update({ x: parseFloat(e.target.value) || 0 })} /></F>
              <F label='Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.y ?? 0.5} onChange={(e) => update({ y: parseFloat(e.target.value) || 0 })} /></F>
            </div>
          </div>
        )}

        {step.type === 'swipe_ratio' && (
          <div className='space-y-2'>
            {onRequestPickSwipeCoords && (
              <Button
                size='sm'
                variant='outline'
                className='h-7 w-full gap-1.5 text-[10px] text-sky-800 border-sky-400/50 hover:bg-sky-50 dark:text-sky-300 dark:hover:bg-sky-950/30'
                onClick={onRequestPickSwipeCoords}
              >
                <Move size={12} />
                Vuốt trên mirror để lấy đoạn (đầu → cuối)
              </Button>
            )}
            <div className='grid grid-cols-2 gap-2'>
            <F label='Từ X'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.x1 ?? 0.5} onChange={(e) => update({ x1: parseFloat(e.target.value) })} /></F>
            <F label='Từ Y'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.y1 ?? 0.8} onChange={(e) => update({ y1: parseFloat(e.target.value) })} /></F>
            <F label='Tới X'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.x2 ?? 0.5} onChange={(e) => update({ x2: parseFloat(e.target.value) })} /></F>
            <F label='Tới Y'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.y2 ?? 0.2} onChange={(e) => update({ y2: parseFloat(e.target.value) })} /></F>
            </div>
            <F label='Thời gian vuốt (ms)'>
              <Input type='number' min={50} className='h-8 w-28 text-xs' value={step.duration_ms ?? 300} onChange={(e) => update({ duration_ms: Number(e.target.value) || 300 })} />
            </F>
          </div>
        )}

        {step.type === 'input_text' && (
          <>
            <F label='Nội dung nhập'>
              <div className='flex items-center gap-2'>
                <Input className='h-8 text-xs' value={step.text ?? ''} onChange={(e) => update({ text: e.target.value })} />
                <VariableInsertSelect
                  availableVariables={availableVariables}
                  t={t}
                  onInsert={(token) => update({ text: insertToken(step.text ?? '', token) })}
                />
              </div>
            </F>
            <F label='Cách nhập'>
              <select className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.via ?? 'u2'} onChange={(e) => update({ via: e.target.value })}>
                <option value='u2'>u2</option>
                <option value='a11y_key'>a11y_key</option>
              </select>
            </F>
          </>
        )}

        {step.type === 'input_selector' && (
          <>
            <SelectorFields
              step={step}
              onChange={onChange}
              onRequestPickSelector={onRequestPickSelector}
              availableVariables={availableVariables}
              t={t}
            />
            <F label='Nội dung nhập'>
              <div className='flex items-center gap-2'>
                <Input className='h-8 text-xs' value={step.text ?? ''} onChange={(e) => update({ text: e.target.value })} />
                <VariableInsertSelect
                  availableVariables={availableVariables}
                  t={t}
                  onInsert={(token) => update({ text: insertToken(step.text ?? '', token) })}
                />
              </div>
            </F>
            <label className='flex cursor-pointer items-center gap-2'>
              <input type='checkbox' className='size-3.5 rounded' checked={step.clear_first ?? true} onChange={(e) => update({ clear_first: e.target.checked })} />
              <span className='text-[11px]'>Xoá nội dung cũ trước khi nhập</span>
            </label>
          </>
        )}

        {step.type === 'key' && (
          <F label='Phím'>
            <select className='w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.key ?? 'enter'} onChange={(e) => update({ key: e.target.value })}>
              <option value='enter'>Enter</option><option value='back'>Back</option><option value='home'>Home</option><option value='recent'>Recent Apps</option>
            </select>
          </F>
        )}

        {step.type === 'scroll_down' && (
          <div className='space-y-2'>
            <div className='grid grid-cols-2 gap-2'>
              <F label={t('scrollDown.repeatsLabel')}>
                <Input type='number' min={1} className='h-8 w-full text-xs' value={step.repeats ?? 1} onChange={(e) => update({ repeats: Number(e.target.value) })} />
              </F>
              <F label={t('scrollDown.startXRatioLabel')}>
                <Input
                  className='h-8 w-full text-xs font-mono'
                  placeholder={t('scrollDown.startXRatioPlaceholder')}
                  value={step.start_x_ratio != null ? String(step.start_x_ratio) : ''}
                  onChange={(e) => {
                    const v = e.target.value.trim();
                    if (v === '') {
                      const { start_x_ratio: _sx, ...rest } = step as FlowStep & { start_x_ratio?: unknown };
                      onChange(rest as FlowStep);
                      return;
                    }
                    if (/^\$\{[^}]+\}$/.test(v)) {
                      update({ start_x_ratio: v } as Partial<FlowStep>);
                      return;
                    }
                    const n = Number(v);
                    update({ start_x_ratio: (Number.isFinite(n) ? n : v) as number | string } as Partial<FlowStep>);
                  }}
                />
              </F>
            </div>
            <div className='grid grid-cols-2 gap-2'>
              <F label={t('scrollDown.startYRatioLabel')}>
                <Input type='number' min={0} max={1} step={0.01} className='h-8 w-full text-xs' value={step.start_y_ratio ?? 0.65} onChange={(e) => update({ start_y_ratio: Number(e.target.value) || 0 })} />
              </F>
              <F label={t('scrollDown.endYRatioLabel')}>
                <Input type='number' min={0} max={1} step={0.01} className='h-8 w-full text-xs' value={step.end_y_ratio ?? 0.47} onChange={(e) => update({ end_y_ratio: Number(e.target.value) || 0 })} />
              </F>
              <F label={t('scrollDown.durationMsLabel')}>
                <Input type='number' min={50} className='h-8 w-full text-xs' value={step.duration_ms ?? 520} onChange={(e) => update({ duration_ms: Number(e.target.value) || 0 })} />
              </F>
              <F label={t('scrollDown.pauseSecondsLabel')}>
                <Input type='number' min={0} step={0.1} className='h-8 w-full text-xs' value={step.pause_seconds ?? 0.6} onChange={(e) => update({ pause_seconds: Number(e.target.value) || 0 })} />
              </F>
            </div>
          </div>
        )}

        {step.type === 'wait_stable' && (
          <div className='grid grid-cols-2 gap-2'>
            <F label='Timeout (giây)'><Input type='number' min={1} step={0.5} className='h-8 text-xs' value={step.timeout ?? 5} onChange={(e) => update({ timeout: Number(e.target.value) || 5 })} /></F>
            <F label='Ổn định trong (giây)'><Input type='number' min={0.1} step={0.1} className='h-8 text-xs' value={step.stable_duration ?? 0.4} onChange={(e) => update({ stable_duration: Number(e.target.value) || 0.4 })} /></F>
          </div>
        )}

        {step.type === 'verify_screen' && (
          <>
            <F label='screenshot (base64 hoặc URL/path)'>
              <textarea className='min-h-[92px] w-full rounded border bg-background px-2 py-1.5 text-xs font-mono' value={step.screenshot ?? ''} onChange={(e) => update({ screenshot: e.target.value })} />
            </F>
            <div className='grid grid-cols-3 gap-2'>
              <F label='ssim_threshold'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ssim_threshold ?? 0.75} onChange={(e) => update({ ssim_threshold: Number(e.target.value) || 0.75 })} /></F>
              <F label='timeout'><Input type='number' min={0.1} step={0.1} className='h-8 text-xs' value={step.timeout ?? 8} onChange={(e) => update({ timeout: Math.max(0.1, Number(e.target.value) || 0.1) })} /></F>
              <F label='poll'><Input type='number' min={0.1} step={0.1} className='h-8 text-xs' value={step.poll ?? 0.5} onChange={(e) => update({ poll: Math.max(0.1, Number(e.target.value) || 0.1) })} /></F>
            </div>
          </>
        )}

        {step.type === 'dismiss_popup' && (
          <F label='Số lần thử (retries)'><Input type='number' min={1} max={10} className='h-8 w-24 text-xs' value={step.retries ?? 3} onChange={(e) => update({ retries: Number(e.target.value) || 3 })} /></F>
        )}

        {step.type === 'tap_fb_comment_button' && (
          <>
            {/* ── Mô tả ── */}
            <div className='rounded-md border border-blue-400/40 bg-blue-50/60 px-3 py-2.5 text-[11px] leading-relaxed text-blue-950 dark:border-blue-500/30 dark:bg-blue-950/30 dark:text-blue-100'>
              <div className='mb-1 font-semibold'>Bấm nút "Bình luận" (Facebook)</div>
              <div className='space-y-0.5'>
                <div>① <b>Tìm</b> bài đầu tiên có nút Bình luận đang hiện trên màn hình</div>
                <div>② <b>Ghi nhớ bài đó</b> — comment thu thập sau sẽ gắn đúng bài này</div>
                <div>③ <b>Bấm nút</b> → sheet bình luận mở</div>
                <div>④ <b>Chọn bộ lọc</b> trong sheet 3 option (tùy chọn)</div>
                <div>⑤ Chạy nhánh <b>Khi bấm được</b> hoặc <b>Không thấy nút</b></div>
              </div>
              <div className='mt-2 rounded bg-amber-50 px-2 py-1.5 text-[10px] text-amber-900 dark:bg-amber-950/40 dark:text-amber-200'>
                <b>Bước này không tự thu thập comment.</b> Để lấy comment, đặt bước
                <code className='mx-1 rounded bg-amber-100 px-1 dark:bg-amber-900/50'>extract fb_comments</code>
                vào nhánh <b>Khi bấm được</b> — lúc đó comment sẽ tự động gắn đúng bài vừa bấm.
              </div>
            </div>

            {/* ── Phase 1: Tìm nút ── */}
            <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>① Tìm nút Bình luận</div>
            <div className='rounded border border-border/50 bg-muted/30 px-2.5 py-2 text-[11px] text-muted-foreground'>
              Tìm node <code className='rounded bg-muted px-1'>Button</code> có text / content-desc là <code className='rounded bg-muted px-1'>"Bình luận"</code> hoặc <code className='rounded bg-muted px-1'>"Comment"</code>.
              Nếu không thấy Button, tự động fallback sang node <code className='rounded bg-muted px-1'>clickable=true</code> cùng text.
              Không tìm thấy → chạy nhánh <b>Không thấy nút</b>.
            </div>

            <label className='flex items-start gap-2 text-xs text-foreground'>
              <input
                type='checkbox' className='mt-0.5 h-3.5 w-3.5'
                checked={!!step.pre_scroll}
                onChange={(e) => update({ pre_scroll: e.target.checked })}
              />
              <span>
                <b>Cuộn nhẹ trước khi tìm</b> — hé lộ hàng Thích / Bình luận khi bài viết dài
                (thay cho bước scroll_down riêng trước bước này).
              </span>
            </label>

            {step.pre_scroll && (
              <F label='Khoảng cách cuộn (0–1, tỉ lệ màn hình)'>
                <Input
                  type='number' min={0.05} max={0.6} step={0.01} className='h-8 w-28 text-xs'
                  value={step.pre_scroll_distance ?? 0.24}
                  onChange={(e) => update({ pre_scroll_distance: Math.min(0.6, Math.max(0.05, Number(e.target.value) || 0.24)) })}
                />
              </F>
            )}

            <div className='grid grid-cols-2 gap-2'>
              <F label='Chờ nút tối đa (giây)'>
                <Input
                  type='number' min={0.5} step={0.5} className='h-8 text-xs'
                  value={step.timeout ?? 6}
                  onChange={(e) => update({ timeout: Math.max(0.5, Number(e.target.value) || 6) })}
                />
              </F>
              <F label='Tần suất kiểm tra (giây)'>
                <Input
                  type='number' min={0.1} step={0.1} className='h-8 text-xs'
                  value={step.poll ?? 0.4}
                  onChange={(e) => update({ poll: Math.max(0.1, Number(e.target.value) || 0.4) })}
                />
              </F>
            </div>

            {/* ── Phase 2: Sau khi tap ── */}
            <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>② Sau khi bấm</div>
            <F label='Chờ sheet bình luận mở (giây)'>
              <Input
                type='number' min={0} step={0.1} className='h-8 w-28 text-xs'
                value={step.post_tap_wait_s ?? 0.8}
                onChange={(e) => update({ post_tap_wait_s: Math.max(0, Number(e.target.value) || 0.8) })}
              />
            </F>

            {/* ── Phase 3: Bộ lọc ── */}
            <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>③ Bộ lọc bình luận</div>
            <F label='Sắp xếp bình luận sau khi mở sheet'>
              <select
                className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
                value={
                  step.comment_filter
                  ?? (step.switch_to_all_comments === false ? 'none' : 'all_comments')
                }
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === 'none') {
                    update({ comment_filter: 'none', switch_to_all_comments: false });
                  } else {
                    update({ comment_filter: v, switch_to_all_comments: true });
                  }
                }}
              >
                <option value='none'>Không đổi — giữ mặc định Facebook</option>
                <option value='most_relevant'>Phù hợp nhất</option>
                <option value='newest'>Mới nhất</option>
                <option value='all_comments'>Tất cả bình luận</option>
              </select>
            </F>
            <p className='text-[10px] leading-relaxed text-muted-foreground'>
              Mở sheet bằng hàng &quot;Nhấn để thay đổi bộ lọc&quot;, rồi tap đúng một trong ba dòng tiêu đề
              (không tap dòng mô tả spam bên dưới).
            </p>

            {/* ── Phase 4: Nhận diện bài ── */}
            <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>④ Nhận diện bài viết</div>
            <F label='Trường hash bài (giữ mặc định nếu không rõ)'>
              <Input
                className='h-8 text-xs font-mono'
                value={step.dedupe_field ?? 'post_key'}
                onChange={(e) => update({ dedupe_field: e.target.value || 'post_key' })}
                placeholder='post_key'
              />
            </F>

            {/* ── Khi lỗi ── */}
            <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>⑤ Khi không tìm thấy nút</div>
            <label className='flex items-start gap-2 text-xs text-foreground'>
              <input
                type='checkbox' className='mt-0.5 h-3.5 w-3.5'
                checked={step.ignore_error !== false}
                onChange={(e) => update({ ignore_error: e.target.checked })}
              />
              <span>
                <b>Bỏ qua khi không thấy nút</b> (khuyến nghị bật) — không có nút Bình luận
                không bị tính là lỗi, kịch bản tiếp tục bình thường. Bỏ tick để kịch bản
                dừng và báo lỗi khi không tìm thấy nút.
              </span>
            </label>
          </>
        )}

        {step.type === 'tap_position' && (
          <F label='Vị trí'>
            <select className='w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.pos ?? 'middle_center'} onChange={(e) => update({ pos: e.target.value })}>
              <option value='top_left'>Góc trên trái</option>
              <option value='top_center'>Giữa trên</option>
              <option value='search_bar'>Thanh tìm kiếm</option>
              <option value='top_right'>Góc trên phải</option>
              <option value='middle_left'>Giữa trái</option>
              <option value='middle_center'>Chính giữa</option>
              <option value='middle_right'>Giữa phải</option>
              <option value='bottom_left'>Góc dưới trái</option>
              <option value='bottom_center'>Giữa dưới</option>
              <option value='bottom_right'>Góc dưới phải</option>
            </select>
          </F>
        )}

        {step.type === 'loop' && (
          <>
            <F label='Số vòng lặp (hỗ trợ biến)'>
              <Input className='h-8 text-xs font-mono' placeholder='10 hoặc ${MAX_SCROLLS}' value={step.count ?? '10'}
                onChange={(e) => update({ count: e.target.value })} />
            </F>
            <F label='max_iterations'>
              <Input type='number' min={1} className='h-8 w-28 text-xs' value={step.max_iterations ?? 100}
                onChange={(e) => update({ max_iterations: Number(e.target.value) || 100 })} />
            </F>
            <JsonTextarea label='while condition (JSON, optional)' value={step.while} onCommit={(next) => update({ while: next })} />
          </>
        )}

        {step.type === 'repeat' && (<><F label='Số lần lặp'><Input type='number' min={1} className='h-8 w-24 text-xs' value={step.count ?? 3} onChange={(e) => update({ count: Number(e.target.value) })} /></F><F label='Delay giữa các lần (giây)'><Input type='number' min={0} step={0.5} className='h-8 w-24 text-xs' value={step.delay_between ?? 0} onChange={(e) => update({ delay_between: Number(e.target.value) })} /></F></>)}

        {step.type === 'repeat_until' && <F label='Tối đa lặp'><Input type='number' min={1} className='h-8 w-24 text-xs' value={step.max_iterations ?? 50} onChange={(e) => update({ max_iterations: Number(e.target.value) })} /></F>}

        {step.type === 'if_element' && (
          <>
            <SelectorFields
              step={step}
              onChange={onChange}
              onRequestPickSelector={onRequestPickSelector}
              availableVariables={availableVariables}
              t={t}
            />
            <F label='Timeout (giây)'>
              <Input type='number' min={0.1} step={0.1} className='h-8 w-24 text-xs' value={step.timeout ?? 3} onChange={(e) => update({ timeout: Math.max(0.1, Number(e.target.value) || 0.1) })} />
            </F>
          </>
        )}

        {step.type === 'if' && (
          <>
            <p className='rounded bg-muted/60 px-2 py-1.5 text-[11px] text-muted-foreground'>
              Điều kiện tổng quát theo backend (`condition`) — hỗ trợ element_exists / element_not_exists / variable_equals...
            </p>
            <JsonTextarea label='Condition JSON' value={step.condition ?? { element_exists: { by: 'text', value: '' } }} onCommit={(next) => update({ condition: next ?? {} })} />
          </>
        )}

        {step.type === 'break_if' && (
          <>
            <p className='rounded bg-muted/60 px-2 py-1.5 text-[11px] text-muted-foreground'>
              Nếu condition đúng thì break vòng lặp hiện tại.
            </p>
            <JsonTextarea label='Condition JSON' value={step.condition ?? { element_exists: { by: 'text', value: '' } }} onCommit={(next) => update({ condition: next ?? {} })} />
          </>
        )}

        {step.type === 'if_variable' && (
          <>
            <F label='Tên biến'><Input className='h-8 text-xs font-mono' value={step.name ?? ''} onChange={(e) => update({ name: e.target.value })} /></F>
            <F label='Điều kiện'>
              <select className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                value={step.equals != null ? 'equals' : step.not_equals != null ? 'not_equals' : step.contains != null ? 'contains' : 'greater_than'}
                onChange={(e) => {
                  const val = step.equals ?? step.not_equals ?? step.contains ?? step.greater_than ?? '';
                  const c: any = { ...step }; delete c.equals; delete c.not_equals; delete c.contains; delete c.greater_than;
                  onChange({ ...c, [e.target.value]: val });
                }}>
                <option value='equals'>Bằng (==)</option><option value='not_equals'>Khác (!=)</option><option value='contains'>Chứa</option><option value='greater_than'>Lớn hơn (&gt;)</option>
              </select>
            </F>
            <F label='Giá trị'>
              <div className={valueInsertRowClassName()}>
                <Input className='h-9 min-w-0 flex-1 text-xs' value={step.equals ?? step.not_equals ?? step.contains ?? step.greater_than ?? ''} onChange={(e) => { const op = step.equals != null ? 'equals' : step.not_equals != null ? 'not_equals' : step.contains != null ? 'contains' : 'greater_than'; update({ [op]: e.target.value }); }} />
                <VariableInsertSelect
                  availableVariables={availableVariables}
                  t={t}
                  onInsert={(token) => {
                    const op = step.equals != null ? 'equals' : step.not_equals != null ? 'not_equals' : step.contains != null ? 'contains' : 'greater_than';
                    const current = step.equals ?? step.not_equals ?? step.contains ?? step.greater_than ?? '';
                    update({ [op]: insertToken(String(current), token) } as Partial<FlowStep>);
                  }}
                />
              </div>
            </F>
          </>
        )}

        {step.type === 'set_variable' && (
          <>
            <F label={t('setVariable.varNameLabel')}>
              <Input
                className='h-9 font-mono text-sm'
                value={step.name ?? ''}
                onChange={(e) => update({ name: e.target.value })}
                placeholder={t('setVariable.varNamePlaceholder')}
              />
            </F>
            <F label={t('setVariable.valueLabel')}>
              <div className={valueInsertRowClassName()}>
                <Input
                  className='h-9 min-w-0 flex-1 font-mono text-sm'
                  value={step.value ?? ''}
                  onChange={(e) => update({ value: e.target.value })}
                  placeholder={t('setVariable.valuePlaceholder')}
                />
                <VariableInsertSelect
                  availableVariables={availableVariables}
                  t={t}
                  onInsert={(token) => update({ value: insertToken(step.value ?? '', token) })}
                />
              </div>
            </F>
            <F label={t('setVariable.randomListLabel')}>
              <Input
                className='h-9 text-sm'
                value={(step.from_list ?? []).join(', ')}
                placeholder={t('setVariable.randomListPlaceholder')}
                onChange={(e) =>
                  update({
                    from_list: e.target.value
                      .split(',')
                      .map((s: string) => s.trim())
                      .filter(Boolean),
                  })}
              />
            </F>
            <div className='rounded-md border border-dashed border-border/70 bg-muted/25 px-2.5 py-2'>
              <p className='mb-1.5 text-[11px] font-medium text-muted-foreground'>{t('setVariable.builtinHint')}</p>
              <div className='flex flex-wrap gap-1'>
                {BUILTIN_VARIABLE_TOKENS.map((token) => (
                  <code
                    key={token}
                    className='rounded bg-background/80 px-1.5 py-0.5 font-mono text-[10px] text-foreground shadow-sm ring-1 ring-border/60'
                  >
                    {token}
                  </code>
                ))}
              </div>
            </div>
          </>
        )}

        {step.type === 'set_var' && (
          <>
            <F label='Key'>
              <Input className='h-8 text-xs font-mono' value={step.key ?? ''} onChange={(e) => update({ key: e.target.value })} placeholder='my_key' />
            </F>
            <F label='Value (JSON hoặc text)'>
              <Input
                className='h-8 text-xs font-mono'
                value={typeof step.value === 'string' ? step.value : JSON.stringify(step.value ?? '')}
                onChange={(e) => {
                  const raw = e.target.value;
                  try {
                    update({ value: JSON.parse(raw) });
                  } catch {
                    update({ value: raw });
                  }
                }}
              />
            </F>
          </>
        )}

        {step.type === 'double_tap' && (
          <>
            <F label='Hệ tọa độ'>
              <select
                className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                value={doubleTapCoordMode}
                onChange={(e) => {
                  const mode = e.target.value;
                  if (mode === 'ratio') update({ rx: step.rx ?? 0.5, ry: step.ry ?? 0.5, x: undefined, y: undefined });
                  else update({ x: step.x ?? 500, y: step.y ?? 900, rx: undefined, ry: undefined });
                }}
              >
                <option value='ratio'>Ratio (0-1)</option>
                <option value='absolute'>Absolute px</option>
              </select>
            </F>
            <div className='grid grid-cols-2 gap-2'>
              {doubleTapCoordMode === 'ratio' ? (
                <>
                  <F label='X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.rx ?? 0.5} onChange={(e) => update({ rx: parseFloat(e.target.value) || 0, x: undefined })} /></F>
                  <F label='Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ry ?? 0.5} onChange={(e) => update({ ry: parseFloat(e.target.value) || 0, y: undefined })} /></F>
                </>
              ) : (
                <>
                  <F label='X (px)'><Input type='number' min={0} step={1} className='h-8 text-xs' value={step.x ?? 500} onChange={(e) => update({ x: Number(e.target.value) || 0, rx: undefined })} /></F>
                  <F label='Y (px)'><Input type='number' min={0} step={1} className='h-8 text-xs' value={step.y ?? 900} onChange={(e) => update({ y: Number(e.target.value) || 0, ry: undefined })} /></F>
                </>
              )}
            </div>
            <F label='Wait sau double tap (giây)'>
              <Input type='number' min={0} step={0.1} className='h-8 w-28 text-xs' value={step.wait_after ?? 0.5} onChange={(e) => update({ wait_after: Number(e.target.value) || 0 })} />
            </F>
          </>
        )}

        {step.type === 'pinch' && (
          <>
            <F label='Tỉ lệ scale (2.0 = zoom in, 0.5 = zoom out)'>
              <Input type='number' min={0.1} max={5} step={0.1} className='h-8 text-xs' value={step.scale ?? 0.5} onChange={(e) => update({ scale: parseFloat(e.target.value) || 0.5 })} />
            </F>
            <F label='Hệ tọa độ tâm'>
              <select
                className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                value={pinchCoordMode}
                onChange={(e) => {
                  const mode = e.target.value;
                  if (mode === 'ratio') update({ rx: step.rx ?? 0.5, ry: step.ry ?? 0.5, cx: undefined, cy: undefined });
                  else update({ cx: step.cx ?? 500, cy: step.cy ?? 900, rx: undefined, ry: undefined });
                }}
              >
                <option value='ratio'>Ratio (0-1)</option>
                <option value='absolute'>Absolute px</option>
              </select>
            </F>
            <div className='grid grid-cols-2 gap-2'>
              {pinchCoordMode === 'ratio' ? (
                <>
                  <F label='Tâm X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.rx ?? 0.5} onChange={(e) => update({ rx: parseFloat(e.target.value) || 0.5, cx: undefined })} /></F>
                  <F label='Tâm Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ry ?? 0.5} onChange={(e) => update({ ry: parseFloat(e.target.value) || 0.5, cy: undefined })} /></F>
                </>
              ) : (
                <>
                  <F label='Tâm X (px)'><Input type='number' min={0} step={1} className='h-8 text-xs' value={step.cx ?? 500} onChange={(e) => update({ cx: Number(e.target.value) || 0, rx: undefined })} /></F>
                  <F label='Tâm Y (px)'><Input type='number' min={0} step={1} className='h-8 text-xs' value={step.cy ?? 900} onChange={(e) => update({ cy: Number(e.target.value) || 0, ry: undefined })} /></F>
                </>
              )}
            </div>
            <F label='Thời gian pinch (ms)'>
              <Input type='number' min={50} className='h-8 w-28 text-xs' value={step.duration_ms ?? 400} onChange={(e) => update({ duration_ms: Number(e.target.value) || 400 })} />
            </F>
          </>
        )}

        {step.type === 'drag' && (
          <>
            <F label='Hệ tọa độ'>
              <select
                className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                value={dragCoordMode}
                onChange={(e) => {
                  const mode = e.target.value;
                  if (mode === 'ratio') {
                    update({
                      rx1: step.rx1 ?? 0.5,
                      ry1: step.ry1 ?? 0.3,
                      rx2: step.rx2 ?? 0.5,
                      ry2: step.ry2 ?? 0.7,
                      x1: undefined,
                      y1: undefined,
                      x2: undefined,
                      y2: undefined,
                    });
                  } else {
                    update({
                      x1: step.x1 ?? 500,
                      y1: step.y1 ?? 700,
                      x2: step.x2 ?? 500,
                      y2: step.y2 ?? 1300,
                      rx1: undefined,
                      ry1: undefined,
                      rx2: undefined,
                      ry2: undefined,
                    });
                  }
                }}
              >
                <option value='ratio'>Ratio (0-1)</option>
                <option value='absolute'>Absolute px</option>
              </select>
            </F>
            <div className='grid grid-cols-2 gap-2'>
              {dragCoordMode === 'ratio' ? (
                <>
                  <F label='Từ X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.rx1 ?? 0.5} onChange={(e) => update({ rx1: parseFloat(e.target.value) || 0, x1: undefined })} /></F>
                  <F label='Từ Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ry1 ?? 0.3} onChange={(e) => update({ ry1: parseFloat(e.target.value) || 0, y1: undefined })} /></F>
                  <F label='Tới X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.rx2 ?? 0.5} onChange={(e) => update({ rx2: parseFloat(e.target.value) || 0, x2: undefined })} /></F>
                  <F label='Tới Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ry2 ?? 0.7} onChange={(e) => update({ ry2: parseFloat(e.target.value) || 0, y2: undefined })} /></F>
                </>
              ) : (
                <>
                  <F label='Từ X (px)'><Input type='number' min={0} step={1} className='h-8 text-xs' value={step.x1 ?? 500} onChange={(e) => update({ x1: Number(e.target.value) || 0, rx1: undefined })} /></F>
                  <F label='Từ Y (px)'><Input type='number' min={0} step={1} className='h-8 text-xs' value={step.y1 ?? 700} onChange={(e) => update({ y1: Number(e.target.value) || 0, ry1: undefined })} /></F>
                  <F label='Tới X (px)'><Input type='number' min={0} step={1} className='h-8 text-xs' value={step.x2 ?? 500} onChange={(e) => update({ x2: Number(e.target.value) || 0, rx2: undefined })} /></F>
                  <F label='Tới Y (px)'><Input type='number' min={0} step={1} className='h-8 text-xs' value={step.y2 ?? 1300} onChange={(e) => update({ y2: Number(e.target.value) || 0, ry2: undefined })} /></F>
                </>
              )}
            </div>
            <F label='Thời gian (ms)'><Input type='number' min={200} className='h-8 w-28 text-xs' value={step.duration_ms ?? 1000} onChange={(e) => update({ duration_ms: Number(e.target.value) })} /></F>
          </>
        )}

        {step.type === 'extract' && (
          <>
            <F label='Chiến lược'>
              <select className='w-full rounded border bg-background px-2 py-1.5 text-xs'
                value={step.strategy ?? 'fb_posts'}
                onChange={(e) => update({ strategy: e.target.value })}>
                <option value='fb_posts'>{t('extract.strategyFbPosts')}</option>
                <option value='fb_comments'>{t('extract.strategyFbComments')}</option>
                <option value='text_nodes'>{t('extract.strategyTextNodes')}</option>
              </select>
            </F>
            <div className='space-y-1.5 rounded-md border border-border/50 p-2.5'>
              <span className='text-[11px] font-semibold'>{t('extract.optionsTitle')}</span>
              <label className='flex cursor-pointer items-center gap-2'>
                <input type='checkbox' className='size-3.5 rounded' checked={step.expand_see_more ?? true}
                  onChange={(e) => update({ expand_see_more: e.target.checked })} />
                <span className='text-[11px]'>{t('extract.expandSeeMoreLabel')}</span>
              </label>
              <label className='flex cursor-pointer items-center gap-2'>
                <input type='checkbox' className='size-3.5 rounded' checked={step.stop_if_no_new ?? true}
                  onChange={(e) => update({ stop_if_no_new: e.target.checked })} />
                <span className='text-[11px]'>{t('extract.stopIfNoNewLabel')}</span>
              </label>
              {step.expand_see_more && (
                <div className='grid grid-cols-3 gap-2'>
                  <F label={t('extract.maxPassesLabel')}>
                    <Input className='h-8 text-xs font-mono' value={String(step.expand_see_more_max_passes ?? 2)}
                      onChange={(e) => update({ expand_see_more_max_passes: parseNumOrVar(e.target.value, 2) })} />
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.maxPassesHint')}</p>
                  </F>
                  <F label={t('extract.scrollBetweenLabel')}>
                    <select
                      className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={String(step.expand_see_more_scroll ?? false)}
                      onChange={(e) => update({ expand_see_more_scroll: e.target.value === 'true' })}
                    >
                      <option value='false'>{t('extract.booleanFalse')}</option>
                      <option value='true'>{t('extract.booleanTrue')}</option>
                    </select>
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.scrollBetweenHint')}</p>
                  </F>
                  <F label={t('extract.scrollDistanceLabel')}>
                    <Input className='h-8 text-xs font-mono' value={String(step.expand_see_more_scroll_distance ?? 0.3)}
                      onChange={(e) => update({ expand_see_more_scroll_distance: parseNumOrVar(e.target.value, 0.3) })} />
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.scrollDistanceHint')}</p>
                  </F>
                </div>
              )}
              {step.expand_see_more && (
                <div className='grid grid-cols-2 gap-2'>
                  <F label={t('extract.lazyHydrationRoundsLabel')}>
                    <Input className='h-8 text-xs font-mono' value={String(step.expand_lazy_hydration_rounds ?? 6)}
                      onChange={(e) => update({ expand_lazy_hydration_rounds: parseNumOrVar(e.target.value, 6) })} />
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.lazyHydrationRoundsHint')}</p>
                  </F>
                  <F label={t('extract.lazyHydrationScrollDistanceLabel')}>
                    <Input className='h-8 text-xs font-mono' value={String(step.expand_lazy_scroll_distance ?? 0.3)}
                      onChange={(e) => update({ expand_lazy_scroll_distance: parseNumOrVar(e.target.value, 0.3) })} />
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.lazyHydrationScrollDistanceHint')}</p>
                  </F>
                  <F label={t('extract.prefetchScrollPassesLabel')}>
                    <Input className='h-8 text-xs font-mono' value={String(step.expand_prefetch_scroll_passes ?? 0)}
                      onChange={(e) => update({ expand_prefetch_scroll_passes: parseNumOrVar(e.target.value, 0) })} />
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.prefetchScrollPassesHint')}</p>
                  </F>
                  <F label={t('extract.prefetchScrollPauseLabel')}>
                    <Input className='h-8 text-xs font-mono' value={String(step.expand_prefetch_scroll_pause ?? 0.7)}
                      onChange={(e) => update({ expand_prefetch_scroll_pause: parseNumOrVar(e.target.value, 0.7) })} />
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.prefetchScrollPauseHint')}</p>
                  </F>
                </div>
              )}
              {step.expand_see_more && (
                <F label={t('extract.completionRetriesLabel')}>
                  <Input className='h-8 w-28 text-xs font-mono' value={String(step.expand_completion_retries ?? 1)}
                    onChange={(e) => update({ expand_completion_retries: parseNumOrVar(e.target.value, 1) })} />
                  <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.completionRetriesHint')}</p>
                </F>
              )}
              {step.strategy === 'fb_comments' && (
                <>
                  <F label={t('extract.maxItemsLabel')}>
                    <Input className='h-8 w-28 text-xs font-mono' value={String(step.max_items ?? 50)}
                      onChange={(e) => update({ max_items: parseNumOrVar(e.target.value, 50) })} />
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.maxItemsHint')}</p>
                  </F>
                  <F label={t('extract.parentPostIdVarLabel')}>
                    <select
                      className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                      value={extractParentMode}
                      onChange={(e) => {
                        const mode = e.target.value;
                        if (mode === 'auto') {
                          update({ parent_post_id_var: undefined });
                        } else {
                          update({ parent_post_id_var: step.parent_post_id_var || '' });
                        }
                      }}
                    >
                      <option value='auto'>{t('extract.parentPostModeAuto')}</option>
                      <option value='custom'>{t('extract.parentPostModeCustom')}</option>
                    </select>
                    {extractParentMode === 'custom' && (
                      <Input className='mt-1 h-8 text-xs font-mono' placeholder='_active_comment_parent_hash'
                        value={step.parent_post_id_var ?? ''}
                        onChange={(e) => update({ parent_post_id_var: e.target.value || undefined })} />
                    )}
                    <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.parentPostIdVarHint')}</p>
                  </F>
                </>
              )}
              {step.stop_if_no_new && (
                <F label={t('extract.noNewThresholdLabel')}>
                  <Input type='number' min={1} className='h-8 w-24 text-xs' value={step.no_new_threshold ?? 30}
                    onChange={(e) => update({ no_new_threshold: Number(e.target.value) || 30 })} />
                  <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.noNewThresholdHint')}</p>
                </F>
              )}
              <F label={t('extract.resultVarLabel')}>
                <Input className='h-8 text-xs font-mono' placeholder='posts (mặc định)' value={step.result_var ?? ''}
                  onChange={(e) => update({ result_var: e.target.value || undefined })} />
                <p className='mt-1 text-[10px] text-muted-foreground'>{t('extract.resultVarHint')}</p>
              </F>
            </div>
            {/* ── Inline save config ── */}
            <div className='space-y-1.5 rounded-md border border-border/50 p-2.5'>
              <div className='flex items-center justify-between'>
                <span className='text-[11px] font-semibold'>{t('extract.saveTitle')}</span>
                <label className='flex cursor-pointer items-center gap-2'>
                  <input type='checkbox' className='size-3.5 rounded' checked={!!step.collection}
                    onChange={(e) => {
                      if (e.target.checked) {
                        update({
                          collection: '${SAVE_COLLECTION}',
                          platform: 'facebook',
                          content_type: step.strategy === 'fb_comments' ? 'comment' : 'group_post',
                          dedupe_field: step.strategy === 'fb_comments' ? 'comment_key' : 'text',
                        });
                      } else {
                        const { collection: _c, platform: _p, content_type: _ct, dedupe_field: _d, tags: _t, save_parent_id_var: _sp, item_level: _il, ...rest } = step;
                        onChange(rest as FlowStep);
                      }
                    }} />
                  <span className='text-[11px]'>{t('extract.saveEnableLabel')}</span>
                </label>
              </div>
              {step.collection && (
                <>
                  <F label={t('saveExtraction.collectionLabel')}>
                    <Input className='h-8 text-xs font-mono' placeholder='default hoặc ${SAVE_COLLECTION}' value={step.collection ?? ''}
                      onChange={(e) => update({ collection: e.target.value })} />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={t('saveExtraction.platformLabel')}>
                      <Input className='h-8 text-xs' placeholder='facebook' value={step.platform ?? ''}
                        onChange={(e) => update({ platform: e.target.value || undefined })} />
                    </F>
                    <F label={t('saveExtraction.contentTypeLabel')}>
                      <Input className='h-8 text-xs' placeholder='group_post' value={step.content_type ?? ''}
                        onChange={(e) => update({ content_type: e.target.value || undefined })} />
                    </F>
                  </div>
                  <F label={t('saveExtraction.dedupeFieldLabel')}>
                    <Input className='h-8 text-xs font-mono' placeholder='comment_key | post_key | text' value={step.dedupe_field ?? ''}
                      onChange={(e) => update({ dedupe_field: e.target.value || undefined })} />
                  </F>
                  <F label={t('saveExtraction.tagsLabel')}>
                    <Input className='h-8 text-xs' placeholder='group,crawl,${GROUP_NAME}' value={step.tags ?? ''}
                      onChange={(e) => update({ tags: e.target.value || undefined })} />
                  </F>
                  <div className='grid grid-cols-2 gap-2'>
                    <F label={t('saveExtraction.parentIdVarLabel')}>
                      <Input className='h-8 text-xs font-mono' placeholder='_active_comment_parent_hash'
                        value={step.save_parent_id_var ?? ''}
                        onChange={(e) => update({ save_parent_id_var: e.target.value || undefined })} />
                    </F>
                    <F label={t('saveExtraction.itemLevelLabel')}>
                      <select className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                        value={String(step.item_level ?? 0)}
                        onChange={(e) => update({ item_level: Number(e.target.value) || 0 })}>
                        <option value='0'>{t('saveExtraction.itemLevelPost')}</option>
                        <option value='1'>{t('saveExtraction.itemLevelComment')}</option>
                        <option value='2'>{t('saveExtraction.itemLevelReply')}</option>
                      </select>
                    </F>
                  </div>
                </>
              )}
            </div>
          </>
        )}

        {step.type === 'extract_text_hierarchy' && (
          <>
            <F label='save_as'><Input className='h-8 text-xs font-mono' value={step.save_as ?? 'texts'} onChange={(e) => update({ save_as: e.target.value || undefined })} /></F>
            <F label='format'>
              <select className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.format ?? 'text'} onChange={(e) => update({ format: e.target.value })}>
                <option value='text'>text</option>
                <option value='json'>json</option>
              </select>
            </F>
            <F label='filter_class'><Input className='h-8 text-xs font-mono' value={step.filter_class ?? ''} onChange={(e) => update({ filter_class: e.target.value || undefined })} /></F>
            <label className='flex cursor-pointer items-center gap-2'>
              <input type='checkbox' className='size-3.5 rounded' checked={step.exclude_empty ?? true} onChange={(e) => update({ exclude_empty: e.target.checked })} />
              <span className='text-[11px]'>exclude_empty</span>
            </label>
          </>
        )}

        {step.type === 'extract_text_ocr' && (
          <>
            <F label='save_as'><Input className='h-8 text-xs font-mono' value={step.save_as ?? 'ocr_text'} onChange={(e) => update({ save_as: e.target.value || undefined })} /></F>
            <div className='grid grid-cols-2 gap-2'>
              <F label='language'><Input className='h-8 text-xs font-mono' value={step.language ?? 'eng'} onChange={(e) => update({ language: e.target.value || 'eng' })} /></F>
              <F label='psm'><Input type='number' min={1} className='h-8 text-xs' value={step.psm ?? 11} onChange={(e) => update({ psm: Number(e.target.value) || 11 })} /></F>
              <F label='scale_factor'><Input type='number' min={0.1} step={0.1} className='h-8 text-xs' value={step.scale_factor ?? 2.0} onChange={(e) => update({ scale_factor: Number(e.target.value) || 2.0 })} /></F>
            </div>
            <JsonTextarea label='region (JSON)' value={step.region} onCommit={(next) => update({ region: next })} placeholder='{"x":0,"y":0,"w":100,"h":100}' />
            <label className='flex cursor-pointer items-center gap-2'>
              <input type='checkbox' className='size-3.5 rounded' checked={step.preprocess ?? true} onChange={(e) => update({ preprocess: e.target.checked })} />
              <span className='text-[11px]'>preprocess</span>
            </label>
          </>
        )}

        {step.type === 'extract_text_ai' && (
          <>
            <F label='save_as'><Input className='h-8 text-xs font-mono' value={step.save_as ?? 'ai_text'} onChange={(e) => update({ save_as: e.target.value || undefined })} /></F>
            <F label='prompt'><textarea className='min-h-[92px] w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.prompt ?? ''} onChange={(e) => update({ prompt: e.target.value })} /></F>
            <div className='grid grid-cols-2 gap-2'>
              <F label='provider'><Input className='h-8 text-xs font-mono' value={step.provider ?? 'openai'} onChange={(e) => update({ provider: e.target.value || 'openai' })} /></F>
              <F label='format'><Input className='h-8 text-xs font-mono' value={step.format ?? 'json'} onChange={(e) => update({ format: e.target.value || 'json' })} /></F>
              <F label='model'><Input className='h-8 text-xs font-mono' value={step.model ?? ''} onChange={(e) => update({ model: e.target.value || undefined })} /></F>
            </div>
            <JsonTextarea label='region (JSON)' value={step.region} onCommit={(next) => update({ region: next })} placeholder='{"x":0,"y":0,"w":100,"h":100}' />
          </>
        )}

        {step.type === 'extract_screen_data' && (
          <>
            <F label='save_as'><Input className='h-8 text-xs font-mono' value={step.save_as ?? 'screen_data'} onChange={(e) => update({ save_as: e.target.value || undefined })} /></F>
            <F label='strategy'>
              <select className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.strategy ?? 'auto'} onChange={(e) => update({ strategy: e.target.value })}>
                <option value='auto'>auto</option>
                <option value='ocr'>ocr</option>
                <option value='hierarchy'>hierarchy</option>
                <option value='ai'>ai</option>
              </select>
            </F>
            <JsonTextarea label='schema (JSON)' value={step.schema} onCommit={(next) => update({ schema: next })} />
          </>
        )}

        {step.type === 'save_extraction' && (
          <>
            <F label={t('saveExtraction.dataVarLabel')}>
              <Input className='h-8 text-xs font-mono' placeholder='comments | posts | text_nodes' value={step.data_var ?? ''}
                onChange={(e) => update({ data_var: e.target.value })} />
              <p className='mt-1 text-[10px] text-muted-foreground'>{t('saveExtraction.dataVarHint')}</p>
            </F>
            <F label={t('saveExtraction.collectionLabel')}>
              <Input className='h-8 text-xs font-mono' placeholder='default hoặc ${SAVE_COLLECTION}' value={step.collection ?? ''}
                onChange={(e) => update({ collection: e.target.value })} />
            </F>
            <div className='grid grid-cols-2 gap-2'>
              <F label={t('saveExtraction.platformLabel')}>
                <Input className='h-8 text-xs' placeholder='facebook' value={step.platform ?? ''}
                  onChange={(e) => update({ platform: e.target.value || undefined })} />
              </F>
              <F label={t('saveExtraction.contentTypeLabel')}>
                <Input className='h-8 text-xs' placeholder='group_post' value={step.content_type ?? ''}
                  onChange={(e) => update({ content_type: e.target.value || undefined })} />
              </F>
            </div>
            <F label={t('saveExtraction.dedupeFieldLabel')}>
              <Input className='h-8 text-xs font-mono' placeholder='comment_key | post_key | text' value={step.dedupe_field ?? ''}
                onChange={(e) => update({ dedupe_field: e.target.value || undefined })} />
              <p className='mt-1 text-[10px] text-muted-foreground'>{t('saveExtraction.dedupeFieldHint')}</p>
            </F>
            <F label={t('saveExtraction.tagsLabel')}>
              <Input className='h-8 text-xs' placeholder='group,crawl,${GROUP_NAME}' value={step.tags ?? ''}
                onChange={(e) => update({ tags: e.target.value || undefined })} />
              <p className='mt-1 text-[10px] text-muted-foreground'>{t('saveExtraction.tagsHint')}</p>
            </F>
            <div className='grid grid-cols-2 gap-2'>
              <F label={t('saveExtraction.parentIdVarLabel')}>
                <select
                  className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                  value={parentLinkMode}
                  onChange={(e) => {
                    const mode = e.target.value;
                    if (mode === 'auto') {
                      update({ parent_id_var: '_active_comment_parent_hash' });
                    } else if (mode === 'none') {
                      update({ parent_id_var: undefined });
                    } else {
                      update({ parent_id_var: step.parent_id_var || '' });
                    }
                  }}
                >
                  <option value='auto'>{t('saveExtraction.parentLinkModeAuto')}</option>
                  <option value='custom'>{t('saveExtraction.parentLinkModeCustom')}</option>
                  <option value='none'>{t('saveExtraction.parentLinkModeNone')}</option>
                </select>
                {parentLinkMode === 'custom' && (
                  <Input className='mt-1 h-8 text-xs font-mono' placeholder='_active_comment_parent_hash'
                    value={step.parent_id_var ?? ''}
                    onChange={(e) => update({ parent_id_var: e.target.value || undefined })} />
                )}
                <p className='mt-1 text-[10px] text-muted-foreground'>{t('saveExtraction.parentIdVarHint')}</p>
              </F>
              <F label={t('saveExtraction.itemLevelLabel')}>
                <select
                  className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
                  value={String(step.item_level ?? 0)}
                  onChange={(e) => update({ item_level: Number(e.target.value) || 0 })}
                >
                  <option value='0'>{t('saveExtraction.itemLevelPost')}</option>
                  <option value='1'>{t('saveExtraction.itemLevelComment')}</option>
                  <option value='2'>{t('saveExtraction.itemLevelReply')}</option>
                </select>
              </F>
            </div>
          </>
        )}

        {step.type === 'take_screenshot' && (
          <F label='Lưu vào đường dẫn (tuỳ chọn)'><Input className='h-8 text-xs font-mono' value={step.save_path ?? ''} onChange={(e) => update({ save_path: e.target.value || undefined })} placeholder='/sdcard/screen.jpg' /></F>
        )}

        {step.type === 'set_clipboard' && (
          <F label='Nội dung clipboard'><Input className='h-8 text-xs' value={step.text ?? ''} onChange={(e) => update({ text: e.target.value })} placeholder='Văn bản cần copy' /></F>
        )}

        {step.type === 'run_scenario' && (
          <div className='space-y-3'>
            <p className='rounded-md bg-muted/40 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground'>
              {t('runScenario.intro')}
            </p>
            <RunScenarioFields
              layout='panel'
              step={step}
              campaignScenarios={campaignScenarios}
              onPatch={(p) => {
                const merged = { ...step } as Record<string, unknown>;
                for (const [k, v] of Object.entries(p)) {
                  if (v === undefined) delete merged[k];
                  else merged[k] = v;
                }
                onChange(merged as FlowStep);
              }}
            />
          </div>
        )}

        {/* ─── Xử lý lỗi (chung cho mọi step) ─────────────────────────── */}
        <ErrorHandlingFields step={step} update={update} />
      </div>
    </div>
  );
}

/**
 * Shared error-handling section rendered at the bottom of every step's form.
 *
 * Backend priority (see temporal/workflows.py::resolve_error_policy):
 *   step.on_error → step.ignore_error → scenario.on_error → scenario.continue_on_error → "stop"
 */
function ErrorHandlingFields({
  step,
  update,
}: {
  step: FlowStep;
  update: (patch: Partial<FlowStep>) => void;
}) {
  const policy = step.on_error ?? '';
  const effective =
    policy === 'continue' ? 'Bỏ qua bước này, chạy tiếp' :
    policy === 'stop' ? 'Dừng kịch bản ngay' :
    policy === 'pause' ? 'Tạm dừng, chờ bạn xử lý' :
    step.ignore_error === true ? 'Bỏ qua bước này, chạy tiếp (do "Bỏ qua nếu lỗi")' :
    'Theo cài đặt của kịch bản (mặc định: Dừng)';

  return (
    <div className='mt-3 space-y-2.5 rounded-md border border-amber-400/40 bg-amber-50/50 px-3 py-2.5 dark:border-amber-500/30 dark:bg-amber-950/20'>
      <div className='flex items-start justify-between gap-2'>
        <div className='text-[11px] font-semibold text-amber-900 dark:text-amber-200'>
          Nếu bước này gặp lỗi thì làm gì?
        </div>
      </div>

      <p className='text-[10.5px] leading-relaxed text-amber-900/80 dark:text-amber-200/80'>
        "Lỗi" ở đây là khi máy không thực hiện được bước (mất kết nối, phần tử không
        tồn tại, timeout…). Tuỳ bước, bạn có thể cho phép <b>bỏ qua</b> để tiếp tục kịch bản, hoặc <b>dừng</b> luôn.
      </p>

      <label className='flex items-start gap-2 text-[11px] text-foreground'>
        <input
          type='checkbox'
          className='mt-0.5 h-3.5 w-3.5 shrink-0'
          checked={step.ignore_error === true}
          onChange={(e) => update({ ignore_error: e.target.checked || undefined })}
        />
        <span className='leading-relaxed'>
          <b>Bỏ qua nếu lỗi</b> — Bước này thất bại thì coi như xong, kịch bản chạy tiếp.
          Phù hợp cho bước không bắt buộc (VD: đóng popup, bấm nút tuỳ chọn).
        </span>
      </label>

      <F label='Cách xử lý khi lỗi (ưu tiên cao hơn "Bỏ qua nếu lỗi")'>
        <select
          className='h-8 w-full rounded border bg-background px-2 py-1.5 text-xs'
          value={policy}
          onChange={(e) => update({ on_error: e.target.value || undefined })}
        >
          <option value=''>— Theo cài đặt của kịch bản (thường là Dừng)</option>
          <option value='continue'>Bỏ qua bước này, chạy tiếp bước sau</option>
          <option value='stop'>Dừng kịch bản ngay</option>
          <option value='pause'>Tạm dừng, chờ bạn vào xử lý thủ công</option>
        </select>
      </F>

      <div className='rounded bg-amber-100/60 px-2 py-1.5 text-[10.5px] leading-relaxed text-amber-900 dark:bg-amber-900/30 dark:text-amber-100'>
        Kết quả áp dụng: <b>{effective}</b>.
      </div>
    </div>
  );
}
