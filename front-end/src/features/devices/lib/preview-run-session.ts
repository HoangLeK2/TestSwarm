/** Tracks the active preview-stream trace without cross-run races. */

export type ActivePreviewTrace = {
  serial: string;
  traceId: string;
  runId: number;
};

type PreviewEvent = { event: string; trace_id?: string; [key: string]: unknown };

export function createPreviewRunSession(
  activeRef: { current: ActivePreviewTrace | null },
  runIdRef: { current: number },
) {
  const beginRun = () => ++runIdRef.current;

  const onStreamStart = (runId: number, serial: string, traceId: string) => {
    activeRef.current = { serial, traceId, runId };
  };

  const onStreamEnd = (runId: number) => {
    if (activeRef.current?.runId === runId) {
      activeRef.current = null;
    }
  };

  const takeActiveForCancel = (): ActivePreviewTrace | null => {
    const active = activeRef.current;
    activeRef.current = null;
    return active;
  };

  const makeStreamHandler = (
    runId: number,
    serial: string,
    onEvent?: (ev: PreviewEvent) => void,
  ) => (ev: PreviewEvent) => {
    if (ev.event === 'start' && typeof ev.trace_id === 'string') {
      onStreamStart(runId, serial, ev.trace_id);
    } else if (ev.event === 'done' || ev.event === 'error') {
      onStreamEnd(runId);
    }
    onEvent?.(ev);
  };

  return {
    beginRun,
    onStreamEnd,
    takeActiveForCancel,
    makeStreamHandler,
  };
}
