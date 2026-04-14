'use client';

import { useNodeRender } from '@flowgram.ai/fixed-layout-editor';
import { Play, MousePointer2 } from 'lucide-react';
import { getStepTypeName, getStepDisplay } from '@/features/campaigns/components/flow-editor/constants';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { useFlowgramScenarioWorkbench } from './flowgram-scenario-context';

// ─── Node border color by step type ───────────────────────────────────────────

const BORDER_COLORS: Record<string, string> = {
  tap_selector: '#3b82f6', tap_ratio: '#3b82f6', tap_position: '#3b82f6', tap: '#3b82f6',
  long_tap_selector: '#3b82f6', swipe_ratio: '#3b82f6', double_tap: '#60a5fa',
  pinch: '#0ea5e9', drag: '#2563eb',
  input_text: '#06b6d4', input_selector: '#06b6d4', key: '#06b6d4',
  launch_app: '#6366f1', open_url: '#6366f1',
  scroll_down: '#6366f1', scroll_to: '#6366f1',
  wait: '#22c55e', wait_element: '#22c55e', wait_stable: '#22c55e',
  assert_element: '#22c55e', dismiss_popup: '#22c55e',
  take_screenshot: '#8b5cf6', set_clipboard: '#14b8a6', set_variable: '#a855f7',
  extract: '#d946ef', save_extraction: '#c026d3',
  repeat: '#f97316', repeat_until: '#f97316', loop: '#14b8a6',
  if_element: '#f59e0b', if_variable: '#f59e0b',
  random_pick: '#f43f5e', run_scenario: '#ec4899',
};

function getBorderColor(stepType?: string): string {
  return (stepType && BORDER_COLORS[stepType]) ?? '#9ca3af';
}

// ─── BaseNode ─────────────────────────────────────────────────────────────────

export function BaseNode() {
  const { id, type, data, isBlockOrderIcon, isBlockIcon, activated, startDrag } = useNodeRender();
  const wb = useFlowgramScenarioWorkbench();

  if (isBlockIcon || isBlockOrderIcon) return null;

  if (type === 'start') {
    return (
      <div style={nodeStyles.terminal('#16a34a', activated)} onMouseDown={startDrag}>
        <span style={nodeStyles.terminalText}>▶ Bắt đầu</span>
      </div>
    );
  }

  if (type === 'end') {
    return (
      <div style={nodeStyles.terminal('#dc2626', activated)} onMouseDown={startDrag}>
        <span style={nodeStyles.terminalText}>■ Kết thúc</span>
      </div>
    );
  }

  const step = data?.step as FlowStep | undefined;
  const stepType = step?.type;
  const selected = wb?.selectedFgId === id;
  const borderColor = selected ? '#1d4ed8' : activated ? '#2563eb' : getBorderColor(stepType);
  const display = step ? getStepDisplay(step) : { target: '', selectorBadge: undefined };
  const label = stepType ? getStepTypeName(stepType) : String(type).toUpperCase();
  const runSt = wb?.runStates[id] ?? 'idle';
  const baseCard = nodeStyles.card(borderColor, activated || selected);

  return (
    <div
      style={{
        ...baseCard,
        boxShadow: selected ? '0 0 0 3px #93c5fd' : baseCard.boxShadow,
      }}
      onMouseDown={startDrag}
    >
      {step && wb && (
        <div
          style={nodeStyles.toolbar}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            title="Chạy bước này trên thiết bị (cần chọn device ở Test toàn bộ)"
            style={nodeStyles.tbBtn}
            onClick={(e) => {
              e.stopPropagation();
              if (step) wb.onRunLeafStep(id, step);
            }}
          >
            <Play size={11} fill="currentColor" />
          </button>
          <button
            type="button"
            title="Chỉnh chi tiết (panel bên phải)"
            style={{ ...nodeStyles.tbBtn, color: selected ? '#1d4ed8' : '#6b7280' }}
            onClick={(e) => {
              e.stopPropagation();
              wb.setSelectedFgId(selected ? null : id);
            }}
          >
            <MousePointer2 size={11} />
          </button>
          {runSt === 'running' && <span style={nodeStyles.runDot}>…</span>}
          {runSt === 'ok' && <span style={{ ...nodeStyles.runDot, color: '#16a34a' }}>✓</span>}
          {runSt === 'error' && <span style={{ ...nodeStyles.runDot, color: '#dc2626' }}>✕</span>}
        </div>
      )}
      <div style={nodeStyles.header}>
        {stepType && (
          <span style={{ display: 'flex', alignItems: 'center' }}>
            <StepIcon type={stepType} size={13} />
          </span>
        )}
        <span style={nodeStyles.typeLabel}>{label}</span>
      </div>
      {display.target && (
        <div style={nodeStyles.target} title={display.target}>
          {display.target}
        </div>
      )}
      {display.selectorBadge && (
        <span style={nodeStyles.badge}>{display.selectorBadge}</span>
      )}
    </div>
  );
}

// ─── Inline styles (Tailwind not available inside flowgram canvas) ─────────────

const nodeStyles = {
  terminal: (bg: string, activated?: boolean): React.CSSProperties => ({
    background: bg,
    borderRadius: 20,
    padding: '7px 24px',
    display: 'inline-flex',
    alignItems: 'center',
    minWidth: 130,
    justifyContent: 'center',
    outline: activated ? '2px solid #93c5fd' : undefined,
    outlineOffset: 2,
    cursor: 'grab',
  }),
  terminalText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: 600,
    letterSpacing: '0.02em',
  } as React.CSSProperties,
  card: (borderColor: string, activated?: boolean): React.CSSProperties => ({
    background: activated ? '#eff6ff' : '#ffffff',
    border: `2px solid ${borderColor}`,
    borderRadius: 8,
    padding: '8px 12px',
    minWidth: 170,
    maxWidth: 250,
    boxShadow: activated ? '0 0 0 3px #bfdbfe' : '0 1px 4px rgba(0,0,0,0.10)',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    cursor: 'grab',
  }),
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginBottom: 4,
  } as React.CSSProperties,
  typeLabel: {
    fontSize: 10,
    fontWeight: 700,
    color: '#374151',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  } as React.CSSProperties,
  target: {
    fontSize: 12,
    color: '#4b5563',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    maxWidth: 220,
  } as React.CSSProperties,
  badge: {
    display: 'inline-block',
    background: '#f3f4f6',
    color: '#6b7280',
    borderRadius: 4,
    fontSize: 10,
    padding: '1px 6px',
    marginTop: 4,
    fontFamily: 'monospace',
  } as React.CSSProperties,
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    marginBottom: 6,
    paddingBottom: 4,
    borderBottom: '1px solid #e5e7eb',
  } as React.CSSProperties,
  tbBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 24,
    height: 22,
    borderRadius: 4,
    border: '1px solid #e5e7eb',
    background: '#f9fafb',
    cursor: 'pointer',
    color: '#374151',
    padding: 0,
  } as React.CSSProperties,
  runDot: {
    fontSize: 10,
    fontWeight: 700,
    marginLeft: 2,
    color: '#2563eb',
  } as React.CSSProperties,
};
