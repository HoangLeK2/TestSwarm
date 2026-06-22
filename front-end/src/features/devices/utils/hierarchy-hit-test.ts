/** Shared hit-test heuristics for mirror pick + XML tree highlight (FB-safe). */

export const HIERARCHY_CONTAINER_CLASSES = new Set([
  'android.widget.FrameLayout',
  'android.widget.LinearLayout',
  'android.widget.RelativeLayout',
  'android.view.View',
  'android.view.ViewGroup',
  'android.widget.ScrollView',
  'androidx.recyclerview.widget.RecyclerView',
  'androidx.constraintlayout.widget.ConstraintLayout',
  'android.widget.HorizontalScrollView',
  'androidx.viewpager.widget.ViewPager'
]);

export const HIERARCHY_CONTAINER_SHORT = new Set([
  'FrameLayout',
  'LinearLayout',
  'RelativeLayout',
  'View',
  'ViewGroup',
  'ScrollView',
  'RecyclerView',
  'ConstraintLayout',
  'HorizontalScrollView',
  'ViewPager'
]);

const SYSTEM_UI_PACKAGES = [
  'com.android.systemui',
  'com.android.providers.',
  'com.android.permissioncontroller'
] as const;

/** True for status bar, nav bar, and other platform chrome in hierarchy dumps. */
export function isSystemUiPackage(pkg: string): boolean {
  const p = (pkg ?? '').trim();
  if (!p || p === 'android') return true;
  return SYSTEM_UI_PACKAGES.some(
    (prefix) => p === prefix || p.startsWith(prefix)
  );
}

const HIERARCHY_BOUNDS_RE = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/;

export type HierarchyScreenDims = { dw: number; dh: number };
export type HierarchyBoundsTuple = [number, number, number, number];
export type StableHierarchySelectorBy =
  | 'resource-id'
  | 'text'
  | 'description'
  | 'xpath'
  | 'class name';
export type StableHierarchySelector = {
  by: StableHierarchySelectorBy;
  value: string;
  selectorReason: string;
  selectorVolatile: boolean;
  resourceIdDuplicateCount: number;
  textDuplicateCount: number;
  descDuplicateCount: number;
};
export type StableHierarchySelectorAttrs = {
  resourceId?: string;
  text?: string;
  contentDesc?: string;
  pkg?: string;
  className?: string;
  bounds?: string;
};
export type StableHierarchySelectorCounts = {
  resourceIdCount?: number;
  textCount?: number;
  descCount?: number;
};

/**
 * Infer the visible device coordinate space from all hierarchy bounds.
 *
 * Do not use the first `[0,0]` node: Android often emits status-bar/SystemUI
 * nodes before the app root, which would shrink the coordinate space to e.g.
 * 1080x80 and make XML-tree picks land far above the intended target.
 */
export function parseHierarchyScreenDims(
  allNodes: Element[],
  fallback: HierarchyScreenDims = { dw: 1080, dh: 1920 }
): HierarchyScreenDims {
  let maxRight = 0;
  let maxBottom = 0;

  for (const node of allNodes) {
    const m = HIERARCHY_BOUNDS_RE.exec(node.getAttribute('bounds') ?? '');
    if (!m) continue;
    const x1 = +m[1];
    const y1 = +m[2];
    const x2 = +m[3];
    const y2 = +m[4];
    if (x2 <= x1 || y2 <= y1) continue;
    maxRight = Math.max(maxRight, x2);
    maxBottom = Math.max(maxBottom, y2);
  }

  if (maxRight > 0 && maxBottom > 0) {
    return { dw: maxRight, dh: maxBottom };
  }
  return fallback;
}

export type HierarchyRatioToPointOptions = {
  /** Tap ratios from mirror/device — use device screen_width × screen_height. */
  screenDims?: HierarchyScreenDims;
  fallback?: HierarchyScreenDims;
};

function isHierarchyRatioToPointOptions(
  options: HierarchyScreenDims | HierarchyRatioToPointOptions | undefined
): options is HierarchyRatioToPointOptions {
  return (
    !!options &&
    typeof options === 'object' &&
    ('screenDims' in options || 'fallback' in options)
  );
}

