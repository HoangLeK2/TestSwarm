export const DEVICE_GRID_TILE_WIDTH_PX = 288;
export const DEVICE_GRID_GAP_PX = 16;
export const DEVICE_GRID_ESTIMATED_ROW_HEIGHT_PX = 570;

export function getDeviceGridColumnCount(
  containerWidth: number,
  itemCount: number
): number {
  const availableWidth = Math.max(0, containerWidth);
  const availableColumns = Math.max(
    1,
    Math.floor(
      (availableWidth + DEVICE_GRID_GAP_PX) /
        (DEVICE_GRID_TILE_WIDTH_PX + DEVICE_GRID_GAP_PX)
    )
  );
  const boundedItemCount = Math.max(1, Math.floor(itemCount));
  return Math.min(availableColumns, boundedItemCount);
}

export function getDeviceGridRowCount(
  itemCount: number,
  columnCount: number
): number {
  const safeItemCount = Math.max(0, Math.floor(itemCount));
  const safeColumnCount = Math.max(1, Math.floor(columnCount));
  return Math.ceil(safeItemCount / safeColumnCount);
}

export function getDeviceGridRowBounds(
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
