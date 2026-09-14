export const FOLLOWER_GRID_GAP_PX = 8;

/** Columns are bounded by the available width only — the grid fills the stage. */
export function getFollowerGridColumnCount(
  containerWidth: number,
  itemCount: number,
  itemWidth: number
): number {
  const availableWidth = Math.max(0, containerWidth);
  const safeItemWidth = Math.max(1, itemWidth);
  const availableColumns = Math.max(
    1,
    Math.floor(
      (availableWidth + FOLLOWER_GRID_GAP_PX) /
        (safeItemWidth + FOLLOWER_GRID_GAP_PX)
    )
  );
  const boundedItemCount = Math.max(1, Math.floor(itemCount));
  return Math.min(availableColumns, boundedItemCount);
}

export function getFollowerGridRowCount(
  itemCount: number,
  columnCount: number
): number {
  const safeItemCount = Math.max(0, Math.floor(itemCount));
  const safeColumnCount = Math.max(1, Math.floor(columnCount));
  return Math.ceil(safeItemCount / safeColumnCount);
}

export function getFollowerGridRowBounds(
  rowIndex: number,
  columnCount: number,
  itemCount: number
): { start: number; end: number } {
  const safeItemCount = Math.max(0, Math.floor(itemCount));
  const safeColumnCount = Math.max(1, Math.floor(columnCount));
  const start = Math.min(
    safeItemCount,
    Math.max(0, Math.floor(rowIndex)) * safeColumnCount
  );
  return {
    start,
    end: Math.min(safeItemCount, start + safeColumnCount)
  };
}
