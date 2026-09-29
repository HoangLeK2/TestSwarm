import type { useTranslations } from 'next-intl';

type RunResultTranslator = ReturnType<typeof useTranslations>;

function quotedField(message: string, fieldNames: string[]): string | null {
  for (const field of fieldNames) {
    const escaped = field.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const match = message.match(new RegExp(`${escaped}=['"]([^'"]+)['"]`, 'i'));
    if (match?.[1]) return match[1];
  }
  return null;
}

export function humanizeStepRunMessage(
  message: string | undefined,
  t: RunResultTranslator
): string | null {
  const text = message?.trim();
  if (!text) return null;

  if (text.includes('comment_sheet_not_open')) {
    return t('messages.commentSheetNotOpen');
  }

  if (/^edge\s+extra_data\s+failed:/i.test(text)) {
    return t('messages.extraDataFailed');
  }

  if (
    /require_verified_target\s*=.*was not verified by a target resolver/i.test(
      text
    )
  ) {
    return t('messages.verifiedTargetMissing');
  }

  if (/^scroll_to\s+found\b/i.test(text)) {
    const target = quotedField(text, [
      'description',
      'text',
      'content-desc',
      'contentDescription',
      'resource-id',
      'resourceId'
    ]);
    const count = Number(text.match(/after\s+(\d+)\s+swipe\(s\)/i)?.[1] ?? 0);
    if (target && count > 0) {
      return t('messages.scrollToFoundWithTarget', { target, count });
    }
    if (target) return t('messages.scrollToFoundTargetOnly', { target });
    if (count > 0) return t('messages.scrollToFound', { count });
  }

  if (/selector\s+not\s+found|element\s+not\s+found/i.test(text)) {
    return t('messages.selectorNotFound');
  }

  if (/timeout|timed out/i.test(text)) {
    return t('messages.timeout');
  }

  return null;
}
