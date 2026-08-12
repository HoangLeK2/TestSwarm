'use client';

import '@xyflow/react/dist/style.css';
import './scenario-automation-map.css';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  applyNodeChanges,
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  type NodeTypes,
  type ReactFlowInstance
} from '@xyflow/react';
import {
  ArrowLeft,
  ArrowRight,
  GitBranch,
  GripVertical,
  Loader2,
  Maximize2,
  Plus,
  Repeat,
  Shuffle,
  Workflow
} from 'lucide-react';
import { useTranslations } from 'next-intl';

import {
  formatStepLabelForCard,
  getStepCategory,
  getStepDisplay,
  getStepTypeName
} from '@/features/campaigns/components/flow-editor/constants';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import {
  ALL_STEP_TYPES,
  type FlowEdge,
  type FlowNode,
  type FlowStep,
  type NodeScope
} from '@/features/campaigns/components/scenario-steps/types';
import { getOrderedScopeNodes } from '@/features/campaigns/utils/scenario-graph';
import { cn } from '@/lib/utils';
import {
  countScenarioSteps,
  layoutScenarioAutomation,
  type ScenarioLaneTone,
  type ScenarioLayoutEdge,
  type ScenarioLayoutNode
} from './scenario-automation-layout';

type ScenarioNodeCallbacks = {
  selectedNodeId: string | null;
  dragSourceNodeId: string | null;
  dropTargetKey: string;
  onSelect: (nodeId: string, step: FlowStep) => void;
  onInsert: (
    scope: NodeScope | null,
    afterNodeId: string | null,
    type: string
  ) => void;
  onMove: (
    nodeId: string,
    scope: NodeScope | null,
    afterNodeId: string | null
  ) => boolean;
};

type DropTarget = {
  scope: NodeScope | null;
  afterNodeId: string | null;
};

function scopeKey(scope: NodeScope | null): string {
  return scope ? `${scope.parentId}:${scope.branch}` : 'root';
}

function dropTargetKey(target: DropTarget | null): string {
  return target
    ? `${scopeKey(target.scope)}:${target.afterNodeId ?? 'start'}`
    : '';
}

type ScenarioNodeData = ScenarioNodeCallbacks & {
  kind: 'step';
  nodeId: string;
  scope: NodeScope | null;
  index: number;
  siblingCount: number;
  previousNodeId: string | null;
  moveBackAfterNodeId: string | null;
  moveForwardAfterNodeId: string | null;
  step: FlowStep;
};

type AnchorNodeData = {
  kind: 'anchor';
  title: string;
  subtitle: string;
};

type PlaceholderNodeData = {
  kind: 'placeholder';
  scope: NodeScope | null;
  label: string;
  dropTargetKey: string;
  onInsert: ScenarioNodeCallbacks['onInsert'];
};

type FrameNodeData = {
  kind: 'frame';
  title: string;
  subtitle: string;
  tone: ScenarioLaneTone;
};

type JunctionNodeData = { kind: 'junction' };
type AutomationNodeData =
  | ScenarioNodeData
  | AnchorNodeData
  | PlaceholderNodeData
  | FrameNodeData
  | JunctionNodeData;
type AutomationNode = Node<AutomationNodeData>;
type AutomationEdgeData = { points: Array<{ x: number; y: number }> };
type AutomationEdge = Edge<AutomationEdgeData, 'scenario'>;

