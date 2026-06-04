/**
 * hierarchy-tree.ts — Parse UI hierarchy XML into a tree structure for the XML tree viewer.
 */

export interface HierarchyTreeNode {
  id: number;
  tag: string;
  className: string;
  resourceId: string;
  text: string;
  contentDesc: string;
  pkg: string;
  bounds: [number, number, number, number] | null; // [x1, y1, x2, y2]
  clickable: boolean;
  children: HierarchyTreeNode[];
  depth: number;
}

let _nextId = 0;

function parseBounds(raw: string): [number, number, number, number] | null {
  // Format: [left,top][right,bottom]
  const m = raw.match(/\[(\d+),(\d+)\]\[(\d+),(\d+)\]/);
  if (!m) return null;
  return [+m[1], +m[2], +m[3], +m[4]];
}

function shortClassName(full: string): string {
  const idx = full.lastIndexOf('.');
  return idx >= 0 ? full.slice(idx + 1) : full;
}

function elementToNode(el: Element, depth: number): HierarchyTreeNode {
  const className = el.getAttribute('class') ?? '';
  const node: HierarchyTreeNode = {
    id: _nextId++,
    tag: el.tagName,
    className: shortClassName(className),
    resourceId: el.getAttribute('resource-id') ?? '',
    text: el.getAttribute('text') ?? '',
    contentDesc: el.getAttribute('content-desc') ?? '',
    pkg: el.getAttribute('package') ?? '',
    bounds: parseBounds(el.getAttribute('bounds') ?? ''),
    clickable: el.getAttribute('clickable') === 'true',
    children: [],
    depth
  };
  for (let i = 0; i < el.children.length; i++) {
    const child = el.children[i];
    if (child.tagName === 'node') {
      node.children.push(elementToNode(child, depth + 1));
    }
  }
  return node;
}

/**
 * Parse XML hierarchy string into a tree. Returns root node or null.
 * Android may emit several top-level &lt;node&gt; siblings (e.g. SystemUI + app window).
 * Using only querySelector('node') hid app content — we merge all direct children of &lt;hierarchy&gt;.
 */
export function parseHierarchyTree(xml: string): HierarchyTreeNode | null {
  if (!xml || !xml.trim()) return null;
  try {
    _nextId = 0;
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    const hierarchyEl = doc.querySelector('hierarchy');
    if (!hierarchyEl) return null;
    const topNodes = Array.from(hierarchyEl.children).filter(
      (c) => c.tagName === 'node'
    ) as Element[];
    if (topNodes.length === 0) return null;
    if (topNodes.length === 1) {
      return elementToNode(topNodes[0], 0);
    }
    const synthetic: HierarchyTreeNode = {
      id: _nextId++,
      tag: 'hierarchy',
      className: `${topNodes.length} roots`,
      resourceId: '',
      text: '',
      contentDesc: '',
      pkg: '',
      bounds: null,
      clickable: false,
      children: topNodes.map((el) => elementToNode(el, 1)),
      depth: 0
    };
    return synthetic;
  } catch {
    return null;
  }
}

const SYSTEM_UI_PACKAGES = [
  'com.android.systemui',
  'com.android.providers.',
  'com.android.permissioncontroller'
] as const;

/** True for status bar, nav bar, and other platform chrome in hierarchy dumps. */
export function isSystemUiPackage(pkg: string): boolean {
  const p = (pkg ?? '').trim();
  if (!p || p === 'android') return true;
  return SYSTEM_UI_PACKAGES.some(
    (prefix) => p === prefix || p.startsWith(prefix)
  );
}

function redepthTree(
  node: HierarchyTreeNode,
  depth: number
): HierarchyTreeNode {
  return {
    ...node,
    depth,
    children: node.children.map((child) => redepthTree(child, depth + 1))
  };
}

/** Drop SystemUI nodes from the viewer tree; app windows are kept / promoted. */
export function filterSystemUiFromTree(
  root: HierarchyTreeNode | null
): HierarchyTreeNode | null {
  if (!root) return null;

  function strip(node: HierarchyTreeNode): HierarchyTreeNode[] {
    const children = node.children.flatMap(strip);
    if (isSystemUiPackage(node.pkg)) return children;
    return [{ ...node, children }];
  }

  const kept = strip(root);
  if (kept.length === 0) return null;
  if (kept.length === 1) return redepthTree(kept[0]!, 0);

  const synthetic: HierarchyTreeNode = {
    ...root,
    tag: 'hierarchy',
    className: `${kept.length} app roots`,
    resourceId: '',
    text: '',
    contentDesc: '',
    pkg: '',
    bounds: null,
    clickable: false,
    children: kept,
    depth: 0
  };
  return redepthTree(synthetic, 0);
}

/**
 * Find all node IDs that match a search query (text, resource-id, or content-desc).
 * Also returns ancestor IDs so the tree structure is preserved.
 */
export function searchTree(
  root: HierarchyTreeNode,
  query: string
): Set<number> {
  const matching = new Set<number>();
  if (!query.trim()) return matching;
  const q = query.toLowerCase();

  function walk(node: HierarchyTreeNode): boolean {
    const selfMatch =
      node.text.toLowerCase().includes(q) ||
      node.resourceId.toLowerCase().includes(q) ||
      node.contentDesc.toLowerCase().includes(q) ||
      node.className.toLowerCase().includes(q);

    let childMatch = false;
    for (const child of node.children) {
      if (walk(child)) childMatch = true;
    }

    if (selfMatch || childMatch) {
      matching.add(node.id);
      return true;
    }
    return false;
  }

  walk(root);
  return matching;
}

