'use client';

import React, {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import { HelpCircle, Loader2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  parseHierarchyTree,
  searchTree,
  bestSelector,
  filterSystemUiFromTree,
  type HierarchyTreeNode
} from '../../utils/hierarchy-tree';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { useTranslations } from 'next-intl';

interface XmlTreeViewerProps {
  xml: string;
  loading: boolean;
  deviceActive?: boolean;
  wsConnected?: boolean;
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

function xmlTreeViewerPropsEqual(
  prev: XmlTreeViewerProps,
  next: XmlTreeViewerProps
) {
  return (
    prev.xml === next.xml &&
    prev.loading === next.loading &&
    prev.deviceActive === next.deviceActive &&
    prev.wsConnected === next.wsConnected &&
    prev.selectedNodeId === next.selectedNodeId &&
    prev.autoRefresh === next.autoRefresh &&
    prev.onNodeSelect === next.onNodeSelect &&
    prev.onRefresh === next.onRefresh &&
    prev.onAutoRefreshChange === next.onAutoRefreshChange
  );
}

function XmlTreeViewerInner({
  xml,
  loading,
  deviceActive = true,
  wsConnected = true,
  onNodeSelect,
  selectedNodeId,
  onRefresh,
  autoRefresh,
  onAutoRefreshChange
}: XmlTreeViewerProps) {
  const t = useTranslations('devicesControlRecord.view');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [hideSystemUi, setHideSystemUi] = useState(true);
  const lastExpandSigRef = useRef('');

  useEffect(() => {
    const tid = window.setTimeout(() => setDebouncedSearch(search), 150);
    return () => window.clearTimeout(tid);
  }, [search]);

  const root = useMemo(() => {
    const parsed = parseHierarchyTree(xml);
    return hideSystemUi ? filterSystemUiFromTree(parsed) : parsed;
  }, [xml, hideSystemUi]);

  // Auto-expand all nodes when hierarchy changes. Schedule via idle callback so
  // the first paint is not blocked on large XML (Facebook feed).
  useEffect(() => {
    if (!root) {
      setExpanded(new Set());
      return;
    }
    const sig = `${xml.length}:${xml.slice(0, 96)}:hide=${hideSystemUi}`;
    if (lastExpandSigRef.current === sig) return;
    lastExpandSigRef.current = sig;

    const ids = new Set<number>();
    function collectAll(node: HierarchyTreeNode) {
      ids.add(node.id);
      node.children.forEach(collectAll);
    }
    collectAll(root);

    let cancelled = false;
    const apply = () => {
      if (!cancelled) setExpanded(ids);
    };
    let idleId: number | undefined;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    if (typeof requestIdleCallback !== 'undefined') {
      idleId = requestIdleCallback(apply, { timeout: 400 });
    } else {
      timeoutId = setTimeout(apply, 0);
    }
    return () => {
      cancelled = true;
      if (idleId !== undefined && typeof cancelIdleCallback !== 'undefined') {
        cancelIdleCallback(idleId);
      }
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [root, xml, hideSystemUi]);

  const matchingIds = useMemo(
    () => (root && debouncedSearch ? searchTree(root, debouncedSearch) : null),
    [root, debouncedSearch]
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
    [onNodeSelect]
  );

  return (
    <div className='flex h-full flex-col'>
      {/* Header — two rows so controls fit the 280px hierarchy column */}
      <div className='shrink-0 border-b border-border/60 bg-muted/20'>
        <div className='flex items-center gap-1 px-2.5 pb-1 pt-2'>
          <span className='min-w-0 flex-1 truncate text-xs font-semibold leading-tight text-foreground'>
            {t('hierarchyTitle')}
          </span>
          <Tooltip delayDuration={400}>
            <TooltipTrigger asChild>
              <button
                type='button'
                className='shrink-0 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground'
                aria-label={t('tooltipHierarchyPanel')}
              >
                <HelpCircle className='size-3.5' />
              </button>
            </TooltipTrigger>
            <TooltipContent
              side='bottom'
              className='max-w-[min(100vw-2rem,22rem)] text-xs leading-relaxed'
            >
              {t('tooltipHierarchyPanel')}
            </TooltipContent>
          </Tooltip>
          <Button
            type='button'
            variant='outline'
            size='sm'
            className='h-6 shrink-0 gap-1 px-2 text-[11px]'
            onClick={onRefresh}
            disabled={loading}
          >
            {loading ? (
              <Loader2 className='size-3 shrink-0 animate-spin' aria-hidden />
            ) : (
              <RefreshCw className='size-3 shrink-0' aria-hidden />
            )}
            <span className='whitespace-nowrap'>{t('refreshHierarchy')}</span>
          </Button>
        </div>
        <div className='flex items-center justify-between gap-2 border-t border-border/40 px-2.5 py-1.5'>
          <div className='flex items-center gap-1.5'>
            <Switch
              id='hierarchy-hide-system'
              checked={hideSystemUi}
              onCheckedChange={setHideSystemUi}
              className='scale-[0.85]'
            />
            <Label
              htmlFor='hierarchy-hide-system'
              className='cursor-pointer whitespace-nowrap text-[11px] font-normal leading-none text-muted-foreground'
            >
              {t('hideSystemUiShort')}
            </Label>
          </div>
          <div className='flex items-center gap-1.5'>
            <Switch
              id='hierarchy-auto-refresh'
              checked={autoRefresh}
              onCheckedChange={onAutoRefreshChange}
              className='scale-[0.85]'
            />
            <Label
              htmlFor='hierarchy-auto-refresh'
              className='cursor-pointer whitespace-nowrap text-[11px] font-normal leading-none text-muted-foreground'
            >
              {t('autoShort')}
            </Label>
          </div>
        </div>
      </div>

      {/* Search */}
      <div className='border-b border-border px-3 py-1.5'>
        <input
          type='text'
          placeholder={t('hierarchySearchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className='w-full rounded border border-border bg-background px-2 py-1 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring'
        />
      </div>

      {/* Tree */}
      <div className='flex-1 overflow-auto p-1 font-mono text-[11px]'>
        {!root ? (
          <div className='flex h-full items-center justify-center text-xs text-muted-foreground'>
            {loading
              ? t('hierarchyLoading')
              : !deviceActive
                ? t('hierarchyOffline')
                : !wsConnected
                  ? t('hierarchyDisconnected')
                  : t('hierarchyEmpty')}
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

/** Re-render only when hierarchy data or selection props change — not on unrelated editor state. */
export const XmlTreeViewer = memo(XmlTreeViewerInner, xmlTreeViewerPropsEqual);

// ── Recursive tree node renderer ─────────────────────────────────────────

interface TreeNodeProps {
  node: HierarchyTreeNode;
  expanded: Set<number>;
  matchingIds: Set<number> | null;
  selectedNodeId: number | null;
  onToggle: (id: number) => void;
  onClick: (node: HierarchyTreeNode) => void;
}

function TreeNode({
  node,
  expanded,
  matchingIds,
  selectedNodeId,
  onToggle,
  onClick
}: TreeNodeProps) {
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
        className={`flex w-max min-w-full cursor-pointer items-center gap-1 whitespace-nowrap rounded px-1 py-0.5 hover:bg-accent/50 ${
          isSelected ? 'bg-primary/15 ring-1 ring-primary/30' : ''
        }`}
        style={{ paddingLeft: indent + 4 }}
        onClick={() => onClick(node)}
      >
        {/* Expand/collapse toggle */}
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggle(node.id);
            }}
            className='flex h-4 w-4 flex-shrink-0 items-center justify-center text-muted-foreground hover:text-foreground'
          >
            {isExpanded ? '\u25BE' : '\u25B8'}
          </button>
        ) : (
          <span className='h-4 w-4 flex-shrink-0' />
        )}

        {/* Class name badge */}
        <span
          className={`flex-shrink-0 rounded px-1 text-[10px] ${
            node.clickable
              ? 'bg-blue-500/20 text-blue-600 dark:text-blue-400'
              : 'bg-muted text-muted-foreground'
          }`}
        >
          {label}
        </span>

        {/* Resource ID */}
        {resId && (
          <span
            className='shrink-0 text-[10px] text-emerald-600 dark:text-emerald-400'
            title={node.resourceId || resId}
          >
            {resId}
          </span>
        )}

        {/* Always show full text/content-desc (no truncation) */}
        {rawText && (
          <span
            className='shrink-0 text-[10px] text-orange-600 dark:text-orange-400'
            title={rawText}
          >
            &quot;{rawText}&quot;
          </span>
        )}

        {node.pkg && (
          <span
            className='shrink-0 text-[9px] text-violet-600/90 dark:text-violet-400/90'
            title={node.pkg}
          >
            {node.pkg}
          </span>
        )}
      </div>

      {/* Children */}
      {isExpanded &&
        hasChildren &&
        node.children.map((child) => (
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
