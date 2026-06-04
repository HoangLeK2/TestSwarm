/**
 * Drop export `checksum` before upload so edited portable files import without
 * CHECKSUM_MISMATCH (users should not edit raw export files manually).
 */
export async function prepareImportScenarioFile(
  file: File
): Promise<{ file: File; strippedChecksum: boolean }> {
  const text = await file.text();
  const trimmed = text.trimStart();
  const isJson =
    file.name.toLowerCase().endsWith('.json') || trimmed.startsWith('{');

  if (isJson) {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      if (parsed && typeof parsed === 'object' && 'checksum' in parsed) {
        delete parsed.checksum;
        const body = JSON.stringify(parsed, null, 2);
        return {
          file: new File([body], file.name, {
            type: file.type || 'application/json'
          }),
          strippedChecksum: true
        };
      }
    } catch {
      // fall through — send original bytes
    }
    return { file, strippedChecksum: false };
  }

  // YAML / YML — remove a single root-level checksum line if present
  const withoutChecksum = text.replace(
    /^checksum:\s*(?:['"][^'"]*['"]|[^\n]+)\s*\n?/m,
    ''
  );
  if (withoutChecksum !== text) {
    return {
      file: new File([withoutChecksum], file.name, { type: file.type }),
      strippedChecksum: true
    };
  }

  return { file, strippedChecksum: false };
}
