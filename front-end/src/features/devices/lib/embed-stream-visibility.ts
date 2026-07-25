export function shouldRunEmbedStream({
  readOnlyPreview,
  nearViewport
}: {
  readOnlyPreview: boolean;
  nearViewport: boolean;
}): boolean {
  return !readOnlyPreview || nearViewport;
}
