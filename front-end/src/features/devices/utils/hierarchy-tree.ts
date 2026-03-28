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
    depth,
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
 */
export function parseHierarchyTree(xml: string): HierarchyTreeNode | null {
  if (!xml || !xml.trim()) return null;
  try {
    _nextId = 0;
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    const root = doc.querySelector('hierarchy');
    if (!root) return null;
    // hierarchy element may have direct <node> children
    const firstNode = root.querySelector('node');
    if (!firstNode) return null;
    return elementToNode(firstNode, 0);
  } catch {
    return null;
  }
}

/**
 * Find all node IDs that match a search query (text, resource-id, or content-desc).
 * Also returns ancestor IDs so the tree structure is preserved.
 */
export function searchTree(
  root: HierarchyTreeNode,
  query: string,
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
 * Pick the best selector for a node (same priority as hierarchy-selectors.ts).
 */
export function bestSelector(node: HierarchyTreeNode): { by: string; value: string } {
  if (node.resourceId && node.resourceId.includes('/')) {
    return { by: 'resource-id', value: node.resourceId };
  }
  if (node.text && node.text.length < 80) {
    return { by: 'text', value: node.text };
  }
  if (node.contentDesc) {
    return { by: 'content-desc', value: node.contentDesc };
  }
  return { by: 'class-name', value: node.className };
}
