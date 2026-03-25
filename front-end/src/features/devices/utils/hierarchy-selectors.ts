export type HierarchyParsedNode = {
  id: string;
  label: string;
  by: 'resource-id' | 'text' | 'xpath';
  value: string;
  package?: string;
  bounds?: string;
  clickable?: boolean;
};

export function parseHierarchySelectorNodes(hierarchyXml: string): HierarchyParsedNode[] {
  if (!hierarchyXml || hierarchyXml.startsWith('Lỗi:') || hierarchyXml.startsWith('Error:')) return [];
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(hierarchyXml, 'text/xml');
    const all = Array.from(doc.getElementsByTagName('*')) as Element[];
    const items: HierarchyParsedNode[] = [];
    const seen = new Set<string>();
    let idx = 0;
    for (const el of all) {
      const resId = el.getAttribute('resource-id') || '';
      const text = el.getAttribute('text') || '';
      const desc = el.getAttribute('content-desc') || '';

      if (resId && !seen.has(`res:${resId}`)) {
        seen.add(`res:${resId}`);
        const label = `${resId}${text ? ` — ${text}` : desc ? ` — ${desc}` : ''}`;
        items.push({ id: `res-${idx++}`, label, by: 'resource-id', value: resId });
      }
      if (text && !resId && !seen.has(`txt:${text}`)) {
        seen.add(`txt:${text}`);
        items.push({
          id: `txt-${idx++}`,
          label: text.slice(0, 60) + (text.length > 60 ? '…' : ''),
          by: 'text',
          value: text
        });
      }
      if (desc && !resId && !seen.has(`desc:${desc}`)) {
        seen.add(`desc:${desc}`);
        const xval = `//*[@content-desc="${desc.replace(/"/g, '\\"')}"]`;
        items.push({
          id: `desc-${idx++}`,
          label: `content-desc: ${desc.slice(0, 50)}`,
          by: 'xpath',
          value: xval,
          clickable: el.getAttribute('clickable') === 'true'
        });
      }
      if (items.length >= 300) break;
    }
    return items;
  } catch {
    return [];
  }
}
