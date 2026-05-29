export function serialToId(s: string): string {
  return s.replace(/:/g, '-');
}
