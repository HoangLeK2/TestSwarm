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
 * Priority: resource-id > content-desc > text > class
 *
 * bounds.rx1/ry1/rx2/ry2 are normalized to XML root dims (0–1) so the caller
 * can pass them directly to the screenshot-b64 API without knowing device resolution.
 */
export function findSelectorInXml(
  xmlStr: string,
  rx: number,
  ry: number
): {
  by: 'resource-id' | 'text' | 'xpath' | 'class name';
  value: string;
  bounds?: {
    left: number; top: number; right: number; bottom: number;
    // Ratio equivalents normalized to XML root viewport dimensions
    rx1: number; ry1: number; rx2: number; ry2: number;
  };
} | null {
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xmlStr, 'text/xml');
  } catch {
    return null;
  }
  const rootNode = doc.querySelector('node');
  const rootBounds = rootNode?.getAttribute('bounds') ?? '';
  const rootM = /\[0,0\]\[(\d+),(\d+)\]/.exec(rootBounds);
  const dw = rootM ? parseInt(rootM[1]) : 1080;
  const dh = rootM ? parseInt(rootM[2]) : 1920;
  const px = rx * dw;
  const py = ry * dh;

  const BOUNDS = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/;
  let best: {
    by: 'resource-id' | 'text' | 'xpath' | 'class name';
    value: string;
    bounds?: { left: number; top: number; right: number; bottom: number };
  } | null = null;
  let bestArea = Infinity;

  for (const node of Array.from(doc.getElementsByTagName('node'))) {
    const m = BOUNDS.exec(node.getAttribute('bounds') ?? '');
    if (!m) continue;
    const [x1, y1, x2, y2] = [+m[1], +m[2], +m[3], +m[4]];
    if (!(x1 <= px && px <= x2 && y1 <= py && py <= y2)) continue;
    const area = (x2 - x1) * (y2 - y1);
    if (area >= bestArea) continue;

    const rid = (node.getAttribute('resource-id') ?? '').trim();
    const desc = (node.getAttribute('content-desc') ?? '').trim();
    const text = (node.getAttribute('text') ?? '').trim();
    const pkg = (node.getAttribute('package') ?? '').trim();
    const cls = (node.getAttribute('class') ?? '').trim();

    const ambiguousLauncher = rid && isAmbiguousLauncherResourceId(rid, pkg);

    const CONTAINER_CLASSES = new Set([
      'android.widget.FrameLayout',
      'android.widget.LinearLayout',
      'android.widget.RelativeLayout',
      'android.view.View',
      'android.view.ViewGroup',
      'androidx.constraintlayout.widget.ConstraintLayout',
      'android.widget.ScrollView',
      'androidx.recyclerview.widget.RecyclerView'
    ]);

    type Sel = {
      by: 'resource-id' | 'text' | 'xpath' | 'class name';
      value: string;
      bounds?: { left: number; top: number; right: number; bottom: number; rx1: number; ry1: number; rx2: number; ry2: number };
    };
    let sel: Sel | null = null;
    if (ambiguousLauncher && text && text.length < 120) {
      sel = { by: 'text', value: text };
    } else if (ambiguousLauncher && desc && desc.length < 80) {
      const safeDesc = desc.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      sel = { by: 'xpath', value: `//*[@content-desc="${safeDesc}"]` };
    } else if (rid && rid.includes('/')) {
      sel = { by: 'resource-id', value: rid };
    } else if (desc && desc.length < 80) {
      const safeDesc = desc.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      sel = { by: 'xpath', value: `//*[@content-desc="${safeDesc}"]` };
    } else if (text && text.length < 80) {
      sel = { by: 'text', value: text };
    } else if (rid) {
      sel = { by: 'resource-id', value: rid };
    } else if (cls && !CONTAINER_CLASSES.has(cls)) {
      sel = { by: 'class name', value: cls };
    }

    if (sel) {
      sel.bounds = {
        left: x1, top: y1, right: x2, bottom: y2,
        rx1: x1 / dw, ry1: y1 / dh, rx2: x2 / dw, ry2: y2 / dh,
      };
      best = sel;
      bestArea = area;
    }
  }
  return best;
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
  intervalMs = 300,
  timeoutMs = 3000
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
