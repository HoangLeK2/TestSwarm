// Fails if a label_key / placeholder_key exposed by the backend scenario schema
// has no entry under campaignsFeature.stepEditor in en.json AND vi.json.
//
// check-i18n-keys.mjs cannot see these: <SchemaField> calls t(dynamicKey), and
// that scanner only reads literal t('key') calls. next-intl renders the raw key
// string into the UI when it is missing, so without this check a schema-driven
// form silently shows "appLifecycle.packageLabel" to the user.
//
// The schema comes from generate/scenario-schema.json, which the backend writes
// from get_scenario_schema() — not from source regexes, so catalog-owned
// metadata is checked after the same overlay production uses, and not from a
// Python subprocess, so this runs without a built device_farm venv.
// device_farm/tests/test_scenario_schema_snapshot.py keeps that file current.
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  '..'
);
const NAMESPACE = 'campaignsFeature.stepEditor';

const load = (f) =>
  JSON.parse(fs.readFileSync(path.join(root, 'messages', f), 'utf8'));
const en = load('en.json');
const vi = load('vi.json');

const has = (obj, key) =>
  key
    .split('.')
    .reduce((a, p) => (a && typeof a === 'object' ? a[p] : undefined), obj) !==
  undefined;

const schemaPath = path.join(root, 'generate/scenario-schema.json');
if (!fs.existsSync(schemaPath)) {
  console.error(`${schemaPath} is missing. Regenerate it with:`);
  console.error(
    '  cd device_farm && UPDATE_SCENARIO_SCHEMA_SNAPSHOT=1 .venv/bin/python -m pytest tests/test_scenario_schema_snapshot.py'
  );
  process.exit(1);
}
const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));

const keys = new Set();
for (const stepSchema of Object.values(schema.steps_schema ?? {})) {
  for (const field of Object.values(stepSchema.fields ?? {})) {
    if (field.label_key) keys.add(field.label_key);
    if (field.placeholder_key) keys.add(field.placeholder_key);
    for (const value of field.values ?? []) {
      if (value.label_key) keys.add(value.label_key);
    }
  }
}

const bad = [];
for (const key of [...keys].sort()) {
  const full = `${NAMESPACE}.${key}`;
  const missing = [!has(en, full) && 'en', !has(vi, full) && 'vi'].filter(
    Boolean
  );
  if (missing.length) bad.push(`  ${key}  missing in ${missing.join('+')}`);
}

if (bad.length) {
  console.error(`${bad.length} schema label key(s) with no translation:`);
  bad.forEach((b) => console.error(b));
  console.error(
    `\nAdd them under "${NAMESPACE}" in messages/en.json and messages/vi.json,`
  );
  console.error(
    'or drop label_key from the field so it falls back to a humanised name.'
  );
  process.exit(1);
}
console.log(`schema field i18n OK (${keys.size} key(s))`);
