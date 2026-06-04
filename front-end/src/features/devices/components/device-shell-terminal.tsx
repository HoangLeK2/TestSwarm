'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { cn } from '@/lib/utils';

export type DeviceShellResult = {
  ok: boolean;
  cmd: string;
  output?: string | null;
  error?: string;
  note?: string;
};

const PROMPT = '$ ';

const TERMINAL_THEME = {
  background: '#0d1117',
  foreground: '#e6edf3',
  cursor: '#58a6ff',
  cursorAccent: '#0d1117',
  selectionBackground: '#264f78',
  black: '#484f58',
  red: '#ff7b72',
  green: '#3fb950',
  yellow: '#d29922',
  blue: '#58a6ff',
  magenta: '#bc8cff',
  cyan: '#39c5cf',
  white: '#e6edf3',
  brightBlack: '#6e7681',
  brightRed: '#ffa198',
  brightGreen: '#56d364',
  brightYellow: '#e3b341',
  brightBlue: '#79c0ff',
  brightMagenta: '#d2a8ff',
  brightCyan: '#56d4dd',
  brightWhite: '#ffffff'
} as const;

type Props = {
  className?: string;
  disabled?: boolean;
  onRunCommand: (cmd: string) => Promise<DeviceShellResult | void>;
  /** Exposed for parent toolbar (clear screen). */
  onReady?: (api: { clear: () => void }) => void;
};

export function DeviceShellTerminal({
  className,
  disabled = false,
  onRunCommand,
  onReady
}: Props) {
  const tRun = useTranslations('devicesControlRecord.deviceOps');
  const containerRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const inputRef = useRef('');
  const runningRef = useRef(false);
  const disabledRef = useRef(disabled);
  const onRunRef = useRef(onRunCommand);

  disabledRef.current = disabled;
  onRunRef.current = onRunCommand;

  const writePrompt = useCallback((term: Terminal) => {
    term.write(`\x1b[32m${PROMPT}\x1b[0m`);
  }, []);

  const writeln = useCallback((term: Terminal, text: string, color?: string) => {
    const prefix = color ? `\x1b[${color}m` : '';
    const suffix = color ? '\x1b[0m' : '';
    const normalized = text.replace(/\r?\n/g, '\r\n');
    term.write(`${prefix}${normalized}${suffix}\r\n`);
  }, []);

  const clearTerminal = useCallback(() => {
    const term = termRef.current;
    if (!term) return;
    term.clear();
    inputRef.current = '';
    writeln(term, tRun('shellWelcome'), '90');
    writePrompt(term);
    term.focus();
  }, [tRun, writeln, writePrompt]);

  useEffect(() => {
    onReady?.({ clear: clearTerminal });
  }, [clearTerminal, onReady]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const term = new Terminal({
      cursorBlink: true,
      cursorStyle: 'block',
      fontFamily:
        'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 14,
      lineHeight: 1.35,
      scrollback: 5000,
      theme: TERMINAL_THEME
    });

    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(el);
    fit.fit();

    termRef.current = term;
    fitRef.current = fit;

    writeln(term, tRun('shellWelcome'), '90');
    writePrompt(term);

    const runCommand = async (raw: string) => {
      const cmd = raw.trim();
      if (!cmd) {
        writePrompt(term);
        return;
      }
      if (runningRef.current || disabledRef.current) {
        writePrompt(term);
        return;
      }

      runningRef.current = true;
      try {
        const result = await onRunRef.current(cmd);
        if (!result) {
          writeln(term, tRun('shellStepSubmitted'), '90');
        } else {
          if (result.output) {
            writeln(term, result.output);
          }
          if (result.note) {
            writeln(term, result.note, '90');
          }
          if (!result.ok && result.error) {
            writeln(term, result.error, '31');
          }
        }
      } catch (e) {
        writeln(term, String(e), '31');
      } finally {
        runningRef.current = false;
        writePrompt(term);
      }
    };

    const disposable = term.onData((data) => {
      if (runningRef.current || disabledRef.current) return;

      if (data === '\r') {
        term.write('\r\n');
        const cmd = inputRef.current;
        inputRef.current = '';
        void runCommand(cmd);
        return;
      }

      if (data === '\u007F') {
        if (inputRef.current.length > 0) {
          inputRef.current = inputRef.current.slice(0, -1);
          term.write('\b \b');
        }
        return;
      }

      if (data === '\u0003') {
        inputRef.current = '';
        term.write('^C\r\n');
        writePrompt(term);
        return;
      }

      if (data === '\u000c') {
        term.clear();
        inputRef.current = '';
        writeln(term, tRun('shellWelcome'), '90');
        writePrompt(term);
        return;
      }

      // Paste / printable UTF-8 (skip most C0 controls)
      if (data.charCodeAt(0) < 32 && data !== '\t') return;

      inputRef.current += data;
      term.write(data);
    });

    const ro = new ResizeObserver(() => {
      try {
        fit.fit();
      } catch {
        /* fit before layout */
      }
    });
    ro.observe(el);

    const focusTimer = window.setTimeout(() => term.focus(), 80);

    return () => {
      window.clearTimeout(focusTimer);
      ro.disconnect();
      disposable.dispose();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, [tRun, writeln, writePrompt]);

  return (
    <div
      className={cn(
        'min-h-0 flex-1 overflow-hidden rounded-lg border border-zinc-800 bg-[#0d1117] p-1 shadow-inner',
        disabled && 'pointer-events-none opacity-60',
        className
      )}
    >
      <div
        ref={containerRef}
        className='h-full min-h-[320px] w-full [&_.xterm]:h-full [&_.xterm-viewport]:!overflow-y-auto'
      />
    </div>
  );
}
