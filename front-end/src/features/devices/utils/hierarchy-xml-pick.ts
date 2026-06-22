import type { ScenarioSelectorShape } from '../lib/scenario-selector-step';
import { enrichSelectorFromNode } from './enrich-selector-from-xml';
import {
  inferForegroundPackage,
  hierarchyRatioToPoint,
  isHierarchyLayoutContainer,
  isSystemUiPackage,
  pickStableHierarchySelector,
  scoreHierarchyHit
} from './hierarchy-hit-test';

export { inferForegroundPackage };

type XmlSelectorPickBy =
  | 'resource-id'
  | 'text'
  | 'description'
  | 'descriptionStartsWith'
  | 'xpath'
  | 'class name';

export type XmlSelectorPick = {
  by: XmlSelectorPickBy;
  value: string;
  selector: ScenarioSelectorShape;
  selectorReason?: string;
  selectorVolatile?: boolean;
  resourceIdDuplicateCount?: number;
  textDuplicateCount?: number;
  descDuplicateCount?: number;
  bounds?: {
    left: number;
    top: number;
    right: number;
    bottom: number;
    rx1: number;
    ry1: number;
    rx2: number;
    ry2: number;
  };
};

export type HierarchyPickOptions = {
  /** Restrict candidates to this package (e.g. device.current_app). Falls back to non-systemUI nodes when no match. */
  targetPackage?: string | null;
  /** Mirror tap ratios are in device screen space — may differ from max hierarchy bounds (nav bar). */
  screenDims?: { dw: number; dh: number } | null;
};

const BOUNDS_RE = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/;

/** FB group page shells embed feed inside a row whose content-desc is the group header. */
const FB_GROUP_HEADER_DESC_RE =
  /\b(thành viên|members|Công khai|Public|Nhóm công khai|private group|Private)\b/i;

function isFbGroupHeaderDescription(desc: string): boolean {
  return FB_GROUP_HEADER_DESC_RE.test(desc.trim());
}

function nodeBoundsArea(n: Element): number {
  const m = BOUNDS_RE.exec(n.getAttribute('bounds') ?? '');
  if (!m) return 0;
  const w = +m[3] - +m[1];
  const h = +m[4] - +m[2];
  return w > 0 && h > 0 ? w * h : 0;
}

type RankedCandidate = {
  node: Element;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  area: number;
  clickable: boolean;
  depth: number;
};

type Sel = {
  by: 'resource-id' | 'text' | 'description' | 'xpath' | 'class name';
  value: string;
  selectorReason?: string;
  selectorVolatile?: boolean;
  resourceIdDuplicateCount?: number;
  textDuplicateCount?: number;
  descDuplicateCount?: number;
};

/**
 * Rank every node whose bounds contain (rx,ry) into selector picks, best first.
 *
 * FB-safe picking:
 *   1. Drop system UI chrome; keep the foreground app package.
 *   2. Prefer deep semantic nodes (content-desc / text) over layout shells.
 *   3. Build the selector from the deepest semantic anchor, not a shallow ancestor.
 *
 * Returns distinct selectors (deduped by by+value) so the UI can cycle through
 * overlapping elements at the same tap point.
 */
