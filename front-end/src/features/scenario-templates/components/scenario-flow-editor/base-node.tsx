'use client';

import { useEffect, useState } from 'react';
import {
  useClientContext,
  useNodeRender
} from '@flowgram.ai/fixed-layout-editor';
import { Flag, MousePointer2, Play } from 'lucide-react';
import {
  getStepTypeName,
  getStepDisplay,
  getStepCategory
} from '@/features/campaigns/components/flow-editor/constants';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { useFlowgramScenarioWorkbench } from './flowgram-scenario-context';

// ─── Node border color by step type ───────────────────────────────────────────

const BORDER_COLORS: Record<string, string> = {
  tap_selector: '#3b82f6',
  tap_ratio: '#3b82f6',
  tap_position: '#3b82f6',
  tap: '#3b82f6',
  fb_tap_comment_button: '#2563eb',
  tap_fb_comment_button: '#2563eb',
  long_tap_selector: '#3b82f6',
  swipe_ratio: '#3b82f6',
  double_tap: '#60a5fa',
  pinch: '#0ea5e9',
  drag: '#2563eb',
  input_text: '#06b6d4',
  input_selector: '#06b6d4',
  key: '#06b6d4',
  launch_app: '#6366f1',
  stop_app: '#6366f1',
  clear_app: '#6366f1',
  wait_app: '#6366f1',
  push_file: '#6366f1',
  pull_file: '#6366f1',
  open_url: '#6366f1',
  scroll_down: '#6366f1',
  scroll_to: '#6366f1',
  wait: '#22c55e',
  wait_element: '#22c55e',
  wait_stable: '#22c55e',
  assert_element: '#22c55e',
  dismiss_popup: '#22c55e',
  take_screenshot: '#8b5cf6',
  set_clipboard: '#14b8a6',
  set_variable: '#a855f7',
  extract: '#d946ef',
  save_extraction: '#c026d3',
  repeat: '#f97316',
  repeat_until: '#f97316',
  loop: '#14b8a6',
  if_element: '#f59e0b',
  if_variable: '#f59e0b',
  random_pick: '#f43f5e',
  if: '#f59e0b',
  break_if: '#f59e0b',
  run_scenario: '#ec4899'
};

function getBorderColor(stepType?: string): string {
  return (stepType && BORDER_COLORS[stepType]) ?? '#9ca3af';
}

function getFlowSummary(step?: FlowStep): string[] {
  if (!step) return [];
  if (
    step.type === 'if' ||
    step.type === 'if_element' ||
    step.type === 'if_variable' ||
    step.type === 'tap_fb_comment_button' ||
    step.type === 'fb_tap_comment_button' ||
    Array.isArray(step.then) ||
    Array.isArray(step.else)
  ) {
    return [
      `Đúng: ${Array.isArray(step.then) ? step.then.length : 0}`,
      `Sai: ${Array.isArray(step.else) ? step.else.length : 0}`
    ];
  }
  if (step.type === 'random_pick' || Array.isArray(step.branches)) {
    const branches = Array.isArray(step.branches) ? step.branches : [];
    return [
      `${branches.length} nhánh`,
      `weight: ${branches.map((b: { weight?: number }) => b.weight ?? 1).join('/') || '1'}`
    ];
  }
  if (
    step.type === 'repeat' ||
    step.type === 'repeat_until' ||
    step.type === 'loop' ||
    Array.isArray(step.steps)
  ) {
    const bodyCount = Array.isArray(step.steps) ? step.steps.length : 0;
    const count =
      step.type === 'repeat'
        ? `Lặp: ${step.count ?? '?'}`
        : step.type === 'repeat_until'
          ? `Tối đa: ${step.max_iterations ?? '?'}`
          : step.type === 'loop'
            ? `Loop: ${step.count ?? '?'}`
            : 'Vòng lặp';
    return [count, `Thân: ${bodyCount}`];
  }
  if (step.type === 'break_if') return ['Dừng vòng lặp nếu đúng'];
  return [];
}

// ─── BaseNode ─────────────────────────────────────────────────────────────────

