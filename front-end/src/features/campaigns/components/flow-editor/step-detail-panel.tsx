'use client';

import { Crosshair, MousePointerClick, Move } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { VariableEditor } from '@/components/variable-editor';
import type { FlowStep } from '../scenario-steps/types';
import { getStepTypeName } from './constants';
import { StepIcon } from './step-icon';
interface Props {
  step: FlowStep;
  onChange: (step: FlowStep) => void;
  onClose: () => void;
  /** Called when user wants to pick a selector from the device screen/tree. Should close the panel first. */
  onRequestPickSelector?: () => void;
  /** Pick single tap ratios on mirror (tap_ratio / tap fallback). */
  onRequestPickTapCoords?: () => void;
  /** Pick swipe segment on mirror (swipe_ratio). */
  onRequestPickSwipeCoords?: () => void;
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
  return <div className='space-y-1'><Label className='text-[11px]'>{label}</Label>{children}</div>;
}

function SelectorFields({ step, onChange, onRequestPickSelector }: {
  step: FlowStep;
  onChange: (s: FlowStep) => void;
  onRequestPickSelector?: () => void;
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
        <Input className='h-8 text-xs' value={step.value ?? ''} onChange={(e) => onChange({ ...step, value: e.target.value })} placeholder='VD: Đăng nhập hoặc com.app:id/btn' />
      </F>
    </>
  );
}

