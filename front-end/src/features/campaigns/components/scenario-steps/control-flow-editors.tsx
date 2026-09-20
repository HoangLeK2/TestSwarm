'use client';

import { VariableInsertMenu } from '@/components/variable-insert-menu';
import type { FlowStep } from './types';

type FieldProps = {
  step: FlowStep;
  onChange: (field: string, value: any) => void;
  availableVariables?: string[];
};

const inputCls = 'border rounded px-1.5 py-0.5 bg-background text-[11px]';
const labelCls = 'shrink-0 text-[11px] text-muted-foreground';

const SELECTOR_OPTIONS = [
  'text',
  'resource-id',
  'xpath',
  'class name',
  'description',
  'descriptionContains',
  'descriptionStartsWith',
  'content-desc'
] as const;

function SelectorSelect({
  value,
  onChange
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <select
      className={`${inputCls} w-28`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {SELECTOR_OPTIONS.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

function insertToken(raw: string, token: string): string {
  const current = raw ?? '';
  if (!current.trim()) return token;
  const matches = current.match(/\$\{[^}]+\}/g);
  if (matches?.includes(token)) return current;
  return `${current} ${token}`.trim();
}

function VariableInsertSelect({
  availableVariables = [],
  onInsert,
  mode = 'token'
}: {
  availableVariables?: string[];
  onInsert: (value: string) => void;
  mode?: 'name' | 'token';
}) {
  if (availableVariables.length === 0) return null;
  return (
    <VariableInsertMenu
      groups={[
        {
          label: 'Biến có thể dùng',
          items: availableVariables.map((name) => ({
            value: mode === 'name' ? name : `\${${name}}`
          }))
        }
      ]}
      label='Chèn biến...'
      onInsert={onInsert}
      align='end'
      triggerClassName='h-7 w-32 min-w-0 px-1.5 text-[11px]'
    />
  );
}

/** repeat — count, delay_between */
export function RepeatFields({ step, onChange }: FieldProps) {
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <span className={labelCls}>count:</span>
      <input
        type='number'
        min={1}
        className={`${inputCls} w-16`}
        value={step.count ?? 3}
        onChange={(e) => onChange('count', Number(e.target.value) || 1)}
      />
      <span className={labelCls}>delay:</span>
      <input
        type='number'
        min={0}
        step={0.5}
        className={`${inputCls} w-16`}
        value={step.delay_between ?? 0}
        onChange={(e) => onChange('delay_between', Number(e.target.value) || 0)}
      />
      <span className={labelCls}>s</span>
    </div>
  );
}

/** repeat_until — condition, max_iterations */
export function RepeatUntilFields({
  step,
  onChange,
  availableVariables = []
}: FieldProps) {
  const condition = step.condition ?? {};
  const condType = condition.element_exists
    ? 'element_exists'
    : condition.element_not_exists
      ? 'element_not_exists'
      : condition.variable_equals
        ? 'variable_equals'
        : 'element_exists';
  const condData = condition[condType] ?? {};

  const updateCondition = (type: string, data: any) => {
    onChange('condition', { [type]: data });
  };

  return (
    <div className='space-y-1.5'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className={labelCls}>condition:</span>
        <select
          className={`${inputCls} w-36`}
          value={condType}
          onChange={(e) =>
            updateCondition(
              e.target.value,
              condType === 'variable_equals'
                ? { name: '', value: '' }
                : { by: 'text', value: '' }
            )
          }
        >
          <option value='element_exists'>element_exists</option>
          <option value='element_not_exists'>element_not_exists</option>
          <option value='variable_equals'>variable_equals</option>
        </select>
        <span className={labelCls}>max:</span>
        <input
          type='number'
          min={1}
          className={`${inputCls} w-16`}
          value={step.max_iterations ?? 50}
          onChange={(e) =>
            onChange('max_iterations', Number(e.target.value) || 50)
          }
        />
      </div>
      {condType !== 'variable_equals' ? (
        <div className='flex items-center gap-2'>
          <SelectorSelect
            value={condData.by ?? 'text'}
            onChange={(v) => updateCondition(condType, { ...condData, by: v })}
          />
          <input
            className={`${inputCls} flex-1`}
            placeholder='selector value'
            value={condData.value ?? ''}
            onChange={(e) =>
              updateCondition(condType, { ...condData, value: e.target.value })
            }
          />
          <VariableInsertSelect
            availableVariables={availableVariables}
            onInsert={(token) =>
              updateCondition(condType, {
                ...condData,
                value: insertToken(condData.value ?? '', token)
              })
            }
          />
        </div>
      ) : (
        <div className='flex items-center gap-2'>
          <input
            className={`${inputCls} w-28`}
            placeholder='variable name'
            value={condData.name ?? ''}
            onChange={(e) =>
              updateCondition('variable_equals', {
                ...condData,
                name: e.target.value
              })
            }
          />
          <VariableInsertSelect
            availableVariables={availableVariables}
            mode='name'
            onInsert={(name) =>
              updateCondition('variable_equals', {
                ...condData,
                name
              })
            }
          />
          <span className={labelCls}>=</span>
          <input
            className={`${inputCls} flex-1`}
            placeholder='expected value'
            value={condData.value ?? ''}
            onChange={(e) =>
              updateCondition('variable_equals', {
                ...condData,
                value: e.target.value
              })
            }
          />
          <VariableInsertSelect
            availableVariables={availableVariables}
            onInsert={(token) =>
              updateCondition('variable_equals', {
                ...condData,
                value: insertToken(condData.value ?? '', token)
              })
            }
          />
        </div>
      )}
    </div>
  );
}

/** if_element — by, value, timeout */
export function IfElementFields({
  step,
  onChange,
  availableVariables = []
}: FieldProps) {
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <span className={labelCls}>if</span>
      <SelectorSelect
        value={step.by ?? 'text'}
        onChange={(v) => onChange('by', v)}
      />
      <input
        className={`${inputCls} min-w-[120px] flex-1`}
        placeholder='element value'
        value={step.value ?? ''}
        onChange={(e) => onChange('value', e.target.value)}
      />
      <VariableInsertSelect
        availableVariables={availableVariables}
        onInsert={(token) =>
          onChange('value', insertToken(step.value ?? '', token))
        }
      />
      <span className={labelCls}>timeout:</span>
      <input
        type='number'
        min={0}
        step={0.5}
        className={`${inputCls} w-14`}
        value={step.timeout ?? 3}
        onChange={(e) => onChange('timeout', Number(e.target.value) || 3)}
      />
    </div>
  );
}

/** if_variable — name, condition operator, value */
export function IfVariableFields({
  step,
  onChange,
  availableVariables = []
}: FieldProps) {
  const op =
    step.equals != null
      ? 'equals'
      : step.not_equals != null
        ? 'not_equals'
        : step.contains != null
          ? 'contains'
          : step.greater_than != null
            ? 'greater_than'
            : 'equals';

  const opValue = step[op] ?? '';

  const handleOpChange = (newOp: string) => {
    const cleaned = { ...step };
    delete cleaned.equals;
    delete cleaned.not_equals;
    delete cleaned.contains;
    delete cleaned.greater_than;
    cleaned[newOp] = opValue;
    // Replace entire step
    Object.keys(cleaned).forEach((k) => {
      if (
        k !== 'type' &&
        k !== 'name' &&
        k !== 'then' &&
        k !== 'else' &&
        k !== newOp
      ) {
        onChange(k, undefined);
      }
    });
    onChange(newOp, opValue);
  };

  return (
    <div className='flex flex-wrap items-center gap-2'>
      <span className={labelCls}>if</span>
      <input
        className={`${inputCls} w-28 font-mono`}
        placeholder='VAR_NAME'
        value={step.name ?? ''}
        onChange={(e) => onChange('name', e.target.value)}
      />
      <VariableInsertSelect
        availableVariables={availableVariables}
        mode='name'
        onInsert={(name) => onChange('name', name)}
      />
      <select
        className={`${inputCls} w-28`}
        value={op}
        onChange={(e) => handleOpChange(e.target.value)}
      >
        <option value='equals'>==</option>
        <option value='not_equals'>!=</option>
        <option value='contains'>contains</option>
        <option value='greater_than'>&gt;</option>
      </select>
      <input
        className={`${inputCls} min-w-[80px] flex-1`}
        placeholder='value'
        value={opValue}
        onChange={(e) => onChange(op, e.target.value)}
      />
      <VariableInsertSelect
        availableVariables={availableVariables}
        onInsert={(token) => onChange(op, insertToken(opValue, token))}
      />
    </div>
  );
}

/**
 * "10–50" when the loop runs a random number of iterations, else null.
 *
 * count_min/count_max override count at run time, so every place that shows a
 * count has to say so — an editor reading "count: 10" next to a loop that
 * actually runs 10–50 times is worse than no number at all.
 */
function randomCountLabel(step: FlowStep): string | null {
  const min = step.count_min;
  const max = step.count_max;
  if (min == null || min === '' || max == null || max === '') return null;
  return `${min}–${max}`;
}

function detectLoopMode(step: FlowStep): 'count' | 'while' {
  const whileCond = step.while;
  const hasWhile =
    whileCond != null &&
    typeof whileCond === 'object' &&
    Object.keys(whileCond).length > 0;
  return hasWhile && step.count == null ? 'while' : 'count';
}

function ConditionBuilder({
  condition,
  onChange,
  condTypeLabels,
  availableVariables = []
}: {
  condition: Record<string, any>;
  onChange: (next: Record<string, any>) => void;
  condTypeLabels?: Record<string, string>;
  availableVariables?: string[];
}) {
  const condType = condition.element_exists
    ? 'element_exists'
    : condition.element_not_exists
      ? 'element_not_exists'
      : condition.variable_equals
        ? 'variable_equals'
        : 'element_exists';
  const condData = condition[condType] ?? {};

  const updateCondition = (type: string, data: any) => {
    onChange({ [type]: data });
  };

  const label = (key: string, fallback: string) =>
    condTypeLabels?.[key] ?? fallback;

  return (
    <div className='space-y-1.5'>
      <select
        className={`${inputCls} w-full max-w-xs`}
        value={condType}
        onChange={(e) =>
          updateCondition(
            e.target.value,
            condType === 'variable_equals'
              ? { name: '', value: '' }
              : { by: 'text', value: '' }
          )
        }
      >
        <option value='element_exists'>
          {label('element_exists', 'element_exists')}
        </option>
        <option value='element_not_exists'>
          {label('element_not_exists', 'element_not_exists')}
        </option>
        <option value='variable_equals'>
          {label('variable_equals', 'variable_equals')}
        </option>
      </select>
      {condType !== 'variable_equals' ? (
        <div className='flex items-center gap-2'>
          <SelectorSelect
            value={condData.by ?? 'text'}
            onChange={(v) => updateCondition(condType, { ...condData, by: v })}
          />
          <input
            className={`${inputCls} flex-1`}
            placeholder='selector value'
            value={condData.value ?? ''}
            onChange={(e) =>
              updateCondition(condType, { ...condData, value: e.target.value })
            }
          />
          <VariableInsertSelect
            availableVariables={availableVariables}
            onInsert={(token) =>
              updateCondition(condType, {
                ...condData,
                value: insertToken(condData.value ?? '', token)
              })
            }
          />
        </div>
      ) : (
        <div className='flex items-center gap-2'>
          <input
            className={`${inputCls} w-28 font-mono`}
            placeholder='TÊN_BIẾN'
            value={condData.name ?? ''}
            onChange={(e) =>
              updateCondition('variable_equals', {
                ...condData,
                name: e.target.value
              })
            }
          />
          <VariableInsertSelect
            availableVariables={availableVariables}
            mode='name'
            onInsert={(name) =>
              updateCondition('variable_equals', {
                ...condData,
                name
              })
            }
          />
          <span className={labelCls}>=</span>
          <input
            className={`${inputCls} flex-1`}
            placeholder='giá trị mong đợi'
            value={condData.value ?? ''}
            onChange={(e) =>
              updateCondition('variable_equals', {
                ...condData,
                value: e.target.value
              })
            }
          />
          <VariableInsertSelect
            availableVariables={availableVariables}
            onInsert={(token) =>
              updateCondition('variable_equals', {
                ...condData,
                value: insertToken(condData.value ?? '', token)
              })
            }
          />
        </div>
      )}
    </div>
  );
}

type LoopConfigProps = {
  step: FlowStep;
  onUpdate: (patch: Partial<FlowStep>) => void;
  availableVariables?: string[];
};

/** Full loop config — count vs while mode (detail panel). */
export function LoopConfigFields({
  step,
  onUpdate,
  availableVariables = []
}: LoopConfigProps) {
  const mode = detectLoopMode(step);

  return (
    <div className='space-y-3'>
      <div className='space-y-1'>
        <span className={labelCls}>Kiểu lặp</span>
        <div className='flex flex-wrap gap-1.5'>
          <button
            type='button'
            className={`rounded-md border px-2.5 py-1 text-[11px] transition-colors ${
              mode === 'count'
                ? 'border-primary bg-primary/10 text-foreground'
                : 'border-border bg-background text-muted-foreground hover:bg-muted/50'
            }`}
            onClick={() =>
              onUpdate({
                while: undefined,
                count: step.count ?? '10'
              })
            }
          >
            Cố định N lần
          </button>
          <button
            type='button'
            className={`rounded-md border px-2.5 py-1 text-[11px] transition-colors ${
              mode === 'while'
                ? 'border-primary bg-primary/10 text-foreground'
                : 'border-border bg-background text-muted-foreground hover:bg-muted/50'
            }`}
            onClick={() =>
              onUpdate({
                count: undefined,
                while: step.while ?? {
                  element_exists: { by: 'text', value: '' }
                },
                max_iterations: step.max_iterations ?? 100
              })
            }
          >
            Lặp khi điều kiện đúng
          </button>
        </div>
      </div>

      {mode === 'count' ? (
        <div className='space-y-1'>
          <span className={labelCls}>Số vòng lặp (hỗ trợ biến)</span>
          <input
            className={`${inputCls} w-full font-mono`}
            placeholder='10 hoặc ${MAX_SCROLLS}'
            value={step.count ?? '10'}
            onChange={(e) => onUpdate({ count: e.target.value })}
          />
          <VariableInsertSelect
            availableVariables={availableVariables}
            onInsert={(token) => onUpdate({ count: token })}
          />
          <p className='text-[10px] text-muted-foreground'>
            {randomCountLabel(step)
              ? `Đang chạy ngẫu nhiên ${randomCountLabel(step)} vòng — số này bị bỏ qua (xóa min/max ở dưới để dùng lại).`
              : 'Chạy đúng N lần. Có thể dừng sớm bằng break_if hoặc extract stop_if_no_new.'}
          </p>
        </div>
      ) : (
        <div className='space-y-2'>
          <div className='space-y-1'>
            <span className={labelCls}>Tiếp tục lặp khi</span>
            <ConditionBuilder
              condition={(step.while as Record<string, any>) ?? {}}
              onChange={(next) => onUpdate({ while: next })}
              condTypeLabels={{
                element_exists: 'Phần tử còn trên màn hình',
                element_not_exists: 'Phần tử không còn trên màn hình',
                variable_equals: 'Biến bằng giá trị'
              }}
              availableVariables={availableVariables}
            />
          </div>
          <div className='flex items-center gap-2'>
            <span className={labelCls}>Giới hạn tối đa</span>
            <input
              type='number'
              min={1}
              className={`${inputCls} w-20`}
              value={step.max_iterations ?? 100}
              onChange={(e) =>
                onUpdate({ max_iterations: Number(e.target.value) || 100 })
              }
            />
            <span className={`${labelCls} text-[10px]`}>vòng (an toàn)</span>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * loop — count supports variable references like ${MAX_SCROLLS}
 */
export function LoopFields({
  step,
  onChange,
  availableVariables = []
}: FieldProps) {
  const mode = detectLoopMode(step);
  if (mode === 'while') {
    return (
      <span className={`${labelCls} text-[10px]`}>lặp theo điều kiện</span>
    );
  }
  const randomLabel = randomCountLabel(step);
  if (randomLabel) {
    return (
      <span className={`${labelCls} text-[10px]`}>
        count: ngẫu nhiên {randomLabel} vòng
      </span>
    );
  }
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <span className={labelCls}>count:</span>
      <input
        className={`${inputCls} w-36 font-mono`}
        placeholder='10 hoặc ${MAX_SCROLLS}'
        value={step.count ?? '10'}
        onChange={(e) => onChange('count', e.target.value)}
      />
      <VariableInsertSelect
        availableVariables={availableVariables}
        onInsert={(token) => onChange('count', token)}
      />
      <span className={`${labelCls} text-[9px]`}>(hỗ trợ biến)</span>
    </div>
  );
}

/** random_pick — branch weights (sub-steps handled by parent) */
export function RandomPickFields({ step, onChange }: FieldProps) {
  const branches = step.branches ?? [];
  return (
    <div className='text-[11px] text-muted-foreground'>
      {branches.length} branch(es) — weights: [
      {branches.map((b: any) => b.weight ?? 1).join(', ')}]
    </div>
  );
}
