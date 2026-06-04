export function readCssHslVariable(name: `--${string}`): string {
  if (typeof window === 'undefined') return '';
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return raw ? `hsl(${raw})` : '';
}

export type AnalyticsChartTheme = {
  total: string;
  failures: string;
  mutedForeground: string;
  border: string;
};

export function readAnalyticsChartTheme(): AnalyticsChartTheme {
  return {
    total: readCssHslVariable('--chart-1'),
    failures: readCssHslVariable('--chart-5'),
    mutedForeground: readCssHslVariable('--muted-foreground'),
    border: readCssHslVariable('--border')
  };
}
