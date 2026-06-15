import type { ScenarioSelectorShape } from '../lib/scenario-selector-step';
import { enrichSelectorFromNode } from './enrich-selector-from-xml';
import {
  inferForegroundPackage,
  isGenericHierarchyResourceId,
  isHierarchyLayoutContainer,
  isSystemUiPackage,
  scoreHierarchyHit
} from './hierarchy-hit-test';
import { isAmbiguousLauncherResourceId } from './hierarchy-tree';

export { inferForegroundPackage };

export type XmlSelectorPick = {
  by: 'resource-id' | 'text' | 'description' | 'xpath' | 'class name';
  value: string;
  selector: ScenarioSelectorShape;
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
};

const BOUNDS_RE = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/;

function parseScreenDims(allNodes: Element[]): { dw: number; dh: number } {
  let dw = 1080;
  let dh = 1920;
  for (const n of allNodes) {
    const m = /\[0,0\]\[(\d+),(\d+)\]/.exec(n.getAttribute('bounds') ?? '');
    if (m) {
      dw = parseInt(m[1], 10);
      dh = parseInt(m[2], 10);
      break;
    }
  }
  return { dw, dh };
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
  const { dw, dh } = parseScreenDims(allNodes);
  const px = rx * dw;
  const py = ry * dh;

  const ridCount = new Map<string, number>();
  const textCount = new Map<string, number>();
  const descCount = new Map<string, number>();
  for (const node of allNodes) {
    const rid = (node.getAttribute('resource-id') ?? '').trim();
    const txt = (node.getAttribute('text') ?? '').trim();
    const d = (node.getAttribute('content-desc') ?? '').trim();
    if (rid) ridCount.set(rid, (ridCount.get(rid) ?? 0) + 1);
    if (txt && txt.length < 80)
      textCount.set(txt, (textCount.get(txt) ?? 0) + 1);
    if (d && d.length < 80) descCount.set(d, (descCount.get(d) ?? 0) + 1);
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
    const rid = (n.getAttribute('resource-id') ?? '').trim();
    const desc = (n.getAttribute('content-desc') ?? '').trim();
    const text = (n.getAttribute('text') ?? '').trim();
    const pkg = (n.getAttribute('package') ?? '').trim();
    const ambiguousLauncher = rid
      ? isAmbiguousLauncherResourceId(rid, pkg)
      : false;
    const ridUnique =
      !!rid && !ambiguousLauncher && (ridCount.get(rid) ?? 0) === 1;
    const textUnique =
      !!text && text.length < 80 && (textCount.get(text) ?? 0) === 1;
    const descUnique =
      !!desc && desc.length < 80 && (descCount.get(desc) ?? 0) === 1;

    if (ambiguousLauncher && text && text.length < 120)
      return { by: 'text', value: text };
    if (ambiguousLauncher && desc && desc.length < 80)
      return { by: 'description', value: desc };
    if (ridUnique) return { by: 'resource-id', value: rid };
    if (descUnique) return { by: 'description', value: desc };
    if (textUnique) return { by: 'text', value: text };
    if (desc && desc.length < 120) return { by: 'description', value: desc };
    if (text && text.length < 80) return { by: 'text', value: text };
    if (
      rid &&
      rid.includes('/') &&
      !isGenericHierarchyResourceId(rid) &&
      !ambiguousLauncher
    ) {
      return { by: 'resource-id', value: rid };
    }
    return null;
  };

  const scoreSelectorAnchor = (n: Element, sel: Sel): number => {
    let score = nodeDepth(n) * 600;
    if (sel.by === 'description') score += 3000;
    if (sel.by === 'text') score += 2500;
    if (sel.by === 'resource-id') score += 800;
    if (sel.by === 'class name') score -= 2000;
    const cls = (n.getAttribute('class') ?? '').trim();
    if (isHierarchyLayoutContainer(cls)) score -= 4000;
    return score;
  };

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
    for (const n of ordered) {
      const s = tryPrimaryOnNode(n);
      if (!s) continue;
      const score = scoreSelectorAnchor(n, s);
      if (!best || score > best.score) {
        best = { sel: s, anchor: n, score };
      }
    }
    if (best) return { sel: best.sel, anchor: best.anchor };

    const cls = (start.getAttribute('class') ?? '').trim();
    if (cls && !isHierarchyLayoutContainer(cls)) {
      return { sel: { by: 'class name', value: cls }, anchor: start };
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
  let hits = effectivePackage ? collectHits(effectivePackage) : collectHits(null);
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
  return listSelectorCandidatesInXml(xmlStr, rx, ry, options)[0] ?? null;
}