function StepTypeMenu({
  align = 'left',
  label = 'Thêm bước',
  iconOnly = false,
  onAdd
}: {
  align?: 'left' | 'right' | 'center';
  label?: string;
  iconOnly?: boolean;
  onAdd: (type: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const grouped = useMemo(() => {
    const map = new Map<string, typeof ALL_STEP_TYPES>();
    for (const item of ALL_STEP_TYPES) {
      const group = item.group || 'action';
      map.set(group, [...(map.get(group) ?? []), item]);
    }
    return Array.from(map.entries());
  }, []);

  return (
    <div className='nodrag nopan relative'>
      <button
        type='button'
        className={cn(
          'scenario-node-action',
          !iconOnly && 'scenario-node-action--labelled'
        )}
        title={label}
        aria-label={label}
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
      >
        <Plus className='size-3.5' />
        {!iconOnly ? <span>{label}</span> : null}
      </button>
      {open ? (
        <div
          className={cn(
            'scenario-step-menu',
            align === 'right'
              ? 'right-0'
              : align === 'center'
                ? 'left-1/2 -translate-x-1/2'
                : 'left-0'
          )}
          onClick={(event) => event.stopPropagation()}
        >
          {grouped.map(([group, items]) => (
            <div key={group} className='space-y-1 py-1'>
              <div className='px-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                {group}
              </div>
              <div className='grid grid-cols-2 gap-1'>
                {items.map((item) => (
                  <button
                    key={item.value}
                    type='button'
                    className='h-8 truncate rounded-md border border-border bg-background px-2 text-left text-[11px] font-medium text-foreground transition-colors hover:border-primary/35 hover:bg-primary/5 hover:text-primary'
                    title={getStepTypeName(item.value)}
                    onClick={() => {
                      onAdd(item.value);
                      setOpen(false);
                    }}
                  >
                    {getStepTypeName(item.value)}
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

function countNestedSteps(steps: FlowStep[] | undefined): number {
  if (!Array.isArray(steps)) return 0;
  return steps.reduce(
    (total, step) =>
      total +
      1 +
      countNestedSteps(step.steps) +
      countNestedSteps(step.then) +
      countNestedSteps(step.else) +
      (Array.isArray(step.branches)
        ? step.branches.reduce(
            (branchTotal: number, branch: { steps?: FlowStep[] }) =>
              branchTotal + countNestedSteps(branch.steps),
            0
          )
        : 0),
    0
  );
}

function FlowBadge({ step }: { step: FlowStep }) {
  if (Array.isArray(step.branches)) {
    return (
      <span className='scenario-flow-badge scenario-flow-badge--rose'>
        <Shuffle className='size-3' />
        {step.branches.length}
      </span>
    );
  }
  if (Array.isArray(step.steps)) {
    return (
      <span className='scenario-flow-badge scenario-flow-badge--sky'>
        <Repeat className='size-3' />
        {countNestedSteps(step.steps)}
      </span>
    );
  }
  if (Array.isArray(step.then) || Array.isArray(step.else)) {
    return (
      <span className='scenario-flow-badge scenario-flow-badge--amber'>
        <GitBranch className='size-3' />
        {(step.then?.length ?? 0) + (step.else?.length ?? 0)}
      </span>
    );
  }
  return null;
}

function AnchorNode({ data }: NodeProps<Node<AnchorNodeData>>) {
  return (
    <div className='scenario-anchor-node'>
      <Handle type='target' position={Position.Left} className='opacity-0' />
      <span className='scenario-anchor-node__icon'>
        <Workflow className='size-3.5' />
      </span>
      <div className='min-w-0'>
        <div className='truncate text-xs font-semibold text-foreground'>
          {data.title}
        </div>
        <div className='truncate text-[10px] text-muted-foreground'>
          {data.subtitle}
        </div>
      </div>
      <Handle type='source' position={Position.Right} className='opacity-0' />
    </div>
  );
}

function FrameNode({ data }: NodeProps<Node<FrameNodeData>>) {
  return (
    <div className={cn('scenario-lane', `scenario-lane--${data.tone}`)}>
      <div className='scenario-lane__header'>
        <span className='scenario-lane__dot' />
        <span className='scenario-lane__title'>{data.title}</span>
        <span className='scenario-lane__subtitle'>{data.subtitle}</span>
      </div>
    </div>
  );
}

function PlaceholderNode({ data }: NodeProps<Node<PlaceholderNodeData>>) {
  const dropActive =
    data.dropTargetKey ===
    dropTargetKey({ scope: data.scope, afterNodeId: null });
  return (
    <div
      className={cn(
        'scenario-placeholder-node',
        dropActive && 'scenario-placeholder-node--drop-target'
      )}
    >
      <Handle type='target' position={Position.Left} className='opacity-0' />
      <StepTypeMenu
        align='center'
        label={data.label}
        onAdd={(type) => data.onInsert(data.scope, null, type)}
      />
      <Handle type='source' position={Position.Right} className='opacity-0' />
    </div>
  );
}

function JunctionNode() {
  return (
    <div className='scenario-junction-node'>
      <Handle type='target' position={Position.Left} className='opacity-0' />
      <Handle type='source' position={Position.Right} className='opacity-0' />
    </div>
  );
}

function ScenarioNode({ data }: NodeProps<Node<ScenarioNodeData>>) {
  const { step } = data;
  const display = getStepDisplay(step);
  const title = formatStepLabelForCard(getStepTypeName(step.type));
  const selected = data.selectedNodeId === data.nodeId;
  const dragging = data.dragSourceNodeId === data.nodeId;
  const dropBefore =
    data.dropTargetKey ===
    dropTargetKey({
      scope: data.scope,
      afterNodeId: data.previousNodeId
    });
  const dropAfter =
    data.dropTargetKey ===
    dropTargetKey({ scope: data.scope, afterNodeId: data.nodeId });
  const category = getStepCategory(step.type);
  const canMoveBack = data.index > 0;
  const canMoveForward = data.index < data.siblingCount - 1;

  return (
    <div
      role='button'
      tabIndex={0}
      className={cn(
        'scenario-step-node',
        category === 'flow' && 'scenario-step-node--flow',
        selected && 'scenario-step-node--selected',
        dragging && 'scenario-step-node--dragging',
        dropBefore && 'scenario-step-node--drop-before',
        dropAfter && 'scenario-step-node--drop-after'
      )}
      onClick={() => data.onSelect(data.nodeId, step)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          data.onSelect(data.nodeId, step);
        }
      }}
    >
      <Handle type='target' position={Position.Left} />
      <span className='scenario-step-node__accent' />
      <span className='scenario-step-node__grip' aria-hidden='true'>
        <GripVertical className='size-3.5' />
      </span>
      <span className='scenario-step-node__icon'>
        <StepIcon type={step.type} size={16} />
      </span>
      <div className='min-w-0 flex-1'>
        <div className='flex min-w-0 items-center gap-1.5'>
          <span className='truncate text-[13px] font-semibold text-foreground'>
            {title}
          </span>
          <FlowBadge step={step} />
        </div>
        <div className='mt-0.5 truncate text-[11px] text-muted-foreground'>
          {display.target || 'Chọn để xem cấu hình'}
        </div>
      </div>
      <div className='scenario-node-toolbar nodrag nopan'>
        <button
          type='button'
          className='scenario-node-action'
          title='Đưa bước về trước'
          aria-label='Đưa bước về trước'
          disabled={!canMoveBack}
          onClick={(event) => {
            event.stopPropagation();
            data.onMove(data.nodeId, data.scope, data.moveBackAfterNodeId);
          }}
        >
          <ArrowLeft className='size-3.5' />
        </button>
        <button
          type='button'
          className='scenario-node-action'
          title='Đưa bước ra sau'
          aria-label='Đưa bước ra sau'
          disabled={!canMoveForward}
          onClick={(event) => {
            event.stopPropagation();
            data.onMove(data.nodeId, data.scope, data.moveForwardAfterNodeId);
          }}
        >
          <ArrowRight className='size-3.5' />
        </button>
        <StepTypeMenu
          iconOnly
          label='Thêm bước sau node này'
          onAdd={(type) => data.onInsert(data.scope, data.nodeId, type)}
        />
      </div>
      <Handle type='source' position={Position.Right} />
    </div>
  );
}

function ScenarioEdge({
  id,
  data,
  markerEnd,
  label
}: EdgeProps<AutomationEdge>) {
  const points = data?.points ?? [];
  if (points.length < 2) return null;
  const edgePath = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
    .join(' ');
  const middle = points[Math.floor(points.length / 2)];

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        className='scenario-edge-path'
      />
      {label && middle ? (
        <EdgeLabelRenderer>
          <div
            className='scenario-edge-label nodrag nopan'
            style={{
              transform: `translate(-50%, -50%) translate(${middle.x}px,${middle.y}px)`
            }}
          >
            {String(label)}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

const nodeTypes: NodeTypes = {
  anchor: AnchorNode,
  frame: FrameNode,
  placeholder: PlaceholderNode,
  junction: JunctionNode,
  scenario: ScenarioNode
};

const edgeTypes = { scenario: ScenarioEdge };

function toAutomationGraph(
  layoutNodes: ScenarioLayoutNode[],
  layoutEdges: ScenarioLayoutEdge[],
  callbacks: ScenarioNodeCallbacks
): { nodes: AutomationNode[]; edges: AutomationEdge[] } {
  const nodes = layoutNodes.map((node): AutomationNode => {
    const common = {
      id: node.id,
      position: node.position,
      draggable: node.kind === 'step',
      connectable: false,
      deletable: false,
      focusable: node.kind === 'step',
      style: { width: node.width, height: node.height }
    };

    if (node.kind === 'step') {
      return {
        ...common,
        type: 'scenario',
        zIndex: 3,
        data: {
          kind: 'step',
          nodeId: node.nodeId!,
          scope: node.scope ?? null,
          index: node.index!,
          siblingCount: node.siblingCount!,
          previousNodeId: node.previousNodeId ?? null,
          moveBackAfterNodeId: node.moveBackAfterNodeId ?? null,
          moveForwardAfterNodeId: node.moveForwardAfterNodeId ?? null,
          step: node.step!,
          ...callbacks
        }
      };
    }
    if (node.kind === 'frame') {
      return {
        ...common,
        type: 'frame',
        selectable: false,
        focusable: false,
        zIndex: 0,
        data: {
          kind: 'frame',
          title: node.title!,
          subtitle: node.subtitle!,
          tone: node.tone!
        }
      };
    }
    if (node.kind === 'placeholder') {
      return {
        ...common,
        type: 'placeholder',
        zIndex: 3,
        data: {
          kind: 'placeholder',
          scope: node.scope ?? null,
          label: node.label!,
          dropTargetKey: callbacks.dropTargetKey,
          onInsert: callbacks.onInsert
        }
      };
    }
    if (node.kind === 'junction') {
      return {
        ...common,
        type: 'junction',
        selectable: false,
        focusable: false,
        zIndex: 2,
        data: { kind: 'junction' }
      };
    }
    return {
      ...common,
      type: 'anchor',
      selectable: false,
      focusable: false,
      zIndex: 3,
      data: {
        kind: 'anchor',
        title: node.title!,
        subtitle: node.subtitle!
      }
    };
  });

  const edges = layoutEdges.map(
    (edge): AutomationEdge => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      type: 'scenario',
      animated: false,
      selectable: false,
      focusable: false,
      markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' },
      data: { points: edge.points }
    })
  );

  return { nodes, edges };
}

function resolveDropTarget(
  draggedNode: AutomationNode,
  nodes: AutomationNode[]
): DropTarget | null {
  if (draggedNode.data.kind !== 'step') return null;
  const draggedWidth =
    typeof draggedNode.width === 'number'
      ? draggedNode.width
      : Number(draggedNode.style?.width) || 0;
  const draggedHeight =
    typeof draggedNode.height === 'number'
      ? draggedNode.height
      : Number(draggedNode.style?.height) || 0;
  const center = {
    x: draggedNode.position.x + draggedWidth / 2,
    y: draggedNode.position.y + draggedHeight / 2
  };
  let closest: { target: DropTarget; distance: number } | undefined;

  for (const node of nodes) {
    if (node.id === draggedNode.id) continue;
    if (node.data.kind !== 'step' && node.data.kind !== 'placeholder') continue;
    const width =
      typeof node.width === 'number'
        ? node.width
        : Number(node.style?.width) || 0;
    const height =
      typeof node.height === 'number'
        ? node.height
        : Number(node.style?.height) || 0;
    const nodeCenter = {
      x: node.position.x + width / 2,
      y: node.position.y + height / 2
    };
    const distance = Math.hypot(
      center.x - nodeCenter.x,
      center.y - nodeCenter.y
    );
    if (distance > Math.max(180, width * 0.85)) continue;

    const target =
      node.data.kind === 'placeholder'
        ? {
            scope: node.data.scope,
            afterNodeId: null
          }
        : {
            scope: node.data.scope,
            afterNodeId:
              center.x < nodeCenter.x
                ? node.data.previousNodeId
                : node.data.nodeId
          };
    if (!closest || distance < closest.distance) closest = { target, distance };
  }

  return closest?.target ?? null;
}

function ScenarioAutomationCanvas({
  nodes,
  edges,
  selectedNodeId,
  onSelect,
  onInsert,
  onMove
}: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  selectedNodeId: string | null;
  onSelect: ScenarioNodeCallbacks['onSelect'];
  onInsert: ScenarioNodeCallbacks['onInsert'];
  onMove: ScenarioNodeCallbacks['onMove'];
}) {
  const t = useTranslations('devicesControlRecord.view.flowMap');
  const total = useMemo(() => countScenarioSteps(nodes), [nodes]);
  const [dragSourceNodeId, setDragSourceNodeId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  const currentDropTargetKey = dropTargetKey(dropTarget);
  const callbacks = useMemo<ScenarioNodeCallbacks>(
    () => ({
      selectedNodeId,
      dragSourceNodeId,
      dropTargetKey: currentDropTargetKey,
      onSelect,
      onInsert,
      onMove
    }),
    [
      selectedNodeId,
      dragSourceNodeId,
      currentDropTargetKey,
      onSelect,
      onInsert,
      onMove
    ]
  );
  const callbacksRef = useRef(callbacks);
  callbacksRef.current = callbacks;
  const requestRef = useRef(0);
  const flowRef = useRef<ReactFlowInstance<
    AutomationNode,
    AutomationEdge
  > | null>(null);
  const [graph, setGraph] = useState<{
    nodes: AutomationNode[];
    edges: AutomationEdge[];
  }>({ nodes: [], edges: [] });
  const [layoutPending, setLayoutPending] = useState(true);
  const initialFitDoneRef = useRef(false);
  const pendingFocusNodeIdRef = useRef<string | null>(null);
  const dragOriginRef = useRef<{
    id: string;
    position: { x: number; y: number };
  } | null>(null);

  const fitScenario = useCallback(() => {
    void flowRef.current?.fitView({ padding: 0.12, maxZoom: 1 });
  }, []);

  useEffect(() => {
    let active = true;
    const request = ++requestRef.current;
    setLayoutPending(true);

    layoutScenarioAutomation(nodes, edges)
      .then((layout) => {
        if (!active || request !== requestRef.current) return;
        setGraph(
          toAutomationGraph(layout.nodes, layout.edges, callbacksRef.current)
        );
        setLayoutPending(false);
        window.setTimeout(() => {
          if (!active || request !== requestRef.current) return;
          const focusNodeId = pendingFocusNodeIdRef.current;
          if (focusNodeId) {
            pendingFocusNodeIdRef.current = null;
            const focusNode = flowRef.current?.getNode(focusNodeId);
            if (focusNode) {
              void flowRef.current?.setCenter(
                focusNode.position.x + (focusNode.measured?.width ?? 232) / 2,
                focusNode.position.y + (focusNode.measured?.height ?? 64) / 2,
                {
                  zoom: Math.max(flowRef.current.getZoom(), 0.72),
                  duration: 280
                }
              );
              return;
            }
          }
          if (!initialFitDoneRef.current) {
            initialFitDoneRef.current = true;
            fitScenario();
          }
        }, 40);
      })
      .catch((error) => {
        if (!active || request !== requestRef.current) return;
        console.error('Scenario automation layout failed', error);
        setLayoutPending(false);
      });

    return () => {
      active = false;
    };
  }, [nodes, edges, fitScenario]);

  useEffect(() => {
    setGraph((current) => ({
      ...current,
      nodes: current.nodes.map((node) => {
        if (node.data.kind === 'step') {
          return { ...node, data: { ...node.data, ...callbacks } };
        }
        if (node.data.kind === 'placeholder') {
          return {
            ...node,
            data: {
              ...node.data,
              dropTargetKey: callbacks.dropTargetKey,
              onInsert: callbacks.onInsert
            }
          };
        }
        return node;
      })
    }));
  }, [callbacks]);

  return (
    <div className='flex h-full min-h-0 flex-col overflow-hidden bg-background'>
      <div className='scenario-map-header'>
        <span className='scenario-map-header__icon'>
          <Workflow className='size-4' />
        </span>
        <div className='min-w-0'>
          <div className='truncate text-sm font-semibold text-foreground'>
            {t('title')}
          </div>
          <div className='truncate text-[11px] text-muted-foreground'>
            {t('stepCount', { count: total })}
          </div>
        </div>
        {layoutPending ? (
          <span className='ml-1 inline-flex items-center gap-1 text-[10px] text-muted-foreground'>
            <Loader2 className='size-3 animate-spin' />
            {t('arranging')}
          </span>
        ) : null}
        <div className='hidden min-w-0 flex-1 items-center justify-end gap-1.5 text-[10px] text-muted-foreground xl:flex'>
          <GripVertical className='size-3' />
          <span className='truncate'>{t('dragHint')}</span>
        </div>
        <button
          type='button'
          className='scenario-map-fit-button'
          title={t('fitView')}
          aria-label={t('fitView')}
          onClick={fitScenario}
        >
          <Maximize2 className='size-3.5' />
          <span className='hidden 2xl:inline'>{t('fitView')}</span>
        </button>
        <StepTypeMenu
          align='right'
          label={t('addToEnd')}
          onAdd={(type) =>
            onInsert(
              null,
              getOrderedScopeNodes(nodes, null).at(-1)?.id ?? null,
              type
            )
          }
        />
      </div>
      <div className='relative min-h-0 flex-1'>
        <ReactFlow<AutomationNode, AutomationEdge>
          className='scenario-automation-flow'
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onInit={(instance) => {
            flowRef.current = instance;
          }}
          onNodesChange={(changes) => {
            if (!changes.some((change) => change.type === 'position')) return;
            setGraph((current) => ({
              ...current,
              nodes: applyNodeChanges(changes, current.nodes)
            }));
          }}
          onNodeDragStart={(_, node) => {
            if (node.data.kind !== 'step') return;
            dragOriginRef.current = {
              id: node.id,
              position: { ...node.position }
            };
            setDragSourceNodeId(node.data.nodeId);
            setDropTarget(null);
            onSelect(node.data.nodeId, node.data.step);
          }}
          onNodeDrag={(_, node) => {
            setDropTarget(resolveDropTarget(node, graph.nodes));
          }}
          onNodeDragStop={(_, node) => {
            const sourceNodeId =
              node.data.kind === 'step' ? node.data.nodeId : null;
            const target = resolveDropTarget(node, graph.nodes) ?? dropTarget;
            const origin = dragOriginRef.current;
            dragOriginRef.current = null;
            setDragSourceNodeId(null);
            setDropTarget(null);
            if (!sourceNodeId || !target) {
              if (origin?.id === node.id) {
                setGraph((current) => ({
                  ...current,
                  nodes: current.nodes.map((currentNode) =>
                    currentNode.id === node.id
                      ? { ...currentNode, position: origin.position }
                      : currentNode
                  )
                }));
              }
              return;
            }
            const moved = onMove(
              sourceNodeId,
              target.scope,
              target.afterNodeId
            );
            if (moved) {
              pendingFocusNodeIdRef.current = sourceNodeId;
              return;
            }
            if (origin?.id === node.id) {
              setGraph((current) => ({
                ...current,
                nodes: current.nodes.map((currentNode) =>
                  currentNode.id === node.id
                    ? { ...currentNode, position: origin.position }
                    : currentNode
                )
              }));
            }
          }}
          nodesDraggable
          nodesConnectable={false}
          elementsSelectable
          edgesFocusable={false}
          edgesReconnectable={false}
          minZoom={0.4}
          maxZoom={1.5}
          panOnScroll
          selectionOnDrag={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={22} size={1} color='var(--scenario-map-grid)' />
          <Controls position='bottom-right' showInteractive={false} />
          {total > 10 ? (
            <MiniMap
              position='bottom-left'
              pannable
              zoomable
              nodeStrokeWidth={2}
              nodeColor={(node) => {
                const automationNode = node as AutomationNode;
                if (automationNode.data.kind === 'anchor') return '#bfdbfe';
                if (automationNode.data.kind === 'frame') return '#e2e8f0';
                if (
                  automationNode.data.kind === 'step' &&
                  getStepCategory(automationNode.data.step.type) === 'flow'
                ) {
                  return '#fcd34d';
                }
                return '#93c5fd';
              }}
              maskColor='var(--scenario-map-minimap-mask)'
            />
          ) : null}
        </ReactFlow>
        {layoutPending && graph.nodes.length === 0 ? (
          <div className='scenario-layout-empty'>
            <Loader2 className='size-4 animate-spin' />
            {t('building')}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ScenarioAutomationMap(props: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  selectedNodeId: string | null;
  onSelect: (nodeId: string, step: FlowStep) => void;
  onInsert: ScenarioNodeCallbacks['onInsert'];
  onMove: ScenarioNodeCallbacks['onMove'];
}) {
  return (
    <ReactFlowProvider>
      <ScenarioAutomationCanvas {...props} />
    </ReactFlowProvider>
  );
}
