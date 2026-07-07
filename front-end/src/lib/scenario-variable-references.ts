const VARIABLE_NAME_RE = /^\w+$/;
const VARIABLE_TOKEN_RE = /\$\{(\w+)\}/g;

export type VariableRename = {
  from: string;
  to: string;
};

export function detectSingleVariableRename(
  previous: Record<string, unknown>,
  next: Record<string, unknown>
): VariableRename | null {
  const previousKeys = Object.keys(previous).filter((key) => key.trim());
  const nextKeys = Object.keys(next).filter((key) => key.trim());
  if (previousKeys.length !== nextKeys.length) return null;

  const nextSet = new Set(nextKeys);
  const previousSet = new Set(previousKeys);
  const removed = previousKeys.filter((key) => !nextSet.has(key));
  const added = nextKeys.filter((key) => !previousSet.has(key));
  if (removed.length !== 1 || added.length !== 1) return null;

  const from = removed[0]!;
  const to = added[0]!;
  if (
    from === to ||
    !VARIABLE_NAME_RE.test(from) ||
    !VARIABLE_NAME_RE.test(to)
  ) {
    return null;
  }
  return { from, to };
}

export function replaceScenarioVariableReferences<T>(
  value: T,
  rename: VariableRename
): T {
  if (typeof value === 'string') {
    const token = new RegExp(`\\$\\{${rename.from}\\}`, 'g');
    return value.replace(token, `\${${rename.to}}`) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) =>
      replaceScenarioVariableReferences(item, rename)
    ) as T;
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) {
      out[key] = replaceScenarioVariableReferences(child, rename);
    }
    return out as T;
  }
  return value;
}

function normalizeTagsValue(tags: string): string {
  return tags
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .join(',');
}

export function stripUndeclaredVariableReferencesFromTags<T>(
  value: T,
  variables: Record<string, unknown>
): T {
  const declared = new Set(Object.keys(variables));

  function walk(current: unknown): unknown {
    if (Array.isArray(current)) {
      return current.map((item) => walk(item));
    }
    if (current && typeof current === 'object') {
      const out: Record<string, unknown> = {};
      for (const [key, child] of Object.entries(current)) {
        if (key === 'tags' && typeof child === 'string') {
          out[key] = normalizeTagsValue(
            child.replace(VARIABLE_TOKEN_RE, (token, name: string) =>
              declared.has(name) ? token : ''
            )
          );
        } else {
          out[key] = walk(child);
        }
      }
      return out;
    }
    return current;
  }

  return walk(value) as T;
}
