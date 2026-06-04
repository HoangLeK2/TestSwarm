/** Shared DLQ status badge styling for list + detail drawer. */
export function dlqStatusVariant(
  status: string
): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'pending') return 'destructive';
  if (status === 'retrying') return 'default';
  if (status === 'replayed' || status === 'resolved') return 'secondary';
  if (status === 'closed' || status === 'dismissed') return 'outline';
  return 'outline';
}

export function dlqStatusLabel(
  status: string,
  t: (key: string) => string
): string {
  if (status === 'pending') return t('monitorDlqStatusPending');
  if (status === 'retrying') return t('monitorDlqStatusRetrying');
  if (status === 'replayed') return t('monitorDlqStatusReplayed');
  if (status === 'closed') return t('monitorDlqStatusClosed');
  if (status === 'resolved') return t('monitorDlqStatusResolved');
  if (status === 'dismissed') return t('monitorDlqStatusDismissed');
  return status;
}
