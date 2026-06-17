import { pickStableHierarchySelector } from './hierarchy-hit-test';

export type HierarchyParsedNode = {
  id: string;
  label: string;
  by: 'resource-id' | 'text' | 'xpath' | 'description' | 'class name';
  value: string;
  package?: string;
  bounds?: string;
  clickable?: boolean;
};

/** DFS order puts status bar / SystemUI first — deprioritize so app nodes fill the quota. */
function systemUiRank(pkg: string): number {
  if (!pkg) return 0;
  if (pkg === 'android') return 2;
  if (pkg.startsWith('com.android.systemui')) return 2;
  if (pkg.startsWith('com.android.providers.')) return 1;
  if (pkg === 'com.android.permissioncontroller') return 1;
  return 0;
}

export function parseHierarchySelectorNodes(
  hierarchyXml: string
): HierarchyParsedNode[] {
  if (
    !hierarchyXml ||
    hierarchyXml.startsWith('Lỗi:') ||
    hierarchyXml.startsWith('Error:')
  )
    return [];
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(hierarchyXml, 'text/xml');
    const nodes = Array.from(doc.getElementsByTagName('node')) as Element[];
    const ridCount = new Map<string, number>();
    const textCount = new Map<string, number>();
    const descCount = new Map<string, number>();
    for (const el of nodes) {
      const rid = (el.getAttribute('resource-id') ?? '').trim();
      const text = (el.getAttribute('text') ?? '').trim();
      const desc = (el.getAttribute('content-desc') ?? '').trim();
      if (rid) ridCount.set(rid, (ridCount.get(rid) ?? 0) + 1);
      if (text && text.length < 80)
        textCount.set(text, (textCount.get(text) ?? 0) + 1);
      if (desc && desc.length < 80)
        descCount.set(desc, (descCount.get(desc) ?? 0) + 1);
    }
    nodes.sort((a, b) => {
      const pa = a.getAttribute('package') || '';
      const pb = b.getAttribute('package') || '';
      return systemUiRank(pa) - systemUiRank(pb);
    });

    const items: HierarchyParsedNode[] = [];
    const seen = new Set<string>();
    let idx = 0;
    for (const el of nodes) {
      const resId = el.getAttribute('resource-id') || '';
      const text = el.getAttribute('text') || '';
      const desc = el.getAttribute('content-desc') || '';
      const pkg = el.getAttribute('package') || '';
      const selector = pickStableHierarchySelector(
        {
          resourceId: resId,
          text,
          contentDesc: desc,
          pkg,
          className: el.getAttribute('class') || '',
          bounds: el.getAttribute('bounds') || ''
        },
        {
          resourceIdCount: ridCount.get(resId.trim()),
          textCount: textCount.get(text.trim()),
          descCount: descCount.get(desc.trim())
        },
        { allowBoundsXPath: true }
      );

      if (selector && !seen.has(`${selector.by}:${selector.value}`)) {
        seen.add(`${selector.by}:${selector.value}`);
        const label = `${resId}${text ? ` — ${text}` : desc ? ` — ${desc}` : ''}`;
        items.push({
          id: `${selector.by}-${idx++}`,
          label:
            selector.by === 'xpath'
              ? `bounds: ${el.getAttribute('bounds') || selector.value}`
              : label || selector.value,
          by: selector.by,
          value: selector.value,
          clickable: el.getAttribute('clickable') === 'true',
          package: pkg || undefined
        });
      }
      if (items.length >= 300) break;
    }
    return items;
  } catch {
    return [];
  }
}
