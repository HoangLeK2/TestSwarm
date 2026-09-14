#!/bin/bash
# find_unused_deps.sh — Report declared dependencies nothing in the tree imports.
#
# Read-only. Prints a report; deletes nothing. Every hit needs a human look
# before it goes, because three classes of dependency are used without ever
# being imported by name and will show up here as false positives:
#   - config-only tools (tailwind, postcss, autoprefixer, eslint/prettier
#     plugins, husky, lint-staged) — referenced from config files by convention
#   - peer/transitive runtime deps another package resolves (sharp for Next
#     image optimisation, hiredis for redis)
#   - anything reached through a dynamic string (importlib, require(variable))
#
# Usage: bash scripts/find_unused_deps.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

hr() { printf '\n== %s ==\n' "$1"; }

# ── front-end ─────────────────────────────────────────────────────────────────
hr "front-end (package.json)"
cd "$ROOT/front-end" || exit 1
node -e '
const fs = require("fs");
const path = require("path");
const pkg = JSON.parse(fs.readFileSync("package.json", "utf8"));
const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };

// Scan every source and config file, not just src/: a dependency named only in
// next.config.ts or tailwind.config.ts is used, just not imported.
const roots = ["src", "app", "scripts", "patches"].filter((d) => fs.existsSync(d));
const files = [];
const walk = (dir) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue;
    const p = path.join(dir, e.name);
    e.isDirectory() ? walk(p) : files.push(p);
  }
};
roots.forEach(walk);
for (const f of fs.readdirSync(".")) {
  if (fs.statSync(f).isFile()) files.push(f);
}

let blob = "";
for (const f of files) {
  try { blob += fs.readFileSync(f, "utf8"); } catch {}
}

const unused = Object.keys(deps).filter((name) => {
  // Quoted, so "react" does not match "react-dom" and vice versa.
  return !new RegExp(`["'"'"'\`]${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(["'"'"'\`/])`).test(blob)
      && !blob.includes(name + "\n");
});
console.log(unused.length ? unused.join("\n") : "(none)");
'

# ── device_farm (Python) ──────────────────────────────────────────────────────
hr "device_farm (pyproject.toml)"
cd "$ROOT/device_farm" || exit 1
# deptry understands import names vs package names (e.g. pillow -> PIL).
uvx deptry . --ignore DEP002,DEP003 2>/dev/null \
  || echo "deptry unavailable; run: uvx deptry ."
echo "--- declared but never imported (DEP002) ---"
uvx deptry . --ignore DEP001,DEP003,DEP004 2>&1 | grep -E "DEP002|error" || true

# ── agent-boot (Python) ───────────────────────────────────────────────────────
hr "agent-boot (pyproject.toml)"
cd "$ROOT/agent-boot" || exit 1
uvx deptry . --ignore DEP001,DEP003,DEP004 2>&1 | grep -E "DEP002|error" || true

# ── media-adapter (Go) ────────────────────────────────────────────────────────
hr "media-adapter (go.mod) — tidy diff means unused requires"
cd "$ROOT/agent-boot/media-adapter" || exit 1
cp go.mod /tmp/go.mod.before && cp go.sum /tmp/go.sum.before
go mod tidy >/dev/null 2>&1
diff /tmp/go.mod.before go.mod && echo "(go.mod already tidy)"
cp /tmp/go.mod.before go.mod && cp /tmp/go.sum.before go.sum
