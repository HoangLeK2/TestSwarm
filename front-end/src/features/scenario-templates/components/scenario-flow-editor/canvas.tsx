'use client';

/**
 * Pure flowgram.ai canvas — no data fetching, no routing.
 * Imported with `dynamic({ ssr: false })` to avoid InversifyJS
 * "Ambiguous match found for serviceIdentifier: FlowRendererRegistry" error.
 */
import '@flowgram.ai/fixed-layout-editor/index.css';
import './flowgram-control-theme.css';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FixedLayoutEditorProvider,
  EditorRenderer,
  FlowNodeEntity,
  type FixedLayoutPluginContext,
  type FixedLayoutProps,
  usePlaygroundTools,
  useClientContext
} from '@flowgram.ai/fixed-layout-editor';
import {
  ClipboardCopy,
  ClipboardPaste,
  CopyPlus,
  Maximize,
  Plus,
  Redo2,
  Trash2,
  Undo2,
  ZoomIn,
  ZoomOut
} from 'lucide-react';
import { nanoid } from 'nanoid';

import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { createDefaultStep } from '@/features/campaigns/components/scenario-steps/types';
import { stepsToFlowDoc, flowDocToSteps, stepToFlowNode } from './converters';
import { scenarioNodeRegistries } from './node-registries';
import { BaseNode } from './base-node';
import { canDropScenarioNodes } from './drag-drop-rules';
import { getSingleEditableFlowNodeId } from './selection';
import { updateScenarioNodeDataOperationMeta } from './node-data-history';
import {
  parseScenarioClipboardNodes,
  regenerateScenarioClipboardNodeIds,
  serializeScenarioClipboardNodes
} from './clipboard';
import {
  FlowgramScenarioProvider,
  type FlowgramScenarioWorkbench
} from './flowgram-scenario-context';

// ─── Adder: "+" button between nodes ─────────────────────────────────────────
// Must be inside FixedLayoutEditorProvider to use useClientContext().
// Props injected by the library's Adder wrapper: from, to, hoverActivated.

const ADDER_STEP_OPTIONS = [
  {
    group: 'Thao tác',
    items: [
      { type: 'tap_selector', label: 'Chạm selector' },
      { type: 'tap_ratio', label: 'Chạm tọa độ' },
      { type: 'input_selector', label: 'Nhập text' },
      { type: 'swipe_ratio', label: 'Vuốt' },
      { type: 'wait', label: 'Chờ' },
      { type: 'dismiss_popup', label: 'Đóng popup' }
    ]
  },
  {
    group: 'Luồng',
    items: [
      { type: 'if_element', label: 'If element' },
      { type: 'if_variable', label: 'If biến' },
      { type: 'repeat', label: 'Lặp N lần' },
      { type: 'repeat_until', label: 'Lặp đến khi' },
      { type: 'random_pick', label: 'Chọn ngẫu nhiên' },
      { type: 'run_scenario', label: 'Chạy kịch bản' }
    ]
  }
] as const;

