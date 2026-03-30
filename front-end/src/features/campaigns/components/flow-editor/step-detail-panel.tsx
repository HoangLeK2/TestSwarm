'use client';

import { X } from 'lucide-react';
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
}

const SELECTOR_OPTIONS = ['text', 'resource-id', 'xpath', 'class name', 'description'] as const;

function F({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className='space-y-1'><Label className='text-[11px]'>{label}</Label>{children}</div>;
}

function SelectorFields({ step, onChange }: { step: FlowStep; onChange: (s: FlowStep) => void }) {
  return (
    <>
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

export function StepDetailPanel({ step, onChange, onClose }: Props) {
  const typeName = getStepTypeName(step.type);
  const update = (fields: Partial<FlowStep>) => onChange({ ...step, ...fields });

  return (
    <div className='flex h-full flex-col border-l bg-card'>
      <div className='flex items-center justify-between border-b px-3 py-2'>
        <div className='flex items-center gap-2'>
          <StepIcon type={step.type} size={18} />
          <span className='text-xs font-semibold'>{typeName}</span>
        </div>
        <Button size='icon' variant='ghost' className='size-6' onClick={onClose}><X size={12} /></Button>
      </div>

      <div className='flex-1 space-y-3 overflow-y-auto p-3'>
        {step.type === 'launch_app' && <F label='Tên package'><Input className='h-8 text-xs font-mono' value={step.package ?? ''} onChange={(e) => update({ package: e.target.value })} placeholder='com.android.chrome' /></F>}

        {step.type === 'open_url' && (<><F label='URL'><Input className='h-8 text-xs' value={step.url ?? ''} onChange={(e) => update({ url: e.target.value })} /></F><F label='Package trình duyệt'><Input className='h-8 text-xs font-mono' value={step.package ?? ''} onChange={(e) => update({ package: e.target.value || undefined })} /></F></>)}

        {step.type === 'wait' && <F label='Thời gian (giây)'><Input type='number' min={0} step={0.5} className='h-8 w-24 text-xs' value={step.seconds ?? 1} onChange={(e) => update({ seconds: Number(e.target.value) || 0 })} /></F>}

        {['tap_selector', 'wait_element', 'assert_element', 'scroll_to', 'long_tap_selector'].includes(step.type) && (
          <>
            <SelectorFields step={step} onChange={onChange} />
            {step.timeout != null && <F label='Timeout (giây)'><Input type='number' min={0} className='h-8 w-24 text-xs' value={step.timeout} onChange={(e) => update({ timeout: Number(e.target.value) })} /></F>}
            {step.type === 'long_tap_selector' && <F label='Thời gian giữ (ms)'><Input type='number' min={100} className='h-8 w-24 text-xs' value={step.duration_ms ?? 800} onChange={(e) => update({ duration_ms: Number(e.target.value) })} /></F>}
          </>
        )}

        {step.type === 'tap_ratio' && (
          <div className='grid grid-cols-2 gap-2'>
            <F label='X (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.x ?? 0.5} onChange={(e) => update({ x: parseFloat(e.target.value) || 0 })} /></F>
            <F label='Y (0-1)'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.y ?? 0.5} onChange={(e) => update({ y: parseFloat(e.target.value) || 0 })} /></F>
          </div>
        )}

        {step.type === 'swipe_ratio' && (
          <div className='grid grid-cols-2 gap-2'>
            <F label='Từ X'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.x1 ?? 0.5} onChange={(e) => update({ x1: parseFloat(e.target.value) })} /></F>
            <F label='Từ Y'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.y1 ?? 0.8} onChange={(e) => update({ y1: parseFloat(e.target.value) })} /></F>
            <F label='Tới X'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.x2 ?? 0.5} onChange={(e) => update({ x2: parseFloat(e.target.value) })} /></F>
            <F label='Tới Y'><Input type='number' min={0} max={1} step={0.01} className='h-8 text-xs' value={step.y2 ?? 0.2} onChange={(e) => update({ y2: parseFloat(e.target.value) })} /></F>
          </div>
        )}

        {step.type === 'input_text' && <F label='Nội dung nhập'><Input className='h-8 text-xs' value={step.text ?? ''} onChange={(e) => update({ text: e.target.value })} /></F>}

        {step.type === 'input_selector' && (<><SelectorFields step={step} onChange={onChange} /><F label='Nội dung nhập'><Input className='h-8 text-xs' value={step.text ?? ''} onChange={(e) => update({ text: e.target.value })} /></F></>)}

        {step.type === 'key' && (
          <F label='Phím'>
            <select className='w-full rounded border bg-background px-2 py-1.5 text-xs' value={step.key ?? 'enter'} onChange={(e) => update({ key: e.target.value })}>
              <option value='enter'>Enter</option><option value='back'>Back</option><option value='home'>Home</option><option value='recent'>Recent Apps</option>
            </select>
          </F>
        )}

        {step.type === 'scroll_down' && <F label='Số lần cuộn'><Input type='number' min={1} className='h-8 w-24 text-xs' value={step.repeats ?? 1} onChange={(e) => update({ repeats: Number(e.target.value) })} /></F>}

        {step.type === 'repeat' && (<><F label='Số lần lặp'><Input type='number' min={1} className='h-8 w-24 text-xs' value={step.count ?? 3} onChange={(e) => update({ count: Number(e.target.value) })} /></F><F label='Delay giữa các lần (giây)'><Input type='number' min={0} step={0.5} className='h-8 w-24 text-xs' value={step.delay_between ?? 0} onChange={(e) => update({ delay_between: Number(e.target.value) })} /></F></>)}

        {step.type === 'repeat_until' && <F label='Tối đa lặp'><Input type='number' min={1} className='h-8 w-24 text-xs' value={step.max_iterations ?? 50} onChange={(e) => update({ max_iterations: Number(e.target.value) })} /></F>}

        {step.type === 'if_element' && (<><SelectorFields step={step} onChange={onChange} /><F label='Timeout (giây)'><Input type='number' min={0} className='h-8 w-24 text-xs' value={step.timeout ?? 3} onChange={(e) => update({ timeout: Number(e.target.value) })} /></F></>)}

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

        {step.type === 'run_scenario' && (
          <>
            <F label='Tên kịch bản'><Input className='h-8 text-xs font-mono' value={step.scenario_name ?? ''} onChange={(e) => update({ scenario_name: e.target.value, scenario_id: undefined })} placeholder='login_facebook' /></F>
            <F label='Hoặc ID kịch bản'><Input className='h-8 text-xs font-mono' value={step.scenario_id ?? ''} onChange={(e) => update({ scenario_id: e.target.value, scenario_name: undefined })} /></F>
            <F label='Ghi đè biến'><VariableEditor variables={step.variables ?? {}} onChange={(vars) => update({ variables: vars })} /></F>
          </>
        )}
      </div>
    </div>
  );
}
