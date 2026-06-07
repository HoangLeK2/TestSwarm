import type { DlqEntry } from '../../types';

const DEFAULT_FALLBACK =
  'Execution failed without a recorded error message (inspect execution_steps / worker logs)';

/** Prefer API display_message, then the most informative DLQ text. */
export function dlqDisplayMessage(entry: DlqEntry, fallback: string): string {
  const display = entry.display_message?.trim() || '';
  if (display) return display;

  const error = entry.error?.trim() || '';
  const reason = entry.failure_reason?.trim() || '';
  if (error && reason) {
    return error.length >= reason.length ? error : reason;
  }
  const primary = error || reason;
  if (primary) return primary;

  const hints: string[] = [];
  if (entry.failed_step_id) {
    hints.push(`failed_step_id=${entry.failed_step_id}`);
  }
  if (entry.execution_id) {
    hints.push(`execution_id=${entry.execution_id}`);
  }
  const base = fallback.trim() || DEFAULT_FALLBACK;
  return hints.length > 0 ? `${base} (${hints.join(', ')})` : base;
}

export function dlqHasExplicitMessage(entry: DlqEntry): boolean {
  return Boolean(
    entry.display_message?.trim() ||
      entry.error?.trim() ||
      entry.failure_reason?.trim()
  );
}