function FlowAdder({ from, hoverActivated }: any) {
  const ctx = useClientContext();
  const [open, setOpen] = useState(false);

  const handleAdd = useCallback(
    (type: string) => {
      if (!from) return;
      const step = createDefaultStep(type) as FlowStep;
      ctx.operation.addFromNode(from, stepToFlowNode(step));
      setOpen(false);
    },
    [ctx, from]
  );

  return (
    <div style={adderWrap} onMouseDown={(e) => e.stopPropagation()}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        type='button'
        aria-label='Thêm bước'
        style={{
          ...adderButton,
          background: hoverActivated || open ? '#2563eb' : '#ffffff',
          color: hoverActivated || open ? '#ffffff' : '#2563eb',
          boxShadow:
            hoverActivated || open
              ? '0 8px 18px rgba(37,99,235,0.22)'
              : '0 4px 12px rgba(15,23,42,0.10)'
        }}
      >
        <Plus size={14} strokeWidth={2.4} />
      </button>
      {open ? (
        <div style={adderMenu}>
          {ADDER_STEP_OPTIONS.map((group) => (
            <div key={group.group} style={adderGroup}>
              <div style={adderGroupLabel}>{group.group}</div>
              <div style={adderGrid}>
                {group.items.map((item) => (
                  <button
                    key={item.type}
                    type='button'
                    style={adderItem}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleAdd(item.type);
                    }}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const adderWrap: React.CSSProperties = {
  position: 'relative',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 20
};

const adderButton: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 26,
  height: 26,
  borderRadius: '50%',
  border: '1px solid #bfdbfe',
  cursor: 'pointer',
  transition: 'background 0.15s, color 0.15s, box-shadow 0.15s'
};

const adderMenu: React.CSSProperties = {
  position: 'absolute',
  top: 31,
  left: '50%',
  transform: 'translateX(-50%)',
  width: 260,
  borderRadius: 8,
  border: '1px solid #dbe3ed',
  background: '#ffffff',
  boxShadow: '0 18px 38px rgba(15,23,42,0.18)',
  padding: 8,
  zIndex: 50
};

const adderGroup: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  padding: '4px 0'
};

const adderGroupLabel: React.CSSProperties = {
  color: '#64748b',
  fontSize: 10,
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: 0,
  padding: '0 3px'
};

const adderGrid: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: 6
};

const adderItem: React.CSSProperties = {
  height: 30,
  borderRadius: 6,
  border: '1px solid #e2e8f0',
  background: '#f8fafc',
  color: '#0f172a',
  fontSize: 11,
  fontWeight: 600,
  cursor: 'pointer',
  textAlign: 'left',
  padding: '0 8px'
};

function DragInsertionMarker({ active = false }: { active?: boolean }) {
  return (
    <div
      aria-hidden='true'
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: active ? 190 : 120,
        height: active ? 28 : 18,
        borderRadius: 999,
        border: `1px ${active ? 'solid' : 'dashed'} ${active ? '#2563eb' : '#93c5fd'}`,
        background: active ? '#dbeafe' : 'rgba(239,246,255,0.9)',
        color: '#1d4ed8',
        fontSize: 10,
        fontWeight: 700,
        boxShadow: active ? '0 5px 16px rgba(37,99,235,0.24)' : undefined,
        transition: 'all 120ms ease'
      }}
    >
      {active ? 'Thả vào vị trí này' : 'Có thể thả tại đây'}
    </div>
  );
}

// ─── Toolbar (must be inside Provider) ───────────────────────────────────────

function isEditableFlowNode(entity: unknown): entity is FlowNodeEntity {
  return (
    entity instanceof FlowNodeEntity &&
    !['start', 'end', 'block', 'blockIcon', 'blockOrderIcon'].includes(
      String(entity.flowNodeType)
    )
  );
}

function getEditableSelection(ctx: FixedLayoutPluginContext): FlowNodeEntity[] {
  const selectedNodes = ctx.selection.selection.filter(isEditableFlowNode);
  const selectedIds = new Set(selectedNodes.map((node) => node.id));

  return selectedNodes.filter((node) => {
    let parent = node.parent;
    while (parent) {
      if (selectedIds.has(parent.id)) return false;
      parent = parent.parent;
    }
    return true;
  });
}

function getLastInsertAnchor(
  ctx: FixedLayoutPluginContext,
  selectedNodes: FlowNodeEntity[]
): FlowNodeEntity | null {
  if (selectedNodes.length === 1) return selectedNodes[0]!;
  return (
    ctx.document.getAllNodes().find((node) => node.flowNodeType === 'start') ??
    null
  );
}

function CanvasToolbar({ stepCount }: { stepCount: number }) {
  const tools = usePlaygroundTools();
  const ctx = useClientContext();
  const [selectionVersion, setSelectionVersion] = useState(0);
  const [hasClipboard, setHasClipboard] = useState(false);

  useEffect(() => {
    const syncClipboard = () => {
      const value = ctx.clipboard.readText();
      Promise.resolve(value).then((text) => {
        setHasClipboard(Boolean(parseScenarioClipboardNodes(text)));
      });
    };
    const selectionDisposable = ctx.selection.onSelectionChanged(() => {
      setSelectionVersion((version) => version + 1);
    });
    const clipboardDisposable = ctx.clipboard.onClipboardChanged(syncClipboard);
    syncClipboard();
    return () => {
      selectionDisposable.dispose();
      clipboardDisposable.dispose();
    };
  }, [ctx]);

  void selectionVersion;
  const selectedNodes = getEditableSelection(ctx);
  const copySelection = useCallback(async () => {
    if (selectedNodes.length === 0) return;
    await ctx.clipboard.writeText(
      serializeScenarioClipboardNodes(
        selectedNodes.map((node) => node.toJSON())
      )
    );
  }, [ctx, selectedNodes]);
  const pasteClipboard = useCallback(async () => {
    const copied = parseScenarioClipboardNodes(await ctx.clipboard.readText());
    if (!copied?.length) return;
    const anchor = getLastInsertAnchor(ctx, selectedNodes);
    if (!anchor) return;

    const pastedNodes = regenerateScenarioClipboardNodeIds(copied, () =>
      nanoid(10)
    );
    const created: FlowNodeEntity[] = [];
    ctx.history.transact(() => {
      let fromNode = anchor;
      for (const nodeJson of pastedNodes) {
        const node = ctx.operation.addFromNode(fromNode, nodeJson);
        created.push(node);
        fromNode = node;
      }
    });
    ctx.selection.selection = created;
  }, [ctx, selectedNodes]);
  const duplicateSelection = useCallback(async () => {
    if (selectedNodes.length === 0) return;
    await ctx.clipboard.writeText(
      serializeScenarioClipboardNodes(
        selectedNodes.map((node) => node.toJSON())
      )
    );
    await pasteClipboard();
  }, [ctx, pasteClipboard, selectedNodes]);
  const deleteSelection = useCallback(() => {
    if (selectedNodes.length === 0) return;
    ctx.operation.deleteNodes(selectedNodes);
    ctx.selection.selection = [];
  }, [ctx, selectedNodes]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!ctx.playground.focused || (!event.metaKey && !event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      if (
        target?.matches('input, textarea, select, [contenteditable="true"]')
      ) {
        return;
      }

      if (event.key.toLowerCase() === 'c' && selectedNodes.length > 0) {
        event.preventDefault();
        void copySelection();
      } else if (event.key.toLowerCase() === 'v' && hasClipboard) {
        event.preventDefault();
        void pasteClipboard();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [copySelection, ctx, hasClipboard, pasteClipboard, selectedNodes.length]);

  return (
    <div style={toolbarStyle}>
      <div style={toolbarTitle}>
        <span style={toolbarTitleDot} />
        <span>Luồng kịch bản</span>
        <span style={toolbarCount}>{stepCount} bước</span>
      </div>
      <div style={{ flex: 1 }} />
      <button
        onClick={() => void copySelection()}
        disabled={selectedNodes.length === 0}
        style={iconBtn}
        title='Sao chép (Ctrl/Cmd+C)'
      >
        <ClipboardCopy size={13} />
      </button>
      <button
        onClick={() => void pasteClipboard()}
        disabled={!hasClipboard}
        style={iconBtn}
        title='Dán sau node đang chọn (Ctrl/Cmd+V)'
      >
        <ClipboardPaste size={13} />
      </button>
      <button
        onClick={() => void duplicateSelection()}
        disabled={selectedNodes.length === 0}
        style={iconBtn}
        title='Nhân bản node đang chọn'
      >
        <CopyPlus size={13} />
      </button>
      <button
        onClick={deleteSelection}
        disabled={selectedNodes.length === 0}
        style={iconBtn}
        title='Xóa node đang chọn (Delete)'
      >
        <Trash2 size={13} />
      </button>
      <div style={toolbarDivider} />
      <button onClick={() => tools.zoomout()} style={iconBtn} title='Thu nhỏ'>
        <ZoomOut size={13} />
      </button>
      <span
        style={{
          fontSize: 11,
          color: '#9ca3af',
          minWidth: 36,
          textAlign: 'center'
        }}
      >
        {Math.round(tools.zoom * 100)}%
      </span>
      <button onClick={() => tools.zoomin()} style={iconBtn} title='Phóng to'>
        <ZoomIn size={13} />
      </button>
      <button onClick={() => tools.fitView()} style={iconBtn} title='Vừa khung'>
        <Maximize size={13} />
      </button>
      <div style={toolbarDivider} />
      <button
        onClick={() => tools.undo()}
        disabled={!tools.canUndo}
        style={iconBtn}
        title='Hoàn tác'
      >
        <Undo2 size={13} />
      </button>
      <button
        onClick={() => tools.redo()}
        disabled={!tools.canRedo}
        style={iconBtn}
        title='Làm lại'
      >
        <Redo2 size={13} />
      </button>
    </div>
  );
}

const toolbarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  padding: '6px 12px',
  borderBottom: '1px solid #e2e8f0',
  background: '#ffffff',
  height: 42,
  flexShrink: 0
};

const toolbarTitle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  minWidth: 0,
  gap: 8,
  fontSize: 12,
  fontWeight: 700,
  color: '#0f172a'
};

const toolbarTitleDot: React.CSSProperties = {
  width: 8,
  height: 8,
  borderRadius: 999,
  background: '#2563eb',
  boxShadow: '0 0 0 3px #dbeafe'
};

const toolbarCount: React.CSSProperties = {
  borderRadius: 999,
  background: '#f1f5f9',
  color: '#64748b',
  fontSize: 10,
  fontWeight: 700,
  padding: '2px 7px'
};

const toolbarDivider: React.CSSProperties = {
  width: 1,
  height: 22,
  background: '#e2e8f0',
  margin: '0 2px'
};

const iconBtn: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: '#f8fafc',
  border: '1px solid #e2e8f0',
  borderRadius: 7,
  width: 28,
  height: 28,
  padding: 0,
  cursor: 'pointer',
  color: '#475569',
  fontSize: 12,
  boxShadow: '0 1px 2px rgba(15,23,42,0.04)'
};

// ─── FlowgramCanvas ───────────────────────────────────────────────────────────

export interface FlowgramCanvasProps {
  /** Steps to show — used as initialData; remount via `key` to reset. */
  steps: FlowStep[];
  /** Called on every canvas change so parent can sync back. */
  onStepsChange?: (steps: FlowStep[]) => void;
  /** Run / select wiring for scenario dialog (optional). */
  workbench?: FlowgramScenarioWorkbench | null;
  /** Exposes editor ctx for document.fromJSON sync from parent. */
  onFlowCtx?: (ctx: FixedLayoutPluginContext | null) => void;
}

export function FlowgramCanvas({
  steps,
  onStepsChange,
  workbench = null,
  onFlowCtx
}: FlowgramCanvasProps) {
  const ctxRef = useRef<FixedLayoutPluginContext | null>(null);
  const selectionDisposeRef = useRef<{ dispose(): void } | null>(null);
  const initialFitPendingRef = useRef(true);
  const initialFitFrameRef = useRef<number | null>(null);
  const workbenchRef = useRef(workbench);
  workbenchRef.current = workbench;

  // eslint-disable-next-line react-hooks/exhaustive-deps -- initialData is read only on mount; parent remounts/syncs external step changes.
  const initialData = useMemo(() => stepsToFlowDoc(steps), []);

  const handleChange = useCallback(
    (ctx: FixedLayoutPluginContext) => {
      if (!onStepsChange) return;
      const doc = ctx.document.toJSON();
      onStepsChange(flowDocToSteps(doc));
    },
    [onStepsChange]
  );

  const scheduleInitialFit = useCallback((ctx: FixedLayoutPluginContext) => {
    if (!initialFitPendingRef.current || initialFitFrameRef.current !== null) {
      return;
    }

    let previousBounds = '';
    let stableFrames = 0;
    let frameCount = 0;
    const fitWhenStable = () => {
      if (ctxRef.current !== ctx || !initialFitPendingRef.current) {
        initialFitFrameRef.current = null;
        return;
      }

      ctx.document.transformer.refresh();
      const bounds = ctx.document.root.bounds;
      const boundsKey = [bounds.x, bounds.y, bounds.width, bounds.height].join(
        ':'
      );
      frameCount += 1;
      stableFrames = boundsKey === previousBounds ? stableFrames + 1 : 0;
      previousBounds = boundsKey;

      if ((frameCount >= 4 && stableFrames >= 2) || frameCount >= 12) {
        initialFitPendingRef.current = false;
        initialFitFrameRef.current = null;
        void ctx.playground.config.fitView(bounds.pad(40));
        return;
      }

      initialFitFrameRef.current = window.requestAnimationFrame(fitWhenStable);
    };

    initialFitFrameRef.current = window.requestAnimationFrame(fitWhenStable);
  }, []);

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
            <div
              style={{
                background: '#2563eb',
                color: '#fff',
                borderRadius: 8,
                padding: '8px 16px',
                fontSize: 12,
                opacity: 0.85,
                cursor: 'grabbing'
              }}
            >
              Đang di chuyển…
            </div>
          ),
          // "+" button on edges — use FlowAdder which needs useClientContext
          adder: FlowAdder,
          // Rest unused — register no-ops to satisfy the registry
          'branch-adder': () => null,
          collapse: () => null,
          'try-catch-collapse': () => null,
          'draggable-adder': () => <DragInsertionMarker />,
          'drag-highlight-adder': () => <DragInsertionMarker active />,
          'drag-branch-highlight-adder': () => <DragInsertionMarker active />,
          'selector-box-popover': () => null,
          'context-menu-popover': () => null,
          'sub-canvas': () => null,
          'slot-adder': () => null,
          'slot-label': () => null,
          'slot-collapse': () => null,
          'arrow-renderer': () => null,
          'marker-arrow': () => null,
          'marker-active-arrow': () => null
        }
      },
      nodeEngine: { enable: false },
      selectBox: {
        enable: true,
        ignoreOneSelect: false,
        ignoreChildrenLength: false
      },
      dragdrop: {
        canDrop(_ctx, dropData) {
          return canDropScenarioNodes(dropData);
        }
      },
      history: {
        enable: true,
        enableChangeNode: true,
        operationMetas: [updateScenarioNodeDataOperationMeta],
        onApply(ctx) {
          handleChange(ctx);
        }
      },
      onInit(ctx) {
        ctxRef.current = ctx;
        selectionDisposeRef.current?.dispose();
        const syncWorkbenchSelection = () => {
          workbenchRef.current?.setSelectedFgId(
            getSingleEditableFlowNodeId(ctx.selection.selection)
          );
        };
        selectionDisposeRef.current = ctx.selection.onSelectionChanged(
          syncWorkbenchSelection
        );
        syncWorkbenchSelection();
        onFlowCtx?.(ctx);
      },
      onDispose(ctx) {
        selectionDisposeRef.current?.dispose();
        selectionDisposeRef.current = null;
        if (initialFitFrameRef.current !== null) {
          window.cancelAnimationFrame(initialFitFrameRef.current);
          initialFitFrameRef.current = null;
        }
        ctx.selection.selection = [];
        ctxRef.current = null;
        workbenchRef.current?.setSelectedFgId(null);
        onFlowCtx?.(null);
      },
      onAllLayersRendered(ctx) {
        scheduleInitialFit(ctx);
      }
    }),
    [initialData, handleChange, onFlowCtx, scheduleInitialFit]
  );

  const shell = (
    <FixedLayoutEditorProvider {...editorProps}>
      <div
        className='scenario-flowgram-shell'
        style={{
          display: 'flex',
          flexDirection: 'column',
          width: '100%',
          height: '100%',
          background: '#f8fafc'
        }}
      >
        <CanvasToolbar stepCount={steps.length} />
        <div style={{ flex: 1, overflow: 'hidden', background: '#f8fafc' }}>
          <EditorRenderer style={{ width: '100%', height: '100%' }} />
        </div>
      </div>
    </FixedLayoutEditorProvider>
  );

  if (workbench) {
    return (
      <FlowgramScenarioProvider value={workbench}>
        {shell}
      </FlowgramScenarioProvider>
    );
  }
  return shell;
}
