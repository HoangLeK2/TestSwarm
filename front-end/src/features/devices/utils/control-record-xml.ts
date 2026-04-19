import { fetchHierarchy } from '../services/api';
import { isAmbiguousLauncherResourceId } from './hierarchy-tree';

/**
 * Normalize Android hierarchy XML before hashing.
 * Strip volatile attributes that change between dumps even when UI is stable:
 * index, bounds, focused, selected, drawing-order
 * Keeps: text, resource-id, content-desc, class, package, checkable, checked, enabled, scrollable
 */
export function normalizeXml(xmlStr: string): string {
  return xmlStr
    .replace(/\s+index="[^"]*"/g, '')
    .replace(/\s+bounds="[^"]*"/g, '')
    .replace(/\s+focused="[^"]*"/g, '')
    .replace(/\s+selected="[^"]*"/g, '')
    .replace(/\s+drawing-order="[^"]*"/g, '')
    .replace(/\s+rotation="[^"]*"/g, '');
}

/** FNV-1a 32-bit hash on normalized XML — stable across volatile attribute churn. */
export function hashXml(xml: string): number {
  const norm = normalizeXml(xml);
  let h = 0x811c9dc5;
  for (let i = 0; i < norm.length; i++) {
    h ^= norm.charCodeAt(i);
    h = (Math.imul(h, 0x01000193)) >>> 0;
  }
  return h;
}

/**
 * Parse XML, find element at (rx,ry).
 *
 * Picking strategy:
 *   1. Collect all nodes whose bounds contain (px,py) AND enabled!=false.
 *   2. Prefer nodes with clickable="true" (or walk up to nearest clickable ancestor).
 *   3. Among candidates, pick smallest area → most specific hit.
 *   4. Selector priority per node:
 *      ambiguous-launcher → text/desc
 *      unique resource-id → resource-id
 *      unique text / desc → text or description
 *      non-unique rid → xpath with clickable + instance index
 *      fallback → xpath pinned by class + bounds-ratio (always unique per screen)
 *
 * bounds.rx1/ry1/rx2/ry2 normalized to XML root dims (0–1).
 */
