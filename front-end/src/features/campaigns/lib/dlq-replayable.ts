import type { DlqEntry } from '../types';

const TERMINAL_STATUSES = new Set([
  'closed',
  'dismissed',
  'replayed',
  'resolved'
]);

/** Mirrors backend replay eligibility when `replayable` is not exposed on DlqEntry. */
export function isDlqEntryReplayable(entry: DlqEntry): boolean {
  if (TERMINAL_STATUSES.has(entry.status)) return false;
  if (entry.status === 'retrying') return false;
  if (entry.close_reason?.trim()) return false;
  return entry.status === 'pending' || entry.status === 'failed';
}

export function dlqReplayBlockedReason(
  entry: DlqEntry,
  t: (key: string) => string
): string | null {
  if (isDlqEntryReplayable(entry)) return null;
  if (entry.status === 'retrying') return t('monitorDlqReplayBlockedRetrying');
  if (entry.status === 'closed' || entry.status === 'dismissed') {
    return t('monitorDlqReplayBlockedClosed');
  }
  if (entry.status === 'replayed' || entry.status === 'resolved') {
    return t('monitorDlqReplayBlockedResolved');
  }
  return t('monitorDlqReplayBlockedGeneric');
}
