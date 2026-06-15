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

  if (
    isHierarchyLayoutContainer(className) &&
    !text &&
    !contentDesc
  ) {
    score -= 8000;
  }

  // Smaller bounds = more specific hit target.
  score -= area / 80_000;
  return score;
}