export function findSelectorInXml(
  xmlStr: string,
  rx: number,
  ry: number
): {
  by: 'resource-id' | 'text' | 'description' | 'xpath' | 'class name';
  value: string;
  bounds?: {
    left: number; top: number; right: number; bottom: number;
    rx1: number; ry1: number; rx2: number; ry2: number;
  };
} | null {
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xmlStr, 'text/xml');
  } catch {
    return null;
  }

  const allNodes = Array.from(doc.getElementsByTagName('node'));
  let dw = 1080, dh = 1920;
  for (const n of allNodes) {
    const m = /\[0,0\]\[(\d+),(\d+)\]/.exec(n.getAttribute('bounds') ?? '');
    if (m) { dw = parseInt(m[1]); dh = parseInt(m[2]); break; }
  }
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
    if (txt && txt.length < 80) textCount.set(txt, (textCount.get(txt) ?? 0) + 1);
    if (d && d.length < 80) descCount.set(d, (descCount.get(d) ?? 0) + 1);
  }

  const BOUNDS = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/;
  const CONTAINER_CLASSES = new Set([
    'android.widget.FrameLayout',
    'android.widget.LinearLayout',
    'android.widget.RelativeLayout',
    'android.view.View',
    'android.view.ViewGroup',
    'androidx.constraintlayout.widget.ConstraintLayout',
    'android.widget.ScrollView',
    'androidx.recyclerview.widget.RecyclerView',
  ]);

  type Cand = {
    node: Element;
    x1: number; y1: number; x2: number; y2: number;
    area: number;
    clickable: boolean;
    clickableAncestor: Element | null;
  };

  // Build parent map once for ancestor walk
  const parentOf = new Map<Element, Element | null>();
  for (const n of allNodes) {
    const p = n.parentElement;
    parentOf.set(n, p && p.tagName === 'node' ? p : null);
  }
  const findClickableSelfOrAncestor = (n: Element): Element | null => {
    let cur: Element | null = n;
    while (cur) {
      if (cur.getAttribute('clickable') === 'true') return cur;
      cur = parentOf.get(cur) ?? null;
    }
    return null;
  };

  // Step 1+2: collect candidates
  const candidates: Cand[] = [];
  for (const node of allNodes) {
    const m = BOUNDS.exec(node.getAttribute('bounds') ?? '');
    if (!m) continue;
    const [x1, y1, x2, y2] = [+m[1], +m[2], +m[3], +m[4]];
    if (!(x1 <= px && px <= x2 && y1 <= py && py <= y2)) continue;
    if (node.getAttribute('enabled') === 'false') continue;
    // drop 0-area / off-screen
    if (x2 <= x1 || y2 <= y1) continue;

    candidates.push({
      node, x1, y1, x2, y2,
      area: (x2 - x1) * (y2 - y1),
      clickable: node.getAttribute('clickable') === 'true',
      clickableAncestor: findClickableSelfOrAncestor(node),
    });
  }
  if (candidates.length === 0) return null;

  // Step 3: prefer clickable self; else promote non-clickable hit to its
  // clickable ancestor (the real button the user aimed at); else raw smallest.
  const clickableSelf = candidates.filter(c => c.clickable);
  let pool: Cand[];
  if (clickableSelf.length > 0) {
    pool = clickableSelf;
  } else {
    const promoted: Cand[] = [];
    const seen = new Set<Element>();
    for (const c of candidates) {
      const a = c.clickableAncestor;
      if (a && !seen.has(a)) {
        const bm = BOUNDS.exec(a.getAttribute('bounds') ?? '');
        if (bm) {
          const [x1, y1, x2, y2] = [+bm[1], +bm[2], +bm[3], +bm[4]];
          promoted.push({
            node: a, x1, y1, x2, y2,
            area: (x2 - x1) * (y2 - y1),
            clickable: true,
            clickableAncestor: a,
          });
          seen.add(a);
        }
      }
    }
    pool = promoted.length > 0 ? promoted : candidates;
  }

  pool.sort((a, b) => a.area - b.area);
  const chosen = pool[0];
  const { node, x1, y1, x2, y2 } = chosen;

  const rid = (node.getAttribute('resource-id') ?? '').trim();
  const desc = (node.getAttribute('content-desc') ?? '').trim();
  const text = (node.getAttribute('text') ?? '').trim();
  const pkg = (node.getAttribute('package') ?? '').trim();
  const cls = (node.getAttribute('class') ?? '').trim();

  const ambiguousLauncher = rid ? isAmbiguousLauncherResourceId(rid, pkg) : false;
  const ridUnique = !!rid && !ambiguousLauncher && (ridCount.get(rid) ?? 0) === 1;
  const textUnique = !!text && text.length < 80 && (textCount.get(text) ?? 0) === 1;
  const descUnique = !!desc && desc.length < 80 && (descCount.get(desc) ?? 0) === 1;

  type Sel = {
    by: 'resource-id' | 'text' | 'description' | 'xpath' | 'class name';
    value: string;
  };
  let sel: Sel | null = null;

  if (ambiguousLauncher && text && text.length < 120) {
    sel = { by: 'text', value: text };
  } else if (ambiguousLauncher && desc && desc.length < 80) {
    sel = { by: 'description', value: desc };
  } else if (ridUnique) {
    sel = { by: 'resource-id', value: rid };
  } else if (descUnique) {
    sel = { by: 'description', value: desc };
  } else if (textUnique) {
    sel = { by: 'text', value: text };
  } else if (rid && rid.includes('/')) {
    // Non-unique rid: pin with clickable=true + instance index restricted to clickable hits
    const sameRid = allNodes.filter((n) => (n.getAttribute('resource-id') ?? '') === rid);
    const clickableSameRid = sameRid.filter((n) => n.getAttribute('clickable') === 'true');
    if (clickableSameRid.length >= 1 && clickableSameRid.includes(node)) {
      const idx = clickableSameRid.indexOf(node);
      sel = {
        by: 'xpath',
        value: `(//*[@resource-id="${rid}" and @clickable="true"])[${idx + 1}]`,
      };
    } else {
      const idx = sameRid.indexOf(node);
      sel = { by: 'xpath', value: `(//*[@resource-id="${rid}"])[${idx + 1}]` };
    }
  } else if (desc) {
    sel = { by: 'description', value: desc };
  } else if (text && text.length < 80) {
    sel = { by: 'text', value: text };
  } else if (cls) {
    // Last resort — pin by class + bounds (bounds always unique per screen)
    if (CONTAINER_CLASSES.has(cls)) {
      sel = {
        by: 'xpath',
        value: `//*[@class="${cls}" and @bounds="[${x1},${y1}][${x2},${y2}]"]`,
      };
    } else {
      sel = { by: 'class name', value: cls };
    }
  }

  if (!sel) return null;
  return {
    by: sel.by,
    value: sel.value,
    bounds: {
      left: x1, top: y1, right: x2, bottom: y2,
      rx1: x1 / dw, ry1: y1 / dh, rx2: x2 / dw, ry2: y2 / dh,
    },
  };
}

export function getScreenSignature(xml: string): { package: string; texts: string[] } {
  try {
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    const BOUNDS = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/;
    let pkg = '';
    let bestArea = 0;
    for (const node of Array.from(doc.getElementsByTagName('node'))) {
      const p = (node.getAttribute('package') ?? '').trim();
      if (!p || p === 'android' || p.startsWith('com.android.systemui')) continue;
      const m = BOUNDS.exec(node.getAttribute('bounds') ?? '');
      if (!m) continue;
      const area = (+m[3] - +m[1]) * (+m[4] - +m[2]);
      if (area > bestArea) {
        bestArea = area;
        pkg = p;
      }
    }
    if (!pkg) {
      pkg = doc.querySelector('node')?.getAttribute('package') ?? '';
    }
    const texts: string[] = [];
    for (const node of Array.from(doc.getElementsByTagName('node'))) {
      const t = (node.getAttribute('text') ?? '').trim();
      if (t && t.length < 60 && !texts.includes(t)) texts.push(t);
      if (texts.length >= 5) break;
    }
    return { package: pkg, texts };
  } catch {
    return { package: '', texts: [] };
  }
}

export async function pollUntilUiChange(
  serial: string,
  oldHash: number,
  intervalMs = 700,
  timeoutMs = 2800
): Promise<string | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise<void>((r) => setTimeout(r, intervalMs));
    try {
      const xml = (await fetchHierarchy(serial, true))?.trim() ?? '';
      if (xml && hashXml(xml) !== oldHash) return xml;
    } catch {
      /* ignore */
    }
  }
  return null;
}
