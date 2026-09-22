// Fails if a t('key') call in src/ has no matching entry in en.json AND vi.json.
// Namespaces come from useTranslations('ns') and from `t` props typed
// useTranslations<'ns'>. A key resolves if it exists under any namespace in scope
// for that file — coarse, but catches the raw-key-rendered-in-UI bug.
// ponytail: file-level namespace scope, tighten if a file mixes unrelated namespaces.
import fs from 'node:fs';
import path from 'node:path';

const load = (f) =>
  JSON.parse(fs.readFileSync(new URL(f, import.meta.url), 'utf8'));
const en = load('../messages/en.json');
const vi = load('../messages/vi.json');

const has = (obj, key) =>
  key
    .split('.')
    .reduce((a, p) => (a && typeof a === 'object' ? a[p] : undefined), obj) !==
  undefined;

const walk = (dir) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? walk(p) : /\.tsx?$/.test(e.name) ? [p] : [];
  });

const root = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  '..'
);
const bad = [];

for (const file of walk(path.join(root, 'src'))) {
  const src = fs.readFileSync(file, 'utf8');
  const namespaces = [
    ...[...src.matchAll(/useTranslations[<(]\s*'([^']+)'/g)].map((m) => m[1])
  ];
  if (!namespaces.length) continue;

  // Aliases too: `const tField = useTranslations(...)` is as common here as `t`,
  // and a key only reached through an alias used to slip past this check.
  const aliases = [
    ...new Set([
      't',
      ...[
        ...src.matchAll(/(?:const|let)\s+(t[A-Z]\w*)\s*=\s*useTranslations/g)
      ].map((m) => m[1]),
      ...[...src.matchAll(/(t[A-Z]\w*)\s*:\s*useTranslations/g)].map(
        (m) => m[1]
      )
    ])
  ];
  const callRe = new RegExp(
    `(?<![\\w.])(?:${aliases.join('|')})\\(\\s*'([a-zA-Z0-9_.]+)'`,
    'g'
  );

  for (const m of src.matchAll(callRe)) {
    const key = m[1];
    const inEn = namespaces.some((ns) => has(en, `${ns}.${key}`));
    const inVi = namespaces.some((ns) => has(vi, `${ns}.${key}`));
    if (inEn && inVi) continue;
    const line = src.slice(0, m.index).split('\n').length;
    const missing = [!inEn && 'en', !inVi && 'vi'].filter(Boolean).join('+');
    bad.push(
      `${path.relative(root, file)}:${line}  t('${key}')  missing in ${missing}`
    );
  }
}

// ICU eats `{...}` as a placeholder. A message meaning to SHOW `${VAR}` to the
// user throws at render time and next-intl falls back to printing the raw key.
// Escape it as $'{VAR}'.
const walkMessages = function* (node, trail = '') {
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) {
      yield* walkMessages(v, trail ? `${trail}.${k}` : k);
    }
  } else if (typeof node === 'string') {
    yield [trail, node];
  }
};

for (const [name, messages] of [
  ['en', en],
  ['vi', vi]
]) {
  for (const [key, value] of walkMessages(messages)) {
    if (value.includes('${')) {
      bad.push(
        `messages/${name}.json  ${key}  unescaped \${...} — write $'{...}' instead`
      );
    }
  }
}

if (bad.length) {
  console.error(`${bad.length} unresolved translation key(s):`);
  bad.forEach((b) => console.error('  ' + b));
  process.exit(1);
}
console.log('i18n keys OK');