export function BaseNode() {
  const {
    id,
    type,
    data,
    isBlockOrderIcon,
    isBlockIcon,
    node,
    activated,
    startDrag
  } = useNodeRender();
  const ctx = useClientContext();
  const wb = useFlowgramScenarioWorkbench();
  const [selected, setSelected] = useState(() =>
    ctx.selection.selection.includes(node)
  );

  useEffect(() => {
    const disposable = ctx.selection.onSelectionChanged((selection) => {
      setSelected(selection.includes(node));
    });
    return () => disposable.dispose();
  }, [ctx, node]);

  // Flowgram renders compound nodes through virtual icons:
  // - blockIcon points back to the condition/loop node
  // - blockOrderIcon points back to its branch block
  // Render those roles explicitly so their DOM size matches Flowgram's compact
  // compound-node slots instead of reusing the larger action-card geometry.
  if (isBlockOrderIcon) {
    const title = String(data?.title || 'Nhánh');
    return (
      <div style={nodeStyles.branchLabel(activated)} onMouseDown={startDrag}>
        <span style={nodeStyles.branchDot} />
        <span style={nodeStyles.branchText}>{title}</span>
      </div>
    );
  }

  if (type === 'start') {
    return (
      <div
        style={nodeStyles.terminal('#ecfdf5', '#047857', '#bbf7d0', activated)}
        onMouseDown={startDrag}
      >
        <Play size={14} fill='currentColor' />
        <span style={nodeStyles.terminalText}>Bắt đầu</span>
      </div>
    );
  }

  if (type === 'end') {
    return (
      <div
        style={nodeStyles.terminal('#fef2f2', '#b91c1c', '#fecaca', activated)}
        onMouseDown={startDrag}
      >
        <Flag size={14} fill='currentColor' />
        <span style={nodeStyles.terminalText}>Kết thúc</span>
      </div>
    );
  }

  if (type === 'block') {
    const title = String(data?.title || 'Nhánh');
    return (
      <div style={nodeStyles.branchLabel(activated)} onMouseDown={startDrag}>
        <span style={nodeStyles.branchDot} />
        <span style={nodeStyles.branchText}>{title}</span>
      </div>
    );
  }

  const step = data?.step as FlowStep | undefined;
  const stepType = step?.type;
  const borderColor = selected
    ? '#1d4ed8'
    : activated
      ? '#2563eb'
      : getBorderColor(stepType);
  const display = step
    ? getStepDisplay(step)
    : { target: '', selectorBadge: undefined };
  const label = stepType
    ? getStepTypeName(stepType)
    : String(type).toUpperCase();
  const category = stepType ? getStepCategory(stepType) : 'action';
  const isFlowNode =
    type === 'condition' ||
    type === 'loop_node' ||
    stepType === 'if_element' ||
    stepType === 'if_variable' ||
    stepType === 'if' ||
    stepType === 'break_if' ||
    stepType === 'random_pick' ||
    stepType === 'repeat' ||
    stepType === 'repeat_until' ||
    stepType === 'loop' ||
    Array.isArray(step?.then) ||
    Array.isArray(step?.else) ||
    Array.isArray(step?.branches) ||
    Array.isArray(step?.steps);
  const title =
    (step?.title as string | undefined)?.trim() ||
    display.target ||
    (stepType ? getStepTypeName(stepType) : String(type));
  const subtitle =
    display.target && display.target !== title
      ? display.target
      : (step?.description as string | undefined)?.trim() || '';
  const runSt = wb?.runStates[id] ?? 'idle';
  const baseCard = nodeStyles.card(borderColor, activated || selected, runSt);
  const tone = nodeStyles.tone(category, stepType);
  const flowSummary = getFlowSummary(step);

  if (isBlockIcon) {
    const compactCard = nodeStyles.compactControlCard(
      borderColor,
      activated || selected,
      runSt
    );
    return (
      <div
        style={{
          ...compactCard,
          boxShadow: selected ? '0 0 0 3px #93c5fd' : compactCard.boxShadow
        }}
        onMouseDown={startDrag}
        onClick={(e) => {
          e.stopPropagation();
          if (!step) return;
          ctx.selection.selection = e.shiftKey
            ? ctx.selection.selection.includes(node)
              ? ctx.selection.selection.filter((entity) => entity !== node)
              : [...ctx.selection.selection, node]
            : [node];
        }}
      >
        {step && wb && (
          <div
            style={nodeStyles.toolbar}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <button
              type='button'
              title='Chạy bước này trên thiết bị (cần chọn device ở Test toàn bộ)'
              style={nodeStyles.tbBtn}
              onClick={(e) => {
                e.stopPropagation();
                wb.onRunLeafStep(id, step);
              }}
            >
              <Play size={11} fill='currentColor' />
            </button>
            <button
              type='button'
              title='Chỉnh chi tiết (panel bên phải)'
              style={{
                ...nodeStyles.tbBtn,
                color: selected ? '#1d4ed8' : '#6b7280'
              }}
              onClick={(e) => {
                e.stopPropagation();
                ctx.selection.selection = selected ? [] : [node];
              }}
            >
              <MousePointer2 size={11} />
            </button>
            {runSt === 'running' && <span style={nodeStyles.runDot}>…</span>}
            {runSt === 'ok' && (
              <span style={{ ...nodeStyles.runDot, color: '#16a34a' }}>✓</span>
            )}
            {runSt === 'error' && (
              <span style={{ ...nodeStyles.runDot, color: '#dc2626' }}>✕</span>
            )}
          </div>
        )}
        <div style={nodeStyles.compactHeader}>
          <span style={{ ...nodeStyles.compactIconBox, ...tone.icon }}>
            {stepType ? <StepIcon type={stepType} size={14} /> : null}
          </span>
          <div
            style={{
              ...nodeStyles.compactHeading,
              paddingRight: wb ? 58 : undefined
            }}
          >
            <div style={nodeStyles.typeLine}>
              <span style={nodeStyles.typeLabel}>Khối điều khiển</span>
              <span style={{ ...nodeStyles.categoryBadge, ...tone.badge }}>
                Luồng
              </span>
            </div>
            <div style={nodeStyles.title} title={title}>
              {title}
            </div>
          </div>
        </div>
        {flowSummary.length > 0 && (
          <div style={nodeStyles.compactFlowSummary}>
            {flowSummary.map((item) => (
              <span
                key={item}
                style={{ ...nodeStyles.flowPill, ...tone.badge }}
              >
                {item}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      style={{
        ...baseCard,
        boxShadow: selected ? '0 0 0 3px #93c5fd' : baseCard.boxShadow
      }}
      onMouseDown={startDrag}
      onClick={(e) => {
        e.stopPropagation();
        if (!step) return;
        ctx.selection.selection = e.shiftKey
          ? ctx.selection.selection.includes(node)
            ? ctx.selection.selection.filter((entity) => entity !== node)
            : [...ctx.selection.selection, node]
          : [node];
      }}
    >
      {step && wb && (
        <div
          style={nodeStyles.toolbar}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <button
            type='button'
            title='Chạy bước này trên thiết bị (cần chọn device ở Test toàn bộ)'
            style={nodeStyles.tbBtn}
            onClick={(e) => {
              e.stopPropagation();
              if (step) wb.onRunLeafStep(id, step);
            }}
          >
            <Play size={11} fill='currentColor' />
          </button>
          <button
            type='button'
            title='Chỉnh chi tiết (panel bên phải)'
            style={{
              ...nodeStyles.tbBtn,
              color: selected ? '#1d4ed8' : '#6b7280'
            }}
            onClick={(e) => {
              e.stopPropagation();
              ctx.selection.selection = selected ? [] : [node];
            }}
          >
            <MousePointer2 size={11} />
          </button>
          {runSt === 'running' && <span style={nodeStyles.runDot}>…</span>}
          {runSt === 'ok' && (
            <span style={{ ...nodeStyles.runDot, color: '#16a34a' }}>✓</span>
          )}
          {runSt === 'error' && (
            <span style={{ ...nodeStyles.runDot, color: '#dc2626' }}>✕</span>
          )}
        </div>
      )}
      <div style={nodeStyles.header}>
        <span style={{ ...nodeStyles.iconBox, ...tone.icon }}>
          {stepType ? <StepIcon type={stepType} size={15} /> : null}
        </span>
        <div style={nodeStyles.heading}>
          <div style={nodeStyles.typeLine}>
            <span style={nodeStyles.typeLabel}>
              {isFlowNode ? 'Khối điều khiển' : label}
            </span>
            <span style={{ ...nodeStyles.categoryBadge, ...tone.badge }}>
              {category === 'flow' ? 'Luồng' : 'Thao tác'}
            </span>
          </div>
          <div style={nodeStyles.title} title={title}>
            {title}
          </div>
        </div>
      </div>
      {subtitle && (
        <div style={nodeStyles.target} title={subtitle}>
          {subtitle}
        </div>
      )}
      {flowSummary.length > 0 && (
        <div style={nodeStyles.flowSummary}>
          {flowSummary.map((item) => (
            <span key={item} style={{ ...nodeStyles.flowPill, ...tone.badge }}>
              {item}
            </span>
          ))}
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
  terminal: (
    bg: string,
    fg: string,
    border: string,
    activated?: boolean
  ): React.CSSProperties => ({
    background: bg,
    borderRadius: 999,
    border: `1px solid ${activated ? '#2563eb' : border}`,
    color: fg,
    padding: '8px 18px',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    minWidth: 138,
    justifyContent: 'center',
    outline: activated ? '2px solid #bfdbfe' : undefined,
    outlineOffset: 2,
    cursor: 'grab',
    boxShadow: '0 4px 14px rgba(15,23,42,0.08)'
  }),
  terminalText: {
    fontSize: 12,
    fontWeight: 600,
    letterSpacing: 0
  } as React.CSSProperties,
  card: (
    borderColor: string,
    activated?: boolean,
    runState?: 'idle' | 'running' | 'ok' | 'error'
  ): React.CSSProperties => ({
    position: 'relative',
    background:
      runState === 'running'
        ? '#eff6ff'
        : runState === 'ok'
          ? '#ecfdf5'
          : runState === 'error'
            ? '#fef2f2'
            : activated
              ? '#f8fafc'
              : '#ffffff',
    border: `1px solid ${activated ? '#2563eb' : '#dbe3ed'}`,
    borderLeft: `4px solid ${borderColor}`,
    borderRadius: 8,
    padding: '12px 14px',
    minWidth: 300,
    maxWidth: 360,
    boxShadow: activated
      ? '0 8px 18px rgba(37,99,235,0.13), 0 0 0 2px #bfdbfe'
      : '0 6px 18px rgba(15,23,42,0.07)',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    cursor: 'grab',
    transition:
      'box-shadow 0.15s ease, border-color 0.15s ease, background 0.15s ease'
  }),
  compactControlCard: (
    borderColor: string,
    activated?: boolean,
    runState?: 'idle' | 'running' | 'ok' | 'error'
  ): React.CSSProperties => ({
    position: 'relative',
    boxSizing: 'border-box',
    width: 250,
    minHeight: 84,
    background:
      runState === 'running'
        ? '#eff6ff'
        : runState === 'ok'
          ? '#ecfdf5'
          : runState === 'error'
            ? '#fef2f2'
            : activated
              ? '#f8fafc'
              : '#ffffff',
    border: `1px solid ${activated ? '#2563eb' : '#dbe3ed'}`,
    borderLeft: `4px solid ${borderColor}`,
    borderRadius: 8,
    padding: '10px 12px',
    boxShadow: activated
      ? '0 7px 16px rgba(37,99,235,0.12), 0 0 0 2px #bfdbfe'
      : '0 5px 14px rgba(15,23,42,0.07)',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    cursor: 'grab',
    transition:
      'box-shadow 0.15s ease, border-color 0.15s ease, background 0.15s ease'
  }),
  header: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 10,
    minWidth: 0
  } as React.CSSProperties,
  compactHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 9,
    minWidth: 0
  } as React.CSSProperties,
  compactIconBox: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 30,
    height: 30,
    borderRadius: 7,
    flexShrink: 0
  } as React.CSSProperties,
  compactHeading: {
    minWidth: 0,
    flex: 1
  } as React.CSSProperties,
  iconBox: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 32,
    height: 32,
    borderRadius: 8,
    flexShrink: 0
  } as React.CSSProperties,
  heading: {
    minWidth: 0,
    flex: 1,
    paddingRight: 60
  } as React.CSSProperties,
  typeLine: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    minWidth: 0,
    marginBottom: 4
  } as React.CSSProperties,
  typeLabel: {
    fontSize: 10,
    fontWeight: 700,
    color: '#64748b',
    textTransform: 'uppercase' as const,
    letterSpacing: 0,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis'
  } as React.CSSProperties,
  categoryBadge: {
    borderRadius: 999,
    fontSize: 9,
    fontWeight: 700,
    padding: '1px 6px',
    whiteSpace: 'nowrap'
  } as React.CSSProperties,
  title: {
    fontSize: 13,
    lineHeight: 1.28,
    fontWeight: 700,
    color: '#0f172a',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap'
  } as React.CSSProperties,
  target: {
    marginTop: 8,
    fontSize: 12,
    color: '#64748b',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    maxWidth: 290
  } as React.CSSProperties,
  badge: {
    display: 'inline-block',
    background: '#f8fafc',
    color: '#64748b',
    border: '1px solid #e2e8f0',
    borderRadius: 6,
    fontSize: 10,
    padding: '2px 6px',
    marginTop: 7,
    fontFamily: 'monospace',
    maxWidth: 180,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap'
  } as React.CSSProperties,
  flowSummary: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 5,
    marginTop: 8
  } as React.CSSProperties,
  compactFlowSummary: {
    display: 'flex',
    flexWrap: 'nowrap',
    gap: 4,
    marginTop: 7,
    overflow: 'hidden'
  } as React.CSSProperties,
  flowPill: {
    borderRadius: 6,
    fontSize: 10,
    fontWeight: 700,
    padding: '2px 6px'
  } as React.CSSProperties,
  toolbar: {
    position: 'absolute',
    top: 8,
    right: 8,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    zIndex: 1
  } as React.CSSProperties,
  tbBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 25,
    height: 22,
    borderRadius: 5,
    border: '1px solid #dbe3ed',
    background: '#ffffff',
    cursor: 'pointer',
    color: '#475569',
    padding: 0,
    boxShadow: '0 1px 2px rgba(15,23,42,0.08)'
  } as React.CSSProperties,
  runDot: {
    fontSize: 10,
    fontWeight: 700,
    marginLeft: 2,
    color: '#2563eb'
  } as React.CSSProperties,
  branchLabel: (activated?: boolean): React.CSSProperties => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: 7,
    height: 28,
    minWidth: 180,
    padding: '0 12px',
    borderRadius: 7,
    background: activated ? '#fff7ed' : '#fffaf5',
    border: `1px solid ${activated ? '#fb923c' : '#fdba74'}`,
    color: '#7c2d12',
    boxShadow: '0 3px 10px rgba(15,23,42,0.05)',
    cursor: 'grab'
  }),
  branchDot: {
    width: 7,
    height: 7,
    borderRadius: 999,
    background: '#f97316',
    flexShrink: 0
  } as React.CSSProperties,
  branchText: {
    fontSize: 11,
    fontWeight: 700,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis'
  } as React.CSSProperties,
  tone: (category: string, stepType?: string) => {
    if (category === 'flow') {
      if (stepType === 'random_pick') {
        return {
          icon: {
            background: '#fff1f2',
            color: '#be123c',
            boxShadow: 'inset 0 0 0 1px #fecdd3'
          },
          badge: {
            background: '#ffe4e6',
            color: '#9f1239'
          }
        };
      }
      if (
        stepType === 'repeat' ||
        stepType === 'repeat_until' ||
        stepType === 'loop'
      ) {
        return {
          icon: {
            background: '#ecfdf5',
            color: '#047857',
            boxShadow: 'inset 0 0 0 1px #a7f3d0'
          },
          badge: {
            background: '#d1fae5',
            color: '#065f46'
          }
        };
      }
      return {
        icon: {
          background: '#fff7ed',
          color: '#c2410c',
          boxShadow: 'inset 0 0 0 1px #fed7aa'
        },
        badge: {
          background: '#ffedd5',
          color: '#9a3412'
        }
      };
    }
    return {
      icon: {
        background: '#eff6ff',
        color: '#1d4ed8',
        boxShadow: 'inset 0 0 0 1px #bfdbfe'
      },
      badge: {
        background: '#e0f2fe',
        color: '#075985'
      }
    };
  }
};