export function hierarchyRatioToPoint(
  allNodes: Element[],
  rx: number,
  ry: number,
  options?: HierarchyScreenDims | HierarchyRatioToPointOptions
): { px: number; py: number; dw: number; dh: number } {
  const normalized: HierarchyRatioToPointOptions =
    isHierarchyRatioToPointOptions(options)
      ? options
      : options
        ? { fallback: options }
        : {};
  const inferred = parseHierarchyScreenDims(allNodes, normalized.fallback);
  const { dw, dh } = normalized.screenDims ?? inferred;
  return { px: rx * dw, py: ry * dh, dw, dh };
}

export function hierarchyBoundsCenterRatio(
  allNodes: Element[],
  bounds: HierarchyBoundsTuple | null,
  options?: HierarchyScreenDims | HierarchyRatioToPointOptions
): { rx: number; ry: number; dw: number; dh: number } | null {
  if (!bounds) return null;
  const [x1, y1, x2, y2] = bounds;
  if (x2 <= x1 || y2 <= y1) return null;
  const normalized: HierarchyRatioToPointOptions =
    isHierarchyRatioToPointOptions(options)
      ? options
      : options
        ? { fallback: options }
        : {};
  const inferred = parseHierarchyScreenDims(allNodes, normalized.fallback);
  const { dw, dh } = normalized.screenDims ?? inferred;
  if (dw <= 0 || dh <= 0) return null;
  return {
    rx: (x1 + x2) / 2 / dw,
    ry: (y1 + y2) / 2 / dh,
    dw,
    dh
  };
}

/**
 * Home/launcher grids reuse one resource-id for every cell (e.g. Samsung
 * `com.sec.android.app.launcher:id/icon`). Using resource-id taps the *first*
 * match in the XML, not the icon you picked — prefer text / content-desc.
 */
export function isAmbiguousLauncherResourceId(
  resourceId: string,
  pkg: string
): boolean {
  if (!resourceId || !resourceId.includes('/')) return false;
  if (
    !/:id\/(icon|label|title|icon_text|text|name|bubble_text)$/i.test(
      resourceId
    )
  ) {
    return false;
  }
  const prefixes = [
    'com.sec.android.app.launcher',
    'com.android.launcher',
    'com.google.android.apps.nexuslauncher',
    'com.miui.home',
    'com.huawei.android.launcher',
    'com.oppo.launcher',
    'com.vivo.launcher'
  ];
  return prefixes.some(
    (p) => pkg.startsWith(p) || resourceId.startsWith(`${p}:`)
  );
}

export function buildBoundsXPath(bounds: string): string | null {
  const b = bounds.trim();
  if (!HIERARCHY_BOUNDS_RE.test(b)) return null;
  return `//*[@bounds="${b}"]`;
}

