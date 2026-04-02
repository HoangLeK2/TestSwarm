'use client';

import { useState } from 'react';
import { CheckCircle2, XCircle, Pause, Loader2, Clock, ChevronDown, ChevronRight, Smartphone, List } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Progress } from '@/components/ui/progress';
import { DeviceControlEmbed } from '@/features/devices/components/device-control-embed';
import { useWorkflowProgress } from '../../hooks/use-campaigns';
import type { WorkflowInfo } from '../../types';
import { getStepTypeName } from '../flow-editor/constants';
import { WorkflowStepList } from '../workflow-step-list';

// ── Helpers ──────────────────────────────────────────────────────────────────

function parseSerial(workflowId: string): string {
  const m = workflowId.match(/^campaign:[^:]+:device:(.+):scenario:[^:]+$/);
  return m ? m[1] : workflowId;
}

function parseScenarioId(workflowId: string): string {
  const m = workflowId.match(/:scenario:([^:]+)$/);
  return m ? m[1] : '';
}

// ── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { icon: React.ReactNode; cls: string; label: string }> = {
    RUNNING: {
      icon: <Loader2 size={10} className='animate-spin' />,
      cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
      label: 'Đang chạy',
    },
    COMPLETED: {
      icon: <CheckCircle2 size={10} />,
      cls: 'bg-green-500/15 text-green-600 dark:text-green-400',
      label: 'Hoàn thành',
    },
    FAILED: {
      icon: <XCircle size={10} />,
      cls: 'bg-red-500/15 text-red-600 dark:text-red-400',
      label: 'Thất bại',
    },
    PAUSED: {
      icon: <Pause size={10} />,
      cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
      label: 'Tạm dừng',
    },
    CANCELLED: {
      icon: <XCircle size={10} />,
      cls: 'bg-muted text-muted-foreground',
      label: 'Đã hủy',
    },
    TERMINATED: {
      icon: <XCircle size={10} />,
      cls: 'bg-muted text-muted-foreground',
      label: 'Kết thúc',
    },
  };
  const c = cfg[status] ?? { icon: <Clock size={10} />, cls: 'bg-muted text-muted-foreground', label: status };
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-bold', c.cls)}>
      {c.icon}
      {c.label}
    </span>
  );
}

// ── Step dots ─────────────────────────────────────────────────────────────────

function StepDots({ current, total }: { current: number; total: number }) {
  if (total === 0) return null;
  const MAX = 20;
  const dots = total <= MAX ? total : MAX;
  const ratio = total <= MAX ? 1 : total / MAX;
  return (
    <div className='flex items-center gap-[2px]'>
      {Array.from({ length: dots }).map((_, i) => {
        const stepIdx = Math.round(i * ratio);
        const done = stepIdx < current;
        const active = stepIdx === current;
        return (
          <div
            key={i}
            className={cn(
              'h-1.5 rounded-full transition-all',
              active ? 'w-3 bg-primary' : done ? 'w-1.5 bg-primary/60' : 'w-1.5 bg-muted',
            )}
          />
        );
      })}
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

interface Props {
  wf: WorkflowInfo;
}

export function WorkflowProgressCard({ wf }: Props) {
  const [expanded, setExpanded] = useState(false);

  const isActive = wf.status === 'RUNNING' || wf.status === 'PAUSED';
  const { data: prog } = useWorkflowProgress(wf.workflow_id, isActive);

  const serial = parseSerial(wf.workflow_id);
  const scenarioId = parseScenarioId(wf.workflow_id);

  const current = prog?.current_step ?? 0;
  const total = prog?.total_steps ?? 0;
  const pct = total > 0 ? Math.round((current / total) * 100) : wf.status === 'COMPLETED' ? 100 : 0;
  const stepType = prog?.current_step_type ?? '';
  const message = prog?.message ?? '';
  const loopIter = prog?.loop_iteration != null && prog.loop_iteration >= 0 ? prog.loop_iteration : null;

  return (
    <div className={cn('transition-colors', expanded && 'bg-accent/20')}>
      {/* ── Summary row (always visible, clickable) ── */}
      <button
        type='button'
        className='w-full px-4 py-3 text-left hover:bg-accent/40 transition-colors'
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Row 1: chevron + serial + status */}
        <div className='flex items-center gap-2 mb-2'>
          {expanded
            ? <ChevronDown size={12} className='shrink-0 text-muted-foreground' />
            : <ChevronRight size={12} className='shrink-0 text-muted-foreground' />
          }
          <Smartphone size={11} className='shrink-0 text-muted-foreground' />
          <span className='font-mono text-[11px] font-semibold truncate flex-1' title={serial}>
            {serial}
          </span>
          {scenarioId && (
            <span className='text-[9px] text-muted-foreground font-mono shrink-0' title={scenarioId}>
              #{scenarioId.slice(0, 8)}
            </span>
          )}
          <StatusBadge status={wf.status} />
        </div>

        {/* Row 2: progress bar + counter */}
        <div className='flex items-center gap-2 mb-1.5 pl-[26px]'>
          <Progress
            value={pct}
            className={cn(
              'h-1.5 flex-1',
              wf.status === 'FAILED' && '[&>div]:bg-destructive',
              wf.status === 'PAUSED' && '[&>div]:bg-amber-500',
              wf.status === 'COMPLETED' && '[&>div]:bg-green-500',
            )}
          />
          <span className='text-[10px] tabular-nums text-muted-foreground shrink-0'>
            {total > 0 ? `${current}/${total}` : pct > 0 ? `${pct}%` : '—'}
          </span>
        </div>

        {/* Row 3: step dots */}
        {total > 0 && (
          <div className='pl-[26px] mb-1.5'>
            <StepDots current={current} total={total} />
          </div>
        )}

        {/* Row 4: current step type + message */}
        {isActive && (
          <div className='flex items-center gap-1.5 pl-[26px] text-[10px] text-muted-foreground'>
            {stepType && (
              <span className='rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-bold text-primary'>
                {getStepTypeName(stepType)}
              </span>
            )}
            {loopIter !== null && (
              <span className='text-[9px]'>vòng #{loopIter + 1}</span>
            )}
            {message && (
              <span className='truncate flex-1 italic' title={message}>{message}</span>
            )}
          </div>
        )}

        {wf.status === 'FAILED' && message && (
          <p className='mt-1 pl-[26px] text-[10px] text-destructive truncate' title={message}>
            {message}
          </p>
        )}
      </button>

      {/* ── Expanded: device left + steps right ── */}
      {expanded && (
        <div className='border-t bg-card overflow-hidden'>
          <div className='flex min-h-0 divide-x overflow-x-auto'>
            <div className='w-[220px] shrink-0 p-2'>
              <DeviceControlEmbed initialSerial={serial} compact hideStepMonitor />
            </div>
            <div className='min-w-0 flex-1 px-3 py-3'>
              <p className='mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
                <List size={10} /> Các bước
              </p>
              <WorkflowStepList wf={wf} maxHeight='400px' />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