export function StepDetailPanel({
  step,
  onChange,
  onClose: _onClose,
  onRequestPickSelector,
  onRequestPickTapCoords,
  onRequestPickSwipeCoords,
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

  return (
    <div className='flex flex-col bg-card'>
      <div className='flex items-center gap-2 border-b px-3 py-2'>
        <StepIcon type={step.type} size={16} />
        <span className='text-xs font-semibold'>{typeName}</span>
      </div>

      <div className='max-h-[70vh] space-y-3 overflow-y-auto p-3'>
        {/* Title & description — user-defined labels for any step */}
        <F label='Tiêu đề (tuỳ chọn)'>
          <Input className='h-8 text-xs' placeholder='VD: Đăng nhập, Mở trang chủ…'
            value={(step as any).title ?? ''}
            onChange={(e) => update({ title: e.target.value || undefined } as any)} />
        </F>
        <F label='Mô tả (tuỳ chọn)'>
          <Input className='h-8 text-xs' placeholder='Ghi chú thêm cho bước này'
            value={(step as any).description ?? ''}
            onChange={(e) => update({ description: e.target.value || undefined } as any)} />
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
          </>
        )}

        {step.type === 'launch_app' && <F label='Tên package'><Input className='h-8 text-xs font-mono' value={step.package ?? ''} onChange={(e) => update({ package: e.target.value })} placeholder='com.android.chrome' /></F>}

        {step.type === 'open_url' && (<><F label='URL'><Input className='h-8 text-xs' value={step.url ?? ''} onChange={(e) => update({ url: e.target.value })} /></F><F label='Package trình duyệt'><Input className='h-8 text-xs font-mono' value={step.package ?? ''} onChange={(e) => update({ package: e.target.value || undefined })} /></F></>)}

        {step.type === 'wait' && <F label='Thời gian (giây)'><Input type='number' min={0} step={0.5} className='h-8 w-24 text-xs' value={step.seconds ?? 1} onChange={(e) => update({ seconds: Number(e.target.value) || 0 })} /></F>}

        {['tap_selector', 'wait_element', 'assert_element', 'scroll_to', 'long_tap_selector'].includes(step.type) && (
          <>
            <SelectorFields step={step} onChange={onChange} onRequestPickSelector={onRequestPickSelector} />
            {step.timeout != null && <F label='Timeout (giây)'><Input type='number' min={0} className='h-8 w-24 text-xs' value={step.timeout} onChange={(e) => update({ timeout: Number(e.target.value) })} /></F>}
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
          </div>
        )}

        {step.type === 'input_text' && <F label='Nội dung nhập'><Input className='h-8 text-xs' value={step.text ?? ''} onChange={(e) => update({ text: e.target.value })} /></F>}

        {step.type === 'input_selector' && (<><SelectorFields step={step} onChange={onChange} onRequestPickSelector={onRequestPickSelector} /><F label='Nội dung nhập'><Input className='h-8 text-xs' value={step.text ?? ''} onChange={(e) => update({ text: e.target.value })} /></F></>)}

        {step.type === 'key' && (
          <F label='Phím'>
            <select className='w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.key ?? 'enter'} onChange={(e) => update({ key: e.target.value })}>
              <option value='enter'>Enter</option><option value='back'>Back</option><option value='home'>Home</option><option value='recent'>Recent Apps</option>
            </select>
          </F>
        )}

        {step.type === 'scroll_down' && (
          <div className='grid grid-cols-2 gap-2'>
            <F label='Số lần cuộn'>
              <Input type='number' min={1} className='h-8 w-full text-xs' value={step.repeats ?? 1} onChange={(e) => update({ repeats: Number(e.target.value) })} />
            </F>
            <F label='start_x_ratio (neo ngang)'>
              <Input
                className='h-8 w-full text-xs font-mono'
                placeholder='0.18 hoặc ${SCROLL_X_RATIO}'
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
        )}

        {step.type === 'wait_stable' && (
          <div className='grid grid-cols-2 gap-2'>
            <F label='Timeout (giây)'><Input type='number' min={1} step={0.5} className='h-8 text-xs' value={step.timeout ?? 5} onChange={(e) => update({ timeout: Number(e.target.value) || 5 })} /></F>
            <F label='Ổn định trong (giây)'><Input type='number' min={0.1} step={0.1} className='h-8 text-xs' value={step.stable_duration ?? 0.4} onChange={(e) => update({ stable_duration: Number(e.target.value) || 0.4 })} /></F>
          </div>
        )}

        {step.type === 'dismiss_popup' && (
          <F label='Số lần thử (retries)'><Input type='number' min={1} max={10} className='h-8 w-24 text-xs' value={step.retries ?? 3} onChange={(e) => update({ retries: Number(e.target.value) || 3 })} /></F>
        )}

        {step.type === 'tap_position' && (
          <F label='Vị trí'>
            <select className='w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.pos ?? 'middle_center'} onChange={(e) => update({ pos: e.target.value })}>
              <option value='top_left'>Góc trên trái</option>
              <option value='top_center'>Giữa trên</option>
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
          <F label='Số vòng lặp (hỗ trợ biến)'>
            <Input className='h-8 text-xs font-mono' placeholder='10 hoặc ${MAX_SCROLLS}' value={step.count ?? '10'}
              onChange={(e) => update({ count: e.target.value })} />
          </F>
        )}

        {step.type === 'repeat' && (<><F label='Số lần lặp'><Input type='number' min={1} className='h-8 w-24 text-xs' value={step.count ?? 3} onChange={(e) => update({ count: Number(e.target.value) })} /></F><F label='Delay giữa các lần (giây)'><Input type='number' min={0} step={0.5} className='h-8 w-24 text-xs' value={step.delay_between ?? 0} onChange={(e) => update({ delay_between: Number(e.target.value) })} /></F></>)}

        {step.type === 'repeat_until' && <F label='Tối đa lặp'><Input type='number' min={1} className='h-8 w-24 text-xs' value={step.max_iterations ?? 50} onChange={(e) => update({ max_iterations: Number(e.target.value) })} /></F>}

        {step.type === 'if_element' && (<><SelectorFields step={step} onChange={onChange} onRequestPickSelector={onRequestPickSelector} /><F label='Timeout (giây)'><Input type='number' min={0} className='h-8 w-24 text-xs' value={step.timeout ?? 3} onChange={(e) => update({ timeout: Number(e.target.value) })} /></F></>)}

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
            <F label='Giá trị'><Input className='h-8 text-xs' value={step.equals ?? step.not_equals ?? step.contains ?? step.greater_than ?? ''} onChange={(e) => { const op = step.equals != null ? 'equals' : step.not_equals != null ? 'not_equals' : step.contains != null ? 'contains' : 'greater_than'; update({ [op]: e.target.value }); }} /></F>
          </>
        )}

        {step.type === 'set_variable' && (
          <>
            <F label='Tên biến'><Input className='h-8 text-xs font-mono' value={step.name ?? ''} onChange={(e) => update({ name: e.target.value })} placeholder='MY_VAR' /></F>
            <F label='Giá trị'><Input className='h-8 text-xs' value={step.value ?? ''} onChange={(e) => update({ value: e.target.value })} placeholder='giá trị hoặc ${__BUILTIN__}' /></F>
            <F label='Danh sách random (phẩy ngăn cách)'><Input className='h-8 text-xs' value={(step.from_list ?? []).join(', ')} onChange={(e) => update({ from_list: e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean) })} /></F>
            <p className='text-[9px] text-muted-foreground'>{'${__NOW__} ${__DATE__} ${__DEVICE_SERIAL__} ${__RANDOM_INT_1_100__}'}</p>
          </>
        )}

        {step.type === 'double_tap' && (
          <div className='grid grid-cols-2 gap-2'>
            <F label='X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.rx ?? step.x ?? 0.5} onChange={(e) => update({ rx: parseFloat(e.target.value) || 0, x: undefined })} /></F>
            <F label='Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ry ?? step.y ?? 0.5} onChange={(e) => update({ ry: parseFloat(e.target.value) || 0, y: undefined })} /></F>
          </div>
        )}

        {step.type === 'pinch' && (
          <>
            <F label='Tỉ lệ scale (2.0 = zoom in, 0.5 = zoom out)'>
              <Input type='number' min={0.1} max={5} step={0.1} className='h-8 text-xs' value={step.scale ?? 0.5} onChange={(e) => update({ scale: parseFloat(e.target.value) || 0.5 })} />
            </F>
            <div className='grid grid-cols-2 gap-2'>
              <F label='Tâm X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.rx ?? step.cx ?? 0.5} onChange={(e) => update({ rx: parseFloat(e.target.value) || 0.5, cx: undefined })} /></F>
              <F label='Tâm Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ry ?? step.cy ?? 0.5} onChange={(e) => update({ ry: parseFloat(e.target.value) || 0.5, cy: undefined })} /></F>
            </div>
          </>
        )}

        {step.type === 'drag' && (
          <>
            <div className='grid grid-cols-2 gap-2'>
              <F label='Từ X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.rx1 ?? 0.5} onChange={(e) => update({ rx1: parseFloat(e.target.value) || 0 })} /></F>
              <F label='Từ Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ry1 ?? 0.3} onChange={(e) => update({ ry1: parseFloat(e.target.value) || 0 })} /></F>
              <F label='Tới X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.rx2 ?? 0.5} onChange={(e) => update({ rx2: parseFloat(e.target.value) || 0 })} /></F>
              <F label='Tới Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.ry2 ?? 0.7} onChange={(e) => update({ ry2: parseFloat(e.target.value) || 0 })} /></F>
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
                </>
              )}
            </div>
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
          <>
            <F label='Tên kịch bản'><Input className='h-8 text-xs font-mono' value={step.scenario_name ?? ''} onChange={(e) => update({ scenario_name: e.target.value, scenario_id: undefined })} placeholder='login_facebook' /></F>
            <F label='Hoặc ID kịch bản'><Input className='h-8 text-xs font-mono' value={step.scenario_id ?? ''} onChange={(e) => update({ scenario_id: e.target.value, scenario_name: undefined })} /></F>
            <F label='Ghi đè biến'><VariableEditor variables={step.variables ?? {}} onChange={(vars) => update({ variables: vars } as any)} showBuiltins={false} /></F>
          </>
        )}
      </div>
    </div>
  );
}