export function pickStableHierarchySelector(
  attrs: StableHierarchySelectorAttrs,
  counts: StableHierarchySelectorCounts = {},
  options: { allowBoundsXPath?: boolean } = {}
): StableHierarchySelector | null {
  const rid = (attrs.resourceId ?? '').trim();
  const text = (attrs.text ?? '').trim();
  const desc = (attrs.contentDesc ?? '').trim();
  const pkg = (attrs.pkg ?? '').trim();
  const cls = (attrs.className ?? '').trim();
  const ambiguousLauncher = rid
    ? isAmbiguousLauncherResourceId(rid, pkg)
    : false;
  const ridUnique =
    !!rid &&
    !ambiguousLauncher &&
    !isGenericHierarchyResourceId(rid) &&
    (counts.resourceIdCount ?? 0) === 1;
  const textUnique =
    !!text && text.length < 500 && (counts.textCount ?? 0) === 1;
  const descUnique =
    !!desc && desc.length < 500 && (counts.descCount ?? 0) === 1;
  const withMeta = (
    by: StableHierarchySelectorBy,
    value: string,
    selectorReason: string,
    selectorVolatile: boolean
  ): StableHierarchySelector => ({
    by,
    value,
    selectorReason,
    selectorVolatile,
    resourceIdDuplicateCount: rid ? (counts.resourceIdCount ?? 0) : 0,
    textDuplicateCount: text ? (counts.textCount ?? 0) : 0,
    descDuplicateCount: desc ? (counts.descCount ?? 0) : 0
  });

  if (ambiguousLauncher && textUnique)
    return withMeta('text', text, 'unique text', false);
  if (ambiguousLauncher && descUnique) {
    return withMeta('description', desc, 'unique content-desc', false);
  }
  if (ridUnique)
    return withMeta('resource-id', rid, 'unique resource-id', false);
  if (descUnique)
    return withMeta('description', desc, 'unique content-desc', false);
  if (textUnique) return withMeta('text', text, 'unique text', false);

  if (options.allowBoundsXPath) {
    const xpath = buildBoundsXPath(attrs.bounds ?? '');
    if (xpath) return withMeta('xpath', xpath, 'bounds fallback', true);
  }

  if (cls && !isHierarchyLayoutContainer(cls)) {
    return withMeta('class name', cls, 'class fallback', true);
  }
  return null;
}

/**
 * The app package occupying the most screen area (ignoring system UI chrome).
 * Used to drop status bar / nav bar / launcher nodes when no explicit
 * targetPackage is supplied.
 */
export function inferForegroundPackage(allNodes: Element[]): string {
  let pkg = '';
  let bestArea = 0;
  for (const node of allNodes) {
    const p = (node.getAttribute('package') ?? '').trim();
    if (!p || isSystemUiPackage(p)) continue;
    const m = HIERARCHY_BOUNDS_RE.exec(node.getAttribute('bounds') ?? '');
    if (!m) continue;
    const area = (+m[3] - +m[1]) * (+m[4] - +m[2]);
    if (area > bestArea) {
      bestArea = area;
      pkg = p;
    }
  }
  return pkg;
}

/** FB / obfuscated dumps reuse these ids across the whole screen. */
export function isGenericHierarchyResourceId(resourceId: string): boolean {
  const rid = resourceId.trim();
  if (!rid) return true;
  if (rid.includes('(name removed)')) return true;
  if (/:id\/(list|content|root|container|main_layout)$/i.test(rid)) return true;
  return false;
}

export function isHierarchyLayoutContainer(className: string): boolean {
  const cls = className.trim();
  if (!cls) return false;
  if (HIERARCHY_CONTAINER_CLASSES.has(cls)) return true;
  const short = cls.includes('.') ? cls.slice(cls.lastIndexOf('.') + 1) : cls;
  return HIERARCHY_CONTAINER_SHORT.has(short);
}

export type HierarchyHitScoreInput = {
  depth: number;
  area: number;
  clickable: boolean;
  text: string;
  contentDesc: string;
  resourceId: string;
  className: string;
  resourceIdCount?: number;
};

/** Higher = better target for the user's tap (prefer deep, semantic, specific nodes). */
export function scoreHierarchyHit(input: HierarchyHitScoreInput): number {
  const { depth, area, clickable, text, contentDesc, resourceId, className } =
    input;
  const ridCount = input.resourceIdCount ?? 1;
  let score = depth * 600;

  if (contentDesc && contentDesc.length < 160) score += 5000;
  if (text && text.length < 120) score += 4200;

  if (
    resourceId &&
    !isGenericHierarchyResourceId(resourceId) &&
    ridCount === 1
  ) {
    score += 2800;
  } else if (
    resourceId &&
    !isGenericHierarchyResourceId(resourceId) &&
    ridCount > 1
  ) {
    score -= 2500;
  } else if (isGenericHierarchyResourceId(resourceId)) {
    score -= 4000;
  }

  if (clickable) score += 900;

  if (isHierarchyLayoutContainer(className) && !text && !contentDesc) {
    score -= 8000;
  }

  // Smaller bounds = more specific hit target.
  score -= area / 80_000;
  return score;
}
