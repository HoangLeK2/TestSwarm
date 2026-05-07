'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Play, Smartphone, CheckSquare, Square, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  DEFAULT_DEVICE_VARIABLES,
  DeviceVarsJsonPanel,
  formatDeviceVarsJson,
  formatInitialDeviceVars,
  parseDeviceVarsJson,
} from '@/components/device-vars-json-panel';
import { cn } from '@/lib/utils';
import { campaignsApi } from '../services/api';
import type { CampaignDeviceOut, ScenarioOut } from '../types';

interface Props {
  open: boolean;
  campaignId: string;
  onClose: () => void;
  devices: CampaignDeviceOut[];
  scenarios: ScenarioOut[];
  isRunning: boolean;
  onConfirm: (deviceSerials?: string[]) => void;
}

const makePairKey = (scenarioId: string, deviceId: string) => `${scenarioId}::${deviceId}`;

export function RunCampaignDialog({
  open,
  campaignId,
  onClose,
  devices,
  scenarios,
  isRunning,
  onConfirm,
}: Props) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeDeviceId, setActiveDeviceId] = useState<string>('');
  const [activeScenarioId, setActiveScenarioId] = useState<string>('');
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [deviceVarEnabled, setDeviceVarEnabled] = useState<Record<string, boolean>>({});
  const [dirtyKeys, setDirtyKeys] = useState<Record<string, true>>({});
  const [isSaving, setIsSaving] = useState(false);

  const allSerials = useMemo(() => devices.map((d) => d.serial), [devices]);
  const deviceSignature = useMemo(() => devices.map((d) => d.id).join('|'), [devices]);
  const scenarioSignature = useMemo(() => scenarios.map((s) => s.id).join('|'), [scenarios]);
  const firstDeviceId = devices[0]?.id ?? '';
  const firstScenarioId = scenarios[0]?.id ?? '';
  const activeDevice = useMemo(
    () => devices.find((d) => d.id === activeDeviceId) ?? devices[0],
    [activeDeviceId, devices],
  );
  const pairKey =
    activeScenarioId && activeDevice?.id
      ? makePairKey(activeScenarioId, activeDevice.id)
      : '';

  useEffect(() => {
    if (!open) return;
    setSelected(new Set(allSerials));
    setActiveDeviceId(firstDeviceId);
    setActiveScenarioId(firstScenarioId);
    setDrafts({});
    setDeviceVarEnabled({});
    setDirtyKeys({});
  }, [allSerials, deviceSignature, firstDeviceId, firstScenarioId, open, scenarioSignature]);

  const variableQuery = useQuery({
    queryKey: ['campaign-device-variables', campaignId, activeScenarioId, activeDevice?.id],
    queryFn: () =>
      campaignsApi.getScenarioDeviceVariables(
        campaignId,
        activeScenarioId,
        activeDevice!.id,
      ),
    enabled: open && !!campaignId && !!activeScenarioId && !!activeDevice?.id,
  });

  useEffect(() => {
    if (!pairKey || !variableQuery.data) return;
    const savedVars = variableQuery.data.vars ?? {};
    setDrafts((prev) => {
      if (prev[pairKey] !== undefined) return prev;
      return {
        ...prev,
        [pairKey]: formatInitialDeviceVars(savedVars),
      };
    });
    setDeviceVarEnabled((prev) => {
      if (prev[pairKey] !== undefined) return prev;
      return {
        ...prev,
        [pairKey]: Object.keys(savedVars).length > 0,
      };
    });
  }, [pairKey, variableQuery.data]);

  const allSelected = allSerials.length > 0 && allSerials.every((s) => selected.has(s));
  const someSelected = allSerials.some((s) => selected.has(s));
  const currentDraft = pairKey
    ? drafts[pairKey] ?? (variableQuery.isLoading ? '' : '{}')
    : '{}';
  const currentDeviceVarsEnabled = pairKey ? deviceVarEnabled[pairKey] === true : false;
  const currentJsonError = useMemo(() => {
    if (variableQuery.isLoading || !currentDeviceVarsEnabled) return '';
    try {
      parseDeviceVarsJson(currentDraft);
      return '';
    } catch (err) {
      return err instanceof Error ? err.message : 'JSON không hợp lệ';
    }
  }, [currentDeviceVarsEnabled, currentDraft, variableQuery.isLoading]);

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

  const handleDraftChange = (value: string) => {
    if (!pairKey) return;
    setDrafts((prev) => ({ ...prev, [pairKey]: value }));
    setDirtyKeys((prev) => ({ ...prev, [pairKey]: true }));
  };

  const handleDeviceVarsToggle = (enabled: boolean) => {
    if (!pairKey) return;
    setDeviceVarEnabled((prev) => ({ ...prev, [pairKey]: enabled }));
    setDrafts((prev) => ({
      ...prev,
      [pairKey]: prev[pairKey] ?? formatDeviceVarsJson(DEFAULT_DEVICE_VARIABLES),
    }));
    setDirtyKeys((prev) => ({ ...prev, [pairKey]: true }));
  };

  const saveDirtyDrafts = async () => {
    const keys = Object.keys(dirtyKeys);
    for (const key of keys) {
      if (deviceVarEnabled[key] !== true) continue;
      try {
        parseDeviceVarsJson(drafts[key] ?? '{}');
      } catch (err) {
        const [scenarioId, deviceId] = key.split('::');
        setActiveScenarioId(scenarioId);
        setActiveDeviceId(deviceId);
        toast.error(err instanceof Error ? err.message : 'JSON không hợp lệ');
        return false;
      }
    }

    if (!keys.length) return true;

    setIsSaving(true);
    try {
      await Promise.all(
        keys.map((key) => {
          const [scenarioId, deviceId] = key.split('::');
          const vars = deviceVarEnabled[key] === true
            ? parseDeviceVarsJson(drafts[key] ?? '{}')
            : {};
          return campaignsApi.replaceScenarioDeviceVariables(campaignId, scenarioId, deviceId, {
            vars,
          });
        }),
      );
      keys.forEach((key) => {
        const [scenarioId, deviceId] = key.split('::');
        qc.invalidateQueries({
          queryKey: ['campaign-device-variables', campaignId, scenarioId, deviceId],
        });
      });
      setDirtyKeys({});
      return true;
    } catch {
      toast.error('Lưu biến thiết bị thất bại');
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  const handleRun = async () => {
    if (!(await saveDirtyDrafts())) return;
    const serials = allSerials.filter((s) => selected.has(s));
    // If all selected, pass undefined so backend uses all assigned devices
    onConfirm(serials.length === allSerials.length ? undefined : serials);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className='max-h-[92vh] max-w-5xl min-w-[92vh] overflow-hidden p-0'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2 border-b px-5 py-4 text-sm'>
            <Play size={14} />
            Chạy campaign
          </DialogTitle>
        </DialogHeader>

        {devices.length === 0 || scenarios.length === 0 ? (
          <p className='py-4 text-center text-xs text-muted-foreground'>
            Chưa có đủ thiết bị hoặc kịch bản để chạy campaign này.
          </p>
        ) : (
          <div className='grid min-h-0 grid-cols-[280px_1fr] divide-x px-5 '>
            <div className='min-h-0 py-4 pr-4'>
              <button
                type='button'
                onClick={toggleAll}
                className='mb-2 flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted/60'
              >
                {allSelected
                  ? <CheckSquare size={14} className='text-primary' />
                  : <Square size={14} className='text-muted-foreground' />}
                <span className='font-medium'>Chọn tất cả</span>
                <Badge variant='secondary' className='ml-auto text-[10px]'>
                  {allSerials.length}
                </Badge>
              </button>

              <div className='max-h-[64vh] space-y-1 overflow-y-auto pr-1'>
                {devices.map((device) => {
                  const isChecked = selected.has(device.serial);
                  const isActive = activeDevice?.id === device.id;
                  return (
                    <div
                      key={device.id}
                      className={cn(
                        'flex items-center gap-1 rounded border border-transparent px-1 py-1',
                        isActive && 'border-primary/30 bg-primary/[0.06]',
                      )}
                    >
                      <button
                        type='button'
                        onClick={() => toggle(device.serial)}
                        className='flex h-7 w-7 shrink-0 items-center justify-center rounded hover:bg-muted'
                        aria-label={isChecked ? 'Bỏ chọn thiết bị' : 'Chọn thiết bị'}
                      >
                        {isChecked
                          ? <CheckSquare size={13} className='text-primary' />
                          : <Square size={13} className='text-muted-foreground' />}
                      </button>
                      <button
                        type='button'
                        onClick={() => setActiveDeviceId(device.id)}
                        className='flex min-w-0 flex-1 items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-muted/60'
                      >
                        <Smartphone size={12} className='shrink-0 text-muted-foreground' />
                        <span className='min-w-0 truncate font-mono'>{device.serial}</span>
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className='min-h-0 py-4 pl-4'>
              <div className='mb-3 flex items-center justify-between gap-3'>
                <div className='min-w-0' />
                {scenarios.length > 1 && (
                  <Select value={activeScenarioId} onValueChange={setActiveScenarioId}>
                    <SelectTrigger size='sm' className='w-[220px] text-xs'>
                      <SelectValue placeholder='Chọn kịch bản' />
                    </SelectTrigger>
                    <SelectContent>
                      {scenarios.map((scenario) => (
                        <SelectItem key={scenario.id} value={scenario.id}>
                          {scenario.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>

              <DeviceVarsJsonPanel
                enabled={currentDeviceVarsEnabled}
                onEnabledChange={handleDeviceVarsToggle}
                draft={currentDraft}
                onDraftChange={handleDraftChange}
                loading={variableQuery.isLoading}
                jsonError={currentJsonError}
                deviceLabel={activeDevice?.serial}
                editorClassName='min-h-[460px]'
                emptyClassName='min-h-[460px]'
              />
            </div>
          </div>
        )}

        <DialogFooter className='border-t px-5 py-4'>
          <Button size='sm' variant='outline' className='h-7 text-xs' onClick={onClose}>
            Hủy
          </Button>
          <Button
            size='sm'
            className='h-7 gap-1.5 text-xs'
            disabled={isRunning || isSaving || !someSelected || !!currentJsonError}
            onClick={handleRun}
          >
            {isSaving ? <Loader2 size={12} className='animate-spin' /> : <Play size={12} />}
            Chạy {selected.size > 0 && selected.size < allSerials.length ? `(${selected.size})` : ''}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