/**
 * Find the node at relative position (rx, ry ∈ [0,1]) that matches the
 * selector picker (control-record-xml.ts:findSelectorInXml) so the tree
 * highlight lands on the same node the recorder will target.
 *
 * Picking rule (mirror of findSelectorInXml):
 *   1. Collect nodes whose bounds contain the point.
 *   2. Prefer clickable-self; else promote to nearest clickable ancestor.
 *   3. Smallest-area wins within the chosen pool.
 */
export function findNodeIdAtRatio(
  root: HierarchyTreeNode,
  rx: number,
  ry: number
): number | null {
  // Prefer root bounds. If synthetic wrapper (null bounds), infer from largest child.
  let screenBounds = root.bounds;
  if (!screenBounds) {
    let bestArea = 0;
    for (const c of root.children) {
      if (!c.bounds) continue;
      const [x1, y1, x2, y2] = c.bounds;
      const a = (x2 - x1) * (y2 - y1);
      if (a > bestArea) {
        bestArea = a;
        screenBounds = c.bounds;
      }
    }
  }
  if (!screenBounds) return null;
  const dw = screenBounds[2];
  const dh = screenBounds[3];
  if (dw <= 0 || dh <= 0) return null;
  const px = rx * dw;
  const py = ry * dh;

  type Cand = {
    node: HierarchyTreeNode;
    area: number;
    clickableAncestor: HierarchyTreeNode | null;
  };
  const candidates: Cand[] = [];

  function walk(
    node: HierarchyTreeNode,
    nearestClickableAnc: HierarchyTreeNode | null
  ) {
    const ownClickable = node.clickable ? node : nearestClickableAnc;
    if (!node.bounds) {
      node.children.forEach((c) => walk(c, ownClickable));
      return;
    }
    const [x1, y1, x2, y2] = node.bounds;
    if (!(x1 <= px && px <= x2 && y1 <= py && py <= y2)) return;
    if (x2 <= x1 || y2 <= y1) return;
    candidates.push({
      node,
      area: (x2 - x1) * (y2 - y1),
      clickableAncestor: ownClickable
    });
    node.children.forEach((c) => walk(c, ownClickable));
  }
  walk(root, null);

  if (candidates.length === 0) return null;

  const clickableSelf = candidates.filter((c) => c.node.clickable);
  let pool: HierarchyTreeNode[];
  if (clickableSelf.length > 0) {
    pool = clickableSelf.map((c) => c.node);
  } else {
    const seen = new Set<number>();
    const promoted: HierarchyTreeNode[] = [];
    for (const c of candidates) {
      const a = c.clickableAncestor;
      if (a && !seen.has(a.id)) {
        promoted.push(a);
        seen.add(a.id);
      }
    }
    pool = promoted.length > 0 ? promoted : candidates.map((c) => c.node);
  }

  let bestId: number | null = null;
  let bestArea = Infinity;
  for (const n of pool) {
    if (!n.bounds) continue;
    const [x1, y1, x2, y2] = n.bounds;
    const area = (x2 - x1) * (y2 - y1);
    if (area < bestArea) {
      bestArea = area;
      bestId = n.id;
    }
  }
  return bestId;
}

/**
 * Home/launcher grids reuse one resource-id for every cell (e.g. Samsung
 * `com.sec.android.app.launcher:id/icon`). Using resource-id taps the *first*
 * match in the XML, not the icon you picked — prefer text / content-desc.
 */
export function isAmbiguousLauncherResourceId(
  resourceId: string,
  pkg: string
): boolean {
  if (!resourceId || !resourceId.includes('/')) return false;
  if (
    !/:id\/(icon|label|title|icon_text|text|name|bubble_text)$/i.test(
      resourceId
    )
  ) {
    return false;
  }
  const prefixes = [
    'com.sec.android.app.launcher',
    'com.android.launcher',
    'com.google.android.apps.nexuslauncher',
    'com.miui.home',
    'com.huawei.android.launcher',
    'com.oppo.launcher',
    'com.vivo.launcher'
  ];
  return prefixes.some(
    (p) => pkg.startsWith(p) || resourceId.startsWith(`${p}:`)
  );
}

/**
 * Pick the best selector for a node (same priority as hierarchy-selectors.ts).
 */
export function bestSelector(node: HierarchyTreeNode): {
  by: string;
  value: string;
} {
  const rid = node.resourceId?.trim() ?? '';
  const ambiguous =
    rid && isAmbiguousLauncherResourceId(rid, node.pkg?.trim() ?? '');

  const text = node.text?.trim() ?? '';
  if (ambiguous && text && text.length < 120) {
    return { by: 'text', value: node.text! };
  }
  const desc = node.contentDesc?.trim() ?? '';
  if (ambiguous && desc && desc.length < 120) {
    return { by: 'description', value: node.contentDesc! };
  }

  if (rid && rid.includes('/')) {
    return { by: 'resource-id', value: rid };
  }
  if (node.text && node.text.length < 80) {
    return { by: 'text', value: node.text };
  }
  if (node.contentDesc) {
    return { by: 'description', value: node.contentDesc };
  }
  return { by: 'class name', value: node.className };
}
