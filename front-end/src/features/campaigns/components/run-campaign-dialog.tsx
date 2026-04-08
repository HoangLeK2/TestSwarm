'use client';

import { useEffect, useState } from 'react';
import { Play, Smartphone, CheckSquare, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import type { CampaignDeviceOut } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
  devices: CampaignDeviceOut[];
  isRunning: boolean;
  onConfirm: (deviceSerials?: string[]) => void;
}

export function RunCampaignDialog({ open, onClose, devices, isRunning, onConfirm }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Reset to "all selected" whenever dialog opens
  const allSerials = devices.map((d) => d.serial);
  useEffect(() => {
    if (open) setSelected(new Set(allSerials));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const allSelected = allSerials.length > 0 && allSerials.every((s) => selected.has(s));
  const someSelected = allSerials.some((s) => selected.has(s));

  const toggle = (serial: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(serial)) next.delete(serial);
      else next.add(serial);
      return next;
    });
  };

  const toggleAll = () => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(allSerials));
    }
  };

  const handleRun = () => {
    const serials = allSerials.filter((s) => selected.has(s));
    // If all selected, pass undefined so backend uses all assigned devices
    onConfirm(serials.length === allSerials.length ? undefined : serials);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className='max-w-sm'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2 text-sm'>
            <Play size={14} />
            Chọn thiết bị để chạy
          </DialogTitle>
        </DialogHeader>

        {devices.length === 0 ? (
          <p className='py-4 text-center text-xs text-muted-foreground'>
            Chưa có thiết bị nào được gán vào campaign này.
          </p>
        ) : (
          <>
            {/* Select all row */}
            <button
              type='button'
              onClick={toggleAll}
              className='flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/60'
            >
              {allSelected
                ? <CheckSquare size={14} className='text-primary' />
                : <Square size={14} className='text-muted-foreground' />}
              <span className='font-medium'>Chọn tất cả</span>
              <Badge variant='secondary' className='ml-auto text-[10px]'>
                {allSerials.length} thiết bị
              </Badge>
            </button>

            <div className='h-px bg-border/50' />

            {/* Device list */}
            <div className='max-h-64 space-y-0.5 overflow-y-auto'>
              {devices.map((device) => {
                const isChecked = selected.has(device.serial);
                return (
                  <button
                    key={device.serial}
                    type='button'
                    onClick={() => toggle(device.serial)}
                    className='flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/60'
                  >
                    {isChecked
                      ? <CheckSquare size={13} className='shrink-0 text-primary' />
                      : <Square size={13} className='shrink-0 text-muted-foreground' />}
                    <Smartphone size={12} className='shrink-0 text-muted-foreground' />
                    <span className='font-mono'>{device.serial}</span>
                    {device.name && (
                      <span className='ml-1 truncate text-muted-foreground'>{device.name}</span>
                    )}
                  </button>
                );
              })}
            </div>
          </>
        )}

        <DialogFooter className='gap-2'>
          <Button size='sm' variant='outline' className='h-7 text-xs' onClick={onClose}>
            Hủy
          </Button>
          <Button
            size='sm'
            className='h-7 gap-1.5 text-xs'
            disabled={isRunning || !someSelected}
            onClick={handleRun}
          >
            <Play size={12} />
            Chạy {selected.size > 0 && selected.size < allSerials.length ? `(${selected.size})` : ''}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
