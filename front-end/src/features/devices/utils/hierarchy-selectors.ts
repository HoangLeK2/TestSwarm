export type HierarchyParsedNode = {
  id: string;
  label: string;
  by: 'resource-id' | 'text' | 'xpath' | 'description';
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

      if (resId && !seen.has(`res:${resId}`)) {
        seen.add(`res:${resId}`);
        const label = `${resId}${text ? ` — ${text}` : desc ? ` — ${desc}` : ''}`;
        items.push({
          id: `res-${idx++}`,
          label,
          by: 'resource-id',
          value: resId,
          package: pkg || undefined
        });
      }
      if (text && !resId && !seen.has(`txt:${text}`)) {
        seen.add(`txt:${text}`);
        items.push({
          id: `txt-${idx++}`,
          label: text.slice(0, 60) + (text.length > 60 ? '…' : ''),
          by: 'text',
          value: text,
          package: pkg || undefined
        });
      }
      if (desc && !resId && !seen.has(`desc:${desc}`)) {
        seen.add(`desc:${desc}`);
        items.push({
          id: `desc-${idx++}`,
          label: `content-desc: ${desc.slice(0, 50)}`,
          by: 'description',
          value: desc,
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
