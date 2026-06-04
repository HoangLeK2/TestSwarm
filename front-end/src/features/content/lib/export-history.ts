import type { ContentFilters, ExportFormat } from '../services/api';

export type ContentExportJobStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type ContentExportJobRecord = {
  id: string;
  status: ContentExportJobStatus;
  format: ExportFormat;
  filterSnapshot: ContentFilters;
  itemCountEstimate?: number | null;
  createdAt: string;
  completedAt?: string | null;
  createdBy?: string | null;
  error?: string | null;
  filename?: string | null;
  /** Stream exports complete immediately — no expiry URL. */
  downloadExpired?: boolean;
};

const STORAGE_KEY = 'device-farm:content-export-history';
const MAX_RECORDS = 30;

export function listExportHistory(): ContentExportJobRecord[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ContentExportJobRecord[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveExportHistory(records: ContentExportJobRecord[]): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(records.slice(0, MAX_RECORDS))
  );
}

export function appendExportJob(record: ContentExportJobRecord): void {
  saveExportHistory([record, ...listExportHistory()]);
}

export function updateExportJob(
  id: string,
  patch: Partial<ContentExportJobRecord>
): void {
  const next = listExportHistory().map((row) =>
    row.id === id ? { ...row, ...patch } : row
  );
  saveExportHistory(next);
}

export function getExportJob(id: string): ContentExportJobRecord | null {
  return listExportHistory().find((row) => row.id === id) ?? null;
}
