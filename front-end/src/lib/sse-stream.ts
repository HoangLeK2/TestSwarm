/**
 * Browser SSE reader over fetch (supports Authorization headers).
 */

export type SseMessage = {
  id?: string;
  event?: string;
  data?: string;
};

export type SseStreamOptions = {
  url: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  lastEventId?: string;
  onMessage: (msg: SseMessage) => void;
  onOpen?: () => void;
};

export async function consumeSseStream(options: SseStreamOptions): Promise<void> {
  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
    ...options.headers
  };
  if (options.lastEventId) {
    headers['Last-Event-ID'] = options.lastEventId;
  }

  const response = await fetch(options.url, {
    method: 'GET',
    headers,
    signal: options.signal,
    credentials: 'same-origin'
  });

  if (!response.ok || !response.body) {
    throw new Error(`SSE error: ${response.status}`);
  }

  options.onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';

    for (const block of blocks) {
      if (!block.trim()) continue;

      let id: string | undefined;
      let event: string | undefined;
      const dataLines: string[] = [];

      for (const line of block.split('\n')) {
        if (!line || line.startsWith(':')) continue;
        if (line.startsWith('id:')) {
          id = line.slice(3).trim();
        } else if (line.startsWith('event:')) {
          event = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart());
        }
      }

      if (dataLines.length > 0) {
        options.onMessage({ id, event, data: dataLines.join('\n') });
      }
    }
  }
}
