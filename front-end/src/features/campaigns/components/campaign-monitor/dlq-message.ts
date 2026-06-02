import type { DlqEntry } from '../../types';

/** Prefer the most informative DLQ text (error often has DB detail failure_reason omits). */
export function dlqDisplayMessage(
  entry: DlqEntry,
  fallback: string
): string {
  const error = entry.error?.trim() || '';
  const reason = entry.failure_reason?.trim() || '';
  if (error && reason) {
    return error.length >= reason.length ? error : reason;
  }
  return error || reason || fallback;
}
