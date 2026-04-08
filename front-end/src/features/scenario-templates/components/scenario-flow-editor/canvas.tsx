'use client';

/**
 * Pure flowgram.ai canvas — no data fetching, no routing.
 * Imported with `dynamic({ ssr: false })` to avoid InversifyJS
 * "Ambiguous match found for serviceIdentifier: FlowRendererRegistry" error.
 */
import '@flowgram.ai/fixed-layout-editor/index.css';

import { useCallback, useMemo, useRef } from 'react';
import {
  FixedLayoutEditorProvider,
  EditorRenderer,
  type FixedLayoutPluginContext,
  type FixedLayoutProps,
  usePlaygroundTools,
  useClientContext,
} from '@flowgram.ai/fixed-layout-editor';
import { ZoomIn, ZoomOut, Maximize, Undo2, Redo2 } from 'lucide-react';

import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { stepsToFlowDoc, flowDocToSteps } from './converters';
import { scenarioNodeRegistries } from './node-registries';
import { BaseNode } from './base-node';

// ─── Adder: "+" button between nodes ─────────────────────────────────────────
// Must be inside FixedLayoutEditorProvider to use useClientContext().
// Props injected by the library's Adder wrapper: from, to, hoverActivated.

function FlowAdder({ from, hoverActivated }: any) {
  const ctx = useClientContext();

  const handleAdd = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!from) return;
      ctx.operation.addFromNode(from, {
        id: `step-${Date.now()}`,
        type: 'action',
        data: { step: { type: 'tap_selector', by: 'id', value: '' } },
      });
    },
    [ctx, from],
  );

  return (
    <button
      onMouseDown={(e) => e.stopPropagation()} // don't trigger canvas drag
      onClick={handleAdd}
      title='Thêm bước'
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 22,
        height: 22,
        borderRadius: '50%',
        background: hoverActivated ? '#2563eb' : '#d1d5db',
        color: '#fff',
        border: 'none',
        cursor: 'pointer',
        fontSize: 16,
        lineHeight: 1,
        boxShadow: '0 1px 4px rgba(0,0,0,0.18)',
        transition: 'background 0.15s',
      }}
    >
      +
    </button>
  );
}

// ─── Toolbar (must be inside Provider) ───────────────────────────────────────

function CanvasToolbar() {
  const tools = usePlaygroundTools();
  return (
    <div style={toolbarStyle}>
      <button onClick={() => tools.zoomout()} style={iconBtn} title='Thu nhỏ'>
        <ZoomOut size={13} />
      </button>
      <span style={{ fontSize: 11, color: '#9ca3af', minWidth: 36, textAlign: 'center' }}>
        {Math.round(tools.zoom * 100)}%
      </span>
      <button onClick={() => tools.zoomin()} style={iconBtn} title='Phóng to'>
        <ZoomIn size={13} />
      </button>
      <button onClick={() => tools.fitView()} style={iconBtn} title='Vừa khung'>
        <Maximize size={13} />
      </button>
      <div style={{ flex: 1 }} />
      <button onClick={() => tools.undo()} disabled={!tools.canUndo} style={iconBtn} title='Hoàn tác'>
        <Undo2 size={13} />
      </button>
      <button onClick={() => tools.redo()} disabled={!tools.canRedo} style={iconBtn} title='Làm lại'>
        <Redo2 size={13} />
      </button>
    </div>
  );
}

const toolbarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 4,
  padding: '4px 8px',
  borderBottom: '1px solid #e5e7eb',
  background: '#f9fafb',
  height: 36,
  flexShrink: 0,
};

const iconBtn: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'transparent',
  border: '1px solid #e5e7eb',
  borderRadius: 5,
  padding: '3px 6px',
  cursor: 'pointer',
  color: '#4b5563',
  fontSize: 12,
};

// ─── FlowgramCanvas ───────────────────────────────────────────────────────────

export interface FlowgramCanvasProps {
  /** Steps to show — used as initialData; remount via `key` to reset. */
  steps: FlowStep[];
  /** Called on every canvas change so parent can sync back. */
  onStepsChange?: (steps: FlowStep[]) => void;
}

export function FlowgramCanvas({ steps, onStepsChange }: FlowgramCanvasProps) {
  const ctxRef = useRef<FixedLayoutPluginContext | null>(null);

  const initialData = useMemo(() => stepsToFlowDoc(steps), []);  // intentionally no dep — only on mount
  // eslint-disable-next-line react-hooks/exhaustive-deps

  const handleChange = useCallback(
    (ctx: FixedLayoutPluginContext) => {
      if (!onStepsChange) return;
      const doc = ctx.document.toJSON();
      onStepsChange(flowDocToSteps(doc));
    },
    [onStepsChange],
  );

  const editorProps = useMemo<FixedLayoutProps>(
    () => ({
      background: true,
      readonly: false,
      initialData,
      nodeRegistries: scenarioNodeRegistries,
      getNodeDefaultRegistry(type) {
        return { type, meta: { defaultExpanded: true } };
      },
      materials: {
        renderDefaultNode: BaseNode,
        // The library has no built-in defaults — every FlowRendererKey must be
        // provided or it throws "Unknown render key".
        components: {
          // Drag ghost
          'drag-node': () => (
            <div style={{
              background: '#2563eb', color: '#fff', borderRadius: 8,
              padding: '8px 16px', fontSize: 12, opacity: 0.85, cursor: 'grabbing',
            }}>
              Đang di chuyển…
            </div>
          ),
          // "+" button on edges — use FlowAdder which needs useClientContext
          'adder': FlowAdder,
          // Rest unused — register no-ops to satisfy the registry
          'branch-adder': () => null,
          'collapse': () => null,
          'try-catch-collapse': () => null,
          'draggable-adder': () => null,
          'drag-highlight-adder': () => null,
          'drag-branch-highlight-adder': () => null,
          'selector-box-popover': () => null,
          'context-menu-popover': () => null,
          'sub-canvas': () => null,
          'slot-adder': () => null,
          'slot-label': () => null,
          'slot-collapse': () => null,
          'arrow-renderer': () => null,
          'marker-arrow': () => null,
          'marker-active-arrow': () => null,
        },
      },
      nodeEngine: { enable: false },
      // Drag-to-reorder: when a node is dropped onto another, move it after the target
      dragdrop: {
        onDrop(ctx, { dragNodes, dropNode }) {
          ctx.operation.startTransaction();
          try {
            for (const dragNode of dragNodes) {
              if (dragNode.id === dropNode.id) continue;
              // skip start/end nodes
              if (dragNode.flowNodeType === 'start' || dragNode.flowNodeType === 'end') continue;
              const { id: _id, ...jsonWithoutId } = dragNode.toJSON() as any;
              ctx.operation.deleteNode(dragNode);
              ctx.operation.addFromNode(dropNode, jsonWithoutId);
            }
          } finally {
            ctx.operation.endTransaction();
          }
        },
      },
      history: {
        enable: true,
        enableChangeNode: true,
        onApply(ctx) {
          handleChange(ctx);
        },
      },
      onInit(ctx) {
        ctxRef.current = ctx;
      },
      onAllLayersRendered(ctx) {
        setTimeout(() => {
          ctx.playground.config.fitView(ctx.document.root.bounds.pad(40));
        }, 100);
      },
    }),
    [initialData, handleChange],
  );

  return (
    <FixedLayoutEditorProvider {...editorProps}>
      <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}>
        <CanvasToolbar />
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <EditorRenderer style={{ width: '100%', height: '100%' }} />
        </div>
      </div>
    </FixedLayoutEditorProvider>
  );
}
