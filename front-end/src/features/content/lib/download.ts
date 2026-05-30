/** Parse filename from Content-Disposition response header. */
export function filenameFromContentDisposition(
  header: string | undefined
): string | null {
  if (!header) return null;
  const utf8 = /filename\*=UTF-8''([^;\n]+)/i.exec(header);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      return utf8[1].trim();
    }
  }
  const plain = /filename="([^"]+)"/i.exec(header);
  if (plain?.[1]) return plain[1];
  const loose = /filename=([^;\n]+)/i.exec(header);
  return loose?.[1]?.trim().replace(/^["']|["']$/g, '') ?? null;
}

export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