export function listSelectorCandidatesInXml(
  xmlStr: string,
  rx: number,
  ry: number,
  options?: HierarchyPickOptions
): XmlSelectorPick[] {
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xmlStr, 'text/xml');
  } catch {
    return [];
  }

  const allNodes = Array.from(doc.getElementsByTagName('node'));
  const screenDims =
    options?.screenDims &&
    options.screenDims.dw > 0 &&
    options.screenDims.dh > 0
      ? options.screenDims
      : undefined;
  const { px, py, dw, dh } = hierarchyRatioToPoint(allNodes, rx, ry, {
    screenDims
  });

  const ridCount = new Map<string, number>();
  const textCount = new Map<string, number>();
  const descCount = new Map<string, number>();
  for (const node of allNodes) {
    const rid = (node.getAttribute('resource-id') ?? '').trim();
    const txt = (node.getAttribute('text') ?? '').trim();
    const d = (node.getAttribute('content-desc') ?? '').trim();
    if (rid) ridCount.set(rid, (ridCount.get(rid) ?? 0) + 1);
    if (txt) textCount.set(txt, (textCount.get(txt) ?? 0) + 1);
    if (d) descCount.set(d, (descCount.get(d) ?? 0) + 1);
  }

  const parentOf = new Map<Element, Element | null>();
  for (const n of allNodes) {
    const p = n.parentElement;
    parentOf.set(n, p && p.tagName === 'node' ? p : null);
  }

  const nodeDepth = (n: Element): number => {
    let depth = 0;
    let cur: Element | null = parentOf.get(n) ?? null;
    while (cur) {
      depth += 1;
      cur = parentOf.get(cur) ?? null;
    }
    return depth;
  };

  const scoreCandidate = (c: RankedCandidate): number =>
    scoreHierarchyHit({
      depth: c.depth,
      area: c.area,
      clickable: c.clickable,
      text: (c.node.getAttribute('text') ?? '').trim(),
      contentDesc: (c.node.getAttribute('content-desc') ?? '').trim(),
      resourceId: (c.node.getAttribute('resource-id') ?? '').trim(),
      className: (c.node.getAttribute('class') ?? '').trim(),
      resourceIdCount: ridCount.get(
        (c.node.getAttribute('resource-id') ?? '').trim()
      )
    });

  const tryPrimaryOnNode = (n: Element): Sel | null => {
    return pickStableHierarchySelector(
      {
        resourceId: n.getAttribute('resource-id') ?? '',
        text: n.getAttribute('text') ?? '',
        contentDesc: n.getAttribute('content-desc') ?? '',
        pkg: n.getAttribute('package') ?? '',
        className: n.getAttribute('class') ?? '',
        bounds: n.getAttribute('bounds') ?? ''
      },
      {
        resourceIdCount: ridCount.get(
          (n.getAttribute('resource-id') ?? '').trim()
        ),
        textCount: textCount.get((n.getAttribute('text') ?? '').trim()),
        descCount: descCount.get((n.getAttribute('content-desc') ?? '').trim())
      },
      { allowBoundsXPath: false }
    );
  };

  const scoreSelectorAnchor = (n: Element, sel: Sel): number => {
    let score = nodeDepth(n) * 600;
    if (sel.by === 'description') score += 3000;
    if (sel.by === 'text') score += 2500;
    if (sel.by === 'resource-id') score += 800;
    if (sel.by === 'class name') score -= 2000;
    if (sel.by === 'xpath') score -= 5000;
    const cls = (n.getAttribute('class') ?? '').trim();
    if (isHierarchyLayoutContainer(cls)) score -= 4000;
    return score;
  };

  const pickBestSemanticInSubtree = (
    root: Element
  ): { sel: Sel; anchor: Element } | null => {
    const nodes: Element[] = [];
    const walk = (el: Element) => {
      nodes.push(el);
      for (let i = 0; i < el.children.length; i++) {
        const ch = el.children[i];
        if (ch.tagName === 'node') walk(ch);
      }
    };
    walk(root);
    let best: { sel: Sel; anchor: Element; score: number } | null = null;
    for (const n of nodes) {
      const s = tryPrimaryOnNode(n);
      if (!s || s.by === 'xpath' || s.by === 'class name') continue;
      if (s.by === 'description') {
        const desc = (n.getAttribute('content-desc') ?? '').trim();
        if (isFbGroupHeaderDescription(desc)) continue;
      }
      const score = scoreSelectorAnchor(n, s);
      if (!best || score > best.score) {
        best = { sel: s, anchor: n, score };
      }
    }
    return best ? { sel: best.sel, anchor: best.anchor } : null;
  };

  const isListContainerClass = (cls: string): boolean =>
    /RecyclerView|ListView|GridView|ViewPager/i.test(cls);

  const nodeAttrs = (n: Element) => ({
    resourceId: n.getAttribute('resource-id') ?? '',
    text: n.getAttribute('text') ?? '',
    contentDesc: n.getAttribute('content-desc') ?? '',
    pkg: n.getAttribute('package') ?? '',
    className: n.getAttribute('class') ?? '',
    bounds: n.getAttribute('bounds') ?? ''
  });

  const nodeCounts = (n: Element) => ({
    resourceIdCount: ridCount.get((n.getAttribute('resource-id') ?? '').trim()),
    textCount: textCount.get((n.getAttribute('text') ?? '').trim()),
    descCount: descCount.get((n.getAttribute('content-desc') ?? '').trim())
  });

  const pickPrimaryForNode = (
    start: Element
  ): { sel: Sel; anchor: Element } | null => {
    const ordered: Element[] = [];
    const walkDesc = (el: Element) => {
      ordered.push(el);
      for (let i = 0; i < el.children.length; i++) {
        const ch = el.children[i];
        if (ch.tagName === 'node') walkDesc(ch);
      }
    };
    walkDesc(start);
    let cur: Element | null = parentOf.get(start) ?? null;
    while (cur) {
      ordered.push(cur);
      cur = parentOf.get(cur) ?? null;
    }

    let best: { sel: Sel; anchor: Element; score: number } | null = null;
    const startArea = nodeBoundsArea(start);
    for (const n of ordered) {
      const s = tryPrimaryOnNode(n);
      if (!s || s.by === 'xpath' || s.by === 'class name') continue;
      if (n !== start && s.by === 'description') {
        const desc = (n.getAttribute('content-desc') ?? '').trim();
        const area = nodeBoundsArea(n);
        if (
          isFbGroupHeaderDescription(desc) &&
          startArea > 0 &&
          area > startArea * 2
        ) {
          continue;
        }
      }
      const score = scoreSelectorAnchor(n, s);
      if (!best || score > best.score) {
        best = { sel: s, anchor: n, score };
      }
    }
    if (best) return { sel: best.sel, anchor: best.anchor };

    const startClassName = (start.getAttribute('class') ?? '').trim();
    if (!isHierarchyLayoutContainer(startClassName)) {
      const localFallback = pickStableHierarchySelector(
        nodeAttrs(start),
        nodeCounts(start),
        { allowBoundsXPath: true }
      );
      if (localFallback && localFallback.by !== 'class name') {
        return { sel: localFallback, anchor: start };
      }
    }

    // FB list rows: when the tapped node is a selector-poor shell, scan the row
    // container for a unique semantic anchor. Do this after local search so an
    // explicit tapped action is not replaced by a sibling title/description.
    const parent = parentOf.get(start) ?? null;
    if (parent) {
      const parentCls = (parent.getAttribute('class') ?? '').trim();
      if (!isListContainerClass(parentCls)) {
        const rowPick = pickBestSemanticInSubtree(parent);
        if (rowPick) return rowPick;
      }
    }

    const fallback = pickStableHierarchySelector(
      nodeAttrs(start),
      nodeCounts(start),
      { allowBoundsXPath: false }
    );
    if (fallback && fallback.by !== 'xpath' && fallback.by !== 'class name') {
      return { sel: fallback, anchor: start };
    }
    return null;
  };

  const collectHits = (packageFilter: string | null): RankedCandidate[] => {
    const hits: RankedCandidate[] = [];
    for (const node of allNodes) {
      const pkg = (node.getAttribute('package') ?? '').trim();
      if (isSystemUiPackage(pkg)) continue;
      if (packageFilter && pkg !== packageFilter) continue;
      const m = BOUNDS_RE.exec(node.getAttribute('bounds') ?? '');
      if (!m) continue;
      const [x1, y1, x2, y2] = [+m[1], +m[2], +m[3], +m[4]];
      if (!(x1 <= px && px <= x2 && y1 <= py && py <= y2)) continue;
      if (node.getAttribute('enabled') === 'false') continue;
      if (x2 <= x1 || y2 <= y1) continue;
      hits.push({
        node,
        x1,
        y1,
        x2,
        y2,
        area: (x2 - x1) * (y2 - y1),
        clickable: node.getAttribute('clickable') === 'true',
        depth: nodeDepth(node)
      });
    }
    return hits;
  };

  const effectivePackage =
    (options?.targetPackage ?? '').trim() || inferForegroundPackage(allNodes);

  // Strict package filter first; fall back to all non-systemUI nodes when the
  // target package (often a stale current_app) has nothing under the tap.
  let hits = effectivePackage
    ? collectHits(effectivePackage)
    : collectHits(null);
  if (hits.length === 0) hits = collectHits(null);
  if (hits.length === 0) return [];

  hits.sort((a, b) => scoreCandidate(b) - scoreCandidate(a));

  const picks: XmlSelectorPick[] = [];
  const seen = new Set<string>();
  for (const hit of hits) {
    const picked = pickPrimaryForNode(hit.node);
    if (!picked) continue;
    const { sel, anchor } = picked;
    const dedupeKey = `${sel.by}::${sel.value}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    const selector = enrichSelectorFromNode(anchor, sel, allNodes);
    picks.push({
      by: sel.by,
      value: sel.value,
      selector,
      selectorReason: sel.selectorReason,
      selectorVolatile: sel.selectorVolatile,
      resourceIdDuplicateCount: sel.resourceIdDuplicateCount,
      textDuplicateCount: sel.textDuplicateCount,
      descDuplicateCount: sel.descDuplicateCount,
      bounds: {
        left: hit.x1,
        top: hit.y1,
        right: hit.x2,
        bottom: hit.y2,
        rx1: hit.x1 / dw,
        ry1: hit.y1 / dh,
        rx2: hit.x2 / dw,
        ry2: hit.y2 / dh
      }
    });
    if (picks.length >= 8) break;
  }
  return picks;
}

/**
 * Parse XML, find the single best element at (rx,ry).
 * Thin wrapper over {@link listSelectorCandidatesInXml} for callers that only
 * need the top result (recording, single pick).
 */
export function findSelectorInXml(
  xmlStr: string,
  rx: number,
  ry: number,
  options?: HierarchyPickOptions
): XmlSelectorPick | null {
  const pick = listSelectorCandidatesInXml(xmlStr, rx, ry, options)[0] ?? null;
  return pick;
}

/** FB list rows: prefer descriptionStartsWith on group name (scroll-safe). */
export function stabilizeListRowSelector(
  pick: XmlSelectorPick
): XmlSelectorPick {
  if (pick.by !== 'description') return pick;
  const value = pick.value.trim();
  if (!value) return pick;

  let prefix = '';
  const dotParts = value.split(/\s*[·•]\s*/);
  if (dotParts.length >= 2 && dotParts[0].trim().length >= 4) {
    prefix = dotParts[0].trim();
  } else {
    const comma = value.split(',')[0]?.trim() ?? '';
    if (comma.length >= 4 && comma.length < value.length) prefix = comma;
  }
  if (!prefix || prefix === value) return pick;

  return {
    ...pick,
    by: 'descriptionStartsWith',
    value: prefix,
    selector: {
      ...pick.selector,
      by: 'descriptionStartsWith',
      value: prefix
    }
  };
}
