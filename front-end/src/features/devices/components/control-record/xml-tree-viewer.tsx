'use client';

import React, { useCallback, useMemo, useState } from 'react';
import { HelpCircle } from 'lucide-react';
import {
  parseHierarchyTree,
  searchTree,
  bestSelector,
  type HierarchyTreeNode,
} from '../../utils/hierarchy-tree';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useTranslations } from 'next-intl';

interface XmlTreeViewerProps {
  xml: string;
  loading: boolean;
  onNodeSelect: (node: {
    bounds: [number, number, number, number] | null;
    by: string;
    value: string;
    nodeId: number;
  }) => void;
  selectedNodeId: number | null;
  onRefresh: () => void;
  autoRefresh: boolean;
  onAutoRefreshChange: (v: boolean) => void;
}

export function XmlTreeViewer({
  xml,
  loading,
  onNodeSelect,
  selectedNodeId,
  onRefresh,
  autoRefresh,
  onAutoRefreshChange,
}: XmlTreeViewerProps) {
  const t = useTranslations('devicesControlRecord.view');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const root = useMemo(() => parseHierarchyTree(xml), [xml]);

  // Auto-expand all nodes so the full tree is visible by default
  useMemo(() => {
    if (!root) return;
    const ids = new Set<number>();
    function collectAll(node: HierarchyTreeNode) {
      ids.add(node.id);
      node.children.forEach(collectAll);
    }
    collectAll(root);
    setExpanded(ids);
  }, [root]);

  const matchingIds = useMemo(
    () => (root && search ? searchTree(root, search) : null),
    [root, search],
  );

  const toggle = useCallback((id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleClick = useCallback(
    (node: HierarchyTreeNode) => {
      const sel = bestSelector(node);
      onNodeSelect({ bounds: node.bounds, ...sel, nodeId: node.id });
    },
    [onNodeSelect],
  );

  return (
    <div className='flex h-full flex-col'>
      {/* Header */}
      <div className='flex items-center gap-2 border-b border-border/60 bg-background/80 px-3 py-2'>
        <div className='flex items-center gap-1'>
          <span className='text-xs font-semibold text-foreground'>{t('hierarchyTitle')}</span>
          <Tooltip delayDuration={400}>
            <TooltipTrigger asChild>
              <button
                type='button'
                className='rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground'
                aria-label={t('tooltipHierarchyPanel')}
              >
                <HelpCircle className='size-3.5' />
              </button>
            </TooltipTrigger>
            <TooltipContent side='bottom' className='max-w-[min(100vw-2rem,22rem)] text-xs leading-relaxed'>
              {t('tooltipHierarchyPanel')}
            </TooltipContent>
          </Tooltip>
        </div>
        <div className='flex-1' />
        <label className='flex items-center gap-1 text-[10px] text-muted-foreground'>
          <input
            type='checkbox'
            checked={autoRefresh}
            onChange={(e) => onAutoRefreshChange(e.target.checked)}
            className='h-3 w-3'
          />
          Auto
        </label>
        <button
          onClick={onRefresh}
          disabled={loading}
          className='rounded bg-muted px-2 py-0.5 text-[10px] hover:bg-accent disabled:opacity-50'
        >
          {loading ? '...' : 'Refresh'}
        </button>
      </div>

      {/* Search */}
      <div className='border-b border-border px-3 py-1.5'>
        <input
          type='text'
          placeholder='Search text, resource-id, content-desc...'
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className='w-full rounded border border-border bg-background px-2 py-1 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring'
        />
      </div>

      {/* Tree */}
      <div className='flex-1 overflow-auto p-1 text-[11px] font-mono'>
        {!root ? (
          <div className='flex h-full items-center justify-center text-muted-foreground text-xs'>
            {loading ? 'Loading...' : 'No hierarchy data'}
          </div>
        ) : (
          <TreeNode
            node={root}
            expanded={expanded}
            matchingIds={matchingIds}
            selectedNodeId={selectedNodeId}
            onToggle={toggle}
            onClick={handleClick}
          />
        )}
      </div>
    </div>
  );
}


// ── Recursive tree node renderer ─────────────────────────────────────────

interface TreeNodeProps {
  node: HierarchyTreeNode;
  expanded: Set<number>;
  matchingIds: Set<number> | null;
  selectedNodeId: number | null;
  onToggle: (id: number) => void;
  onClick: (node: HierarchyTreeNode) => void;
}

function TreeNode({ node, expanded, matchingIds, selectedNodeId, onToggle, onClick }: TreeNodeProps) {
  // If searching and this node is not in matching set, hide it
  if (matchingIds && !matchingIds.has(node.id)) return null;

  const isExpanded = expanded.has(node.id);
  const hasChildren = node.children.length > 0;
  const isSelected = selectedNodeId === node.id;
  const indent = node.depth * 14;

  const label = node.className || node.tag;
  const resId = node.resourceId ? node.resourceId.split('/').pop() : '';
  const textValue = node.text || '';
  const contentDescValue = node.contentDesc || '';
  const rawText = textValue || contentDescValue;

  return (
    <>
      <div
        className={`flex cursor-pointer items-center gap-1 whitespace-nowrap rounded px-1 py-0.5 hover:bg-accent/50 ${
          isSelected ? 'bg-primary/15 ring-1 ring-primary/30' : ''
        }`}
        style={{ paddingLeft: indent + 4 }}
        onClick={() => onClick(node)}
      >
        {/* Expand/collapse toggle */}
        {hasChildren ? (
          <button
            onClick={(e) => { e.stopPropagation(); onToggle(node.id); }}
            className='flex h-4 w-4 flex-shrink-0 items-center justify-center text-muted-foreground hover:text-foreground'
          >
            {isExpanded ? '\u25BE' : '\u25B8'}
          </button>
        ) : (
          <span className='h-4 w-4 flex-shrink-0' />
        )}

        {/* Class name badge */}
        <span className={`flex-shrink-0 rounded px-1 text-[10px] ${
          node.clickable ? 'bg-blue-500/20 text-blue-600 dark:text-blue-400' : 'bg-muted text-muted-foreground'
        }`}>
          {label}
        </span>

        {/* Resource ID */}
        {resId && (
          <span className='shrink-0 text-[10px] text-emerald-600 dark:text-emerald-400' title={node.resourceId || resId}>
            {resId}
          </span>
        )}

        {/* Always show full text/content-desc (no truncation) */}
        {rawText && (
          <span className='shrink-0 text-[10px] text-orange-600 dark:text-orange-400' title={rawText}>
            &quot;{rawText}&quot;
          </span>
        )}

        {node.pkg && (
          <span className='shrink-0 text-[9px] text-violet-600/90 dark:text-violet-400/90' title={node.pkg}>
            {node.pkg}
          </span>
        )}
      </div>

      {/* Children */}
      {isExpanded && hasChildren && node.children.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          expanded={expanded}
          matchingIds={matchingIds}
          selectedNodeId={selectedNodeId}
          onToggle={onToggle}
          onClick={onClick}
        />
      ))}
    </>
  );
}
