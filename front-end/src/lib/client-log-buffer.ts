'use client';

type LogLevel = 'log' | 'info' | 'warn' | 'error';

interface LogEntry {
  level: LogLevel;
  message: string;
  timestamp: number;
}

let isCapturing = false;
const logBuffer: LogEntry[] = [];
let originalConsole: Partial<
  Record<LogLevel, (...args: unknown[]) => void>
> | null = null;

function formatArgsToString(args: unknown[]): string {
  try {
    return args
      .map((a) => {
        if (a instanceof Error)
          return `${a.name}: ${a.message}\n${a.stack ?? ''}`;
        if (typeof a === 'string') return a;
        return JSON.stringify(a, null, 2);
      })
      .join(' ');
  } catch (_err) {
    return args.map((a) => String(a)).join(' ');
  }
}

export function enableConsoleCapture(): void {
  if (isCapturing || typeof window === 'undefined') return;
  isCapturing = true;

  originalConsole = {
    log: console.log.bind(console),
    info: console.info.bind(console),
    warn: console.warn.bind(console),
    error: console.error.bind(console)
  };
  (['log', 'info', 'warn', 'error'] as LogLevel[]).forEach((level) => {
    console[level] = ((...args: unknown[]) => {
      const message = formatArgsToString(args);
      logBuffer.push({ level, message, timestamp: Date.now() });
      if (logBuffer.length > 500) logBuffer.shift();
      // forward to original
      originalConsole?.[level]?.(...(args as []));
    }) as typeof console.log;
  });

  window.addEventListener('error', (ev) => {
    const err = ev.error as Error | undefined;
    const message = err
      ? `${err.name}: ${err.message}\n${err.stack ?? ''}`
      : ev.message;
    logBuffer.push({ level: 'error', message, timestamp: Date.now() });
  });

  window.addEventListener('unhandledrejection', (ev) => {
    const reason = (ev as PromiseRejectionEvent).reason;
    const message =
      reason instanceof Error
        ? `${reason.name}: ${reason.message}\n${reason.stack ?? ''}`
        : typeof reason === 'string'
          ? reason
          : JSON.stringify(reason);
    logBuffer.push({ level: 'error', message, timestamp: Date.now() });
  });
}

export function getCapturedLogs(): ReadonlyArray<LogEntry> {
  return logBuffer.slice();
}

export function clearCapturedLogs(): void {
  logBuffer.length = 0;
}
