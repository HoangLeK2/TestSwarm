import type { AxiosResponse } from 'axios';

function probeText(blob: Blob, max = 2048): Promise<string> {
  return blob.slice(0, Math.min(blob.size, max)).text();
}

function looksLikeScenarioExportPayload(probe: string): boolean {
  const t = probe.trimStart();
  if (t.includes('schema_version')) return true;
  if (t.includes('"scenario"') || t.includes("'scenario'")) return true;
  if (/^scenario\s*:/m.test(t)) return true;
  return false;
}

function looksLikeFastApiErrorPayload(probe: string): boolean {
  const t = probe.trimStart();
  if (!t.startsWith('{') && !t.startsWith('[')) return false;
  if (looksLikeScenarioExportPayload(probe)) return false;
  return t.includes('"detail"') || t.includes("'detail'");
}

async function throwFromApiErrorBlob(blob: Blob): Promise<never> {
  const full = await blob.text();
  try {
    const parsed = JSON.parse(full) as {
      detail?: unknown;
      message?: string;
    };
    const detail = parsed.detail;
    if (typeof detail === 'string' && detail.trim()) {
      throw new Error(detail.trim());
    }
    if (
      detail != null &&
      typeof detail === 'object' &&
      !Array.isArray(detail)
    ) {
      const msg = (detail as { message?: string }).message;
      const code = (detail as { code?: string }).code;
      if (msg?.trim()) {
        throw new Error(code ? `${code}: ${msg.trim()}` : msg.trim());
      }
    }
    if (typeof parsed.message === 'string' && parsed.message.trim()) {
      throw new Error(parsed.message.trim());
    }
  } catch (err) {
    if (err instanceof Error && !err.message.startsWith('Unexpected')) {
      throw err;
    }
  }
  throw new Error('EXPORT_API_ERROR');
}

/** Ensure a scenario export response is a non-empty YAML/JSON blob, not an API error body. */
export async function blobFromExportResponse(
  response: AxiosResponse<Blob>,
  format: 'yaml' | 'json' = 'yaml'
): Promise<Blob> {
  const data = response.data;
  if (!(data instanceof Blob)) {
    throw new Error('EXPORT_INVALID_RESPONSE');
  }
  if (data.size === 0) {
    throw new Error('EXPORT_EMPTY_FILE');
  }

  const contentType = String(response.headers['content-type'] ?? '').toLowerCase();
  if (contentType.includes('yaml') || contentType.includes('x-yaml')) {
    return data;
  }
  if (format === 'json' && contentType.includes('json')) {
    return data;
  }

  const probe = await probeText(data);
  const trimmed = probe.trimStart();

  if (looksLikeScenarioExportPayload(probe)) {
    return data;
  }

  if (trimmed.startsWith('<!') || trimmed.toLowerCase().startsWith('<html')) {
    throw new Error('EXPORT_HTML_ERROR');
  }

  if (looksLikeFastApiErrorPayload(probe)) {
    return throwFromApiErrorBlob(data);
  }

  if (format === 'yaml' && (trimmed.startsWith('{') || trimmed.startsWith('['))) {
    return throwFromApiErrorBlob(data);
  }

  return data;
}

/** Parse FastAPI JSON `detail` when axios stored error body as Blob (responseType: blob). */
export async function farmApiDetailFromError(err: unknown): Promise<unknown> {
  const e = err as {
    response?: { data?: unknown };
  };
  const data = e.response?.data;
  if (!(data instanceof Blob)) {
    return (data as { detail?: unknown } | undefined)?.detail;
  }
  try {
    const text = await data.text();
    const parsed = JSON.parse(text) as { detail?: unknown };
    return parsed.detail;
  } catch {
    return undefined;
  }
}
