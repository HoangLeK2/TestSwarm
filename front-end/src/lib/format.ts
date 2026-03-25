export const getLocaleByNextLocale = (locale: string) => {
  return locale === 'vi' ? 'vi-VN' : 'en-US';
};

export function formatDate(
  date: Date | string | number | undefined,
  opts: Intl.DateTimeFormatOptions = {},
  locale: string = 'en-US'
) {
  if (!date) return '';

  try {
    return new Intl.DateTimeFormat(locale, {
      month: opts.month ?? 'long',
      day: opts.day ?? 'numeric',
      year: opts.year ?? 'numeric',
      ...opts
    }).format(new Date(date));
  } catch (_err) {
    return '';
  }
}

export function formatNumberDecimal(
  number: number,
  opts: { locale?: string; decimalPlaces?: number } = {}
) {
  const locale = opts.locale === 'vi' ? 'vi-VN' : 'en-US';
  return new Intl.NumberFormat(locale, {
    style: 'decimal'
  }).format(number);
}
