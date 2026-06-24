import { fetchHierarchy } from '../services/api';
import {
  findSelectorInXml,
  inferForegroundPackage,
  listSelectorCandidatesInXml,
  type HierarchyPickOptions,
  type XmlSelectorPick
} from './hierarchy-xml-pick';
import { hierarchyBoundsCenterRatio } from './hierarchy-hit-test';

export type { HierarchyPickOptions, XmlSelectorPick };
export {
  findSelectorInXml,
  inferForegroundPackage,
  listSelectorCandidatesInXml
};

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
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

/** Pick at center of a hierarchy tree node's bounds (tree row click). */
export function findSelectorForTreeNode(
  xmlStr: string,
  bounds: [number, number, number, number] | null,
  options?: HierarchyPickOptions
): XmlSelectorPick | null {
  if (!bounds || !xmlStr?.trim()) return null;
  const [x1, y1, x2, y2] = bounds;
  if (x2 <= x1 || y2 <= y1) return null;
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(xmlStr, 'text/xml');
  } catch {
    return null;
  }
  const allNodes = Array.from(doc.getElementsByTagName('node'));
  const center = hierarchyBoundsCenterRatio(allNodes, [x1, y1, x2, y2], {
    screenDims: options?.screenDims ?? undefined
  });
  if (!center) return null;
  return findSelectorInXml(xmlStr, center.rx, center.ry, options);
}

export function getScreenSignature(xml: string): {
  package: string;
  texts: string[];
} {
  try {
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    const BOUNDS = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/;
    let pkg = '';
    let bestArea = 0;
    for (const node of Array.from(doc.getElementsByTagName('node'))) {
      const p = (node.getAttribute('package') ?? '').trim();
      if (!p || p === 'android' || p.startsWith('com.android.systemui'))
        continue;
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
