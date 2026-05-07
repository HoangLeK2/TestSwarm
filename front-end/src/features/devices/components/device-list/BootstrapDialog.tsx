'use client';

import { useState } from 'react';
import { RefreshCw, Video, Zap } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { toast } from 'sonner';
import type { DeviceOut } from '../../services/manage-api';
import { deviceControlApi } from '../../services/manage-api';

type Cmd = 'bootstrap' | 'restart_u2' | 'restart_scrcpy';

const CMD_CONFIG: Record<Cmd, { label: string; icon: React.ReactNode; description: string; timeout: number }> = {
  bootstrap: {
    label: 'Bootstrap',
    icon: <Zap size={12} />,
    description: 'Các thao tác cần thiết để thiết bị có thể hoạt động.',
    timeout: 60,
  },
  restart_u2: {
    label: 'Restart u2',
    icon: <RefreshCw size={12} />,
    description: 'Khởi động lại uiautomator2 server trên thiết bị.',
    timeout: 30,
  },
  restart_scrcpy: {
    label: 'Restart Stream',
    icon: <Video size={12} />,
    description: 'Dừng và khởi động lại luồng truyền hình cho thiết bị.',
    timeout: 20,
  },
};

function RunningState({ cmd, onDone }: { cmd: Cmd; onDone: () => void }) {
  const cfg = CMD_CONFIG[cmd];
  const [elapsed, setElapsed] = useState(0);

  useState(() => {
    const start = Date.now();
    const iv = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 500);
    return () => clearInterval(iv);
  });

  const pct = Math.min(100, Math.round((elapsed / cfg.timeout) * 100));

  return (
    <div className='space-y-3 py-2'>
      <div className='flex items-center gap-2 text-sm text-muted-foreground'>
        <RefreshCw size={14} className='animate-spin' />
        <span>Đang chạy {cfg.label}… ({elapsed}s / {cfg.timeout}s)</span>
      </div>
      <Progress value={pct} className='h-2' />
    </div>
  );
}

export function DeviceCmdButton({
  device,
  cmd,
}: {
  device: DeviceOut;
  cmd: Cmd;
}) {
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const cfg = CMD_CONFIG[cmd];

  const handleRun = async () => {
    setRunning(true);
    const toastId = toast.loading(`${cfg.label}: đang chạy…`);
    try {
      const fnMap: Record<Cmd, (id: string) => Promise<any>> = {
        bootstrap:      deviceControlApi.bootstrap,
        restart_u2:     deviceControlApi.restartU2,
        restart_scrcpy: deviceControlApi.restartScrcpy,
      };
      const fn = fnMap[cmd];
      const res = await fn(device.id);
      if (res.ok) {
        toast.success(`${cfg.label}: thành công`, { id: toastId });
      } else {
        toast.error(`${cfg.label}: ${res.error || 'thất bại'}`, { id: toastId, description: res.output });
      }
    } catch (e: any) {
      toast.error(`${cfg.label}: ${e?.message || 'lỗi'}`, { id: toastId });
    } finally {
      setRunning(false);
      setOpen(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button size='sm' variant='outline' className='h-7 px-2 text-[11px]' disabled={running} title={cfg.label}>
          {cfg.icon}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className='flex items-center gap-2'>
            {cfg.icon}
            {cfg.label} — {device.name || device.serial}
          </AlertDialogTitle>
          <AlertDialogDescription>{cfg.description}</AlertDialogDescription>
        </AlertDialogHeader>

        {running && <RunningState cmd={cmd} onDone={() => {}} />}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={running}>Huỷ</AlertDialogCancel>
          {!running && (
            <AlertDialogAction onClick={(e) => { e.preventDefault(); handleRun(); }}>
              Chạy
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
