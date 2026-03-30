'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { DeviceTile } from './device-tile';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Circle,
  Square,
  Copy,
  Plus,
  Save,
  ArrowLeft,
  Play,
  GitBranch,
  ChevronDown,
  RefreshCw,
  Video,
  Clapperboard,
  Crosshair,
  HelpCircle,
} from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from '@/components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useControlRecord } from '../hooks/use-control-record';
import { XmlTreeViewer } from './control-record/xml-tree-viewer';
import { ScenarioPlayer } from './control-record/scenario-player';
import { FlowEditor } from '@/features/campaigns/components/flow-editor';
import {
  applySelectorToSteps,
  type SelectorPickTarget,
} from '@/features/campaigns/components/flow-editor';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { findSelectorInXml } from '../utils/control-record-xml';
import { parseHierarchyTree, findNodeIdAtRatio } from '../utils/hierarchy-tree';
import { useTranslations } from 'next-intl';

type Props = { initialSerial?: string | null };

export function ControlRecordView({ initialSerial }: Props = {}) {
  const t = useTranslations('devicesControlRecord.view');
  const { error, device, record, steps, save, hierarchy, selector } = useControlRecord(initialSerial);
  const { setSkipTapRecordingWhilePick } = record;

  const [highlightBounds, setHighlightBounds] = useState<[number, number, number, number] | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [playerMode, setPlayerMode] = useState(false);
  const [selectorPickTarget, setSelectorPickTarget] = useState<SelectorPickTarget | null>(null);

  useEffect(() => {
    setSkipTapRecordingWhilePick(selectorPickTarget != null);
    return () => setSkipTapRecordingWhilePick(false);
  }, [selectorPickTarget, setSkipTapRecordingWhilePick]);

  const applySelectorPick = useCallback(
    (by: string, value: string) => {
      if (!selectorPickTarget) return;
      const raw = steps.items as FlowStep[];
      const next = applySelectorToSteps(raw, selectorPickTarget, by, value);
      if (next === raw) {
        toast.warning(t('pickSelectorNoElement'));
        return;
      }
      steps.setItems(
        next.map((s: FlowStep, i: number) => ({
          ...s,
          _id: (s as { _id?: string })._id || `step-${Date.now()}-${i}`,
        })) as any,
      );
      selector.setBy(by as typeof selector.by);
      selector.setValue(value);
      setSelectorPickTarget(null);
      toast.success(t('pickSelectorApplied', { by, value: value.slice(0, 48) }));
    },
    [selectorPickTarget, steps, selector, t],
  );

  // When user taps the phone screen → hierarchy highlight + optional selector pick
  const handleScreenTap = useCallback(
    (rx: number, ry: number) => {
      const tree = parseHierarchyTree(hierarchy.xml);
      if (tree) {
        const nodeId = findNodeIdAtRatio(tree, rx, ry);
        setSelectedNodeId(nodeId);
      }

      if (selectorPickTarget) {
        const sel = findSelectorInXml(hierarchy.xml, rx, ry);
        if (sel?.value) {
          applySelectorPick(sel.by, sel.value);
        } else {
          toast.warning(t('pickSelectorNoElement'));
        }
        return;
      }
    },
    [hierarchy.xml, selectorPickTarget, applySelectorPick, t],
  );

  // ── Error / empty states ─────────────────────────────────────────────────
  if (error) {
    return (
      <div className='rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive'>
        {error}
      </div>
    );
  }

  if (device.connectedDevices.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-20 text-center'>
        <Video className='mb-3 size-10 text-muted-foreground/40' />
        <p className='mb-1 text-base font-medium'>{t('noDeviceConnected')}</p>
        <p className='mb-4 text-sm text-muted-foreground'>Kết nối thiết bị Android qua USB hoặc Wi-Fi để bắt đầu</p>
        <Button asChild size='sm' variant='outline'>
          <Link href={ROUTES.DEVICES.MANAGE}>
            <ArrowLeft className='mr-1.5 size-4' />
            {t('addDevice')}
          </Link>
        </Button>
      </div>
    );
  }

  const { selectedDevice } = device;

  return (
    <div className='flex h-[calc(100vh-80px)] flex-col overflow-hidden'>

      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div className='flex shrink-0 flex-col gap-2 border-b bg-background/95 px-4 py-3 backdrop-blur sm:flex-row sm:items-center sm:gap-4'>
        <div className='flex min-w-0 flex-1 items-center gap-2 sm:gap-3'>
          <Button asChild variant='ghost' size='sm' className='shrink-0 -ml-1'>
            <Link href={ROUTES.DEVICES.ROOT}>
              <ArrowLeft className='mr-1 size-4' />
              Farm
            </Link>
          </Button>
          <div className='hidden h-6 w-px bg-border sm:block' />
          <div className='min-w-0'>
            <p className='text-[10px] font-medium uppercase tracking-wider text-muted-foreground'>
              {t('pageEyebrow')}
            </p>
            <p className='truncate text-sm font-semibold leading-tight'>{t('pageTitle')}</p>
          </div>
        </div>

        <div className='flex flex-wrap items-center gap-2 sm:justify-end'>
          <Select
            value={device.selectedSerial ?? ''}
            onValueChange={(v) => device.setSelectedSerial(v || null)}
          >
            <SelectTrigger className='h-9 w-full min-w-[200px] max-w-[min(100%,320px)] sm:w-[280px]'>
              <SelectValue placeholder={t('selectPhonePlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {device.connectedDevices.map((d) => (
                <SelectItem key={d.serial} value={d.serial}>
                  {d.brand} {d.model} — {d.serial.slice(0, 12)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium',
              device.wsConnected
                ? 'border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-400'
                : 'border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-400',
            )}
          >
            <span
              className={cn('size-2 rounded-full', device.wsConnected ? 'bg-green-500' : 'bg-red-500')}
            />
            {device.wsConnected ? t('wsConnected') : t('wsDisconnected')}
          </span>

          {selectedDevice?.touch_method && (
            <span className='text-xs text-muted-foreground'>
              {t('touchPrefix')}{' '}
              {selectedDevice.touch_method === 'u2' ? 'uiautomator2' : selectedDevice.touch_method}
            </span>
          )}
        </div>
      </div>

      {/* ── Main layout ─────────────────────────────────────────────────── */}
      <div className='flex flex-1 overflow-hidden'>

        {/* LEFT: device screen only ──────────────────────────────────────── */}
        <div className='w-[min(100%,360px)] shrink-0 overflow-y-auto border-r border-border/60 bg-muted/20 p-3'>
          {selectedDevice && (
            <div className='min-h-[660px]'>
              <DeviceTile
                device={selectedDevice}
                logLines={device.logs[selectedDevice.serial] ?? []}
                mode={device.mode}
                wsSend={record.sendAndRecord}
                onToggleMode={record.handleToggleMode}
                onRestart={record.handleRestart}
                onTap={handleScreenTap}
                highlightBounds={highlightBounds}
              />
            </div>
          )}
        </div>

        {/* RIGHT: hierarchy (top) + recording editor (bottom) ───────────── */}
        <div className='flex flex-1 flex-col overflow-hidden'>

          {/* ── Hierarchy / phần tử màn hình ─────────────────────────────── */}
          <div
            className='flex shrink-0 flex-col border-b border-border/60 bg-muted/10'
            style={{ height: 'min(40vh, 420px)', minHeight: 200 }}
          >
            <div className='min-h-0 flex-1 overflow-hidden p-2 pb-0'>
              <XmlTreeViewer
                xml={hierarchy.xml}
                loading={hierarchy.loading}
                onNodeSelect={({ bounds, by, value, nodeId }) => {
                  setHighlightBounds(bounds);
                  if (nodeId != null) setSelectedNodeId(nodeId);
                  if (selectorPickTarget) {
                    if (value?.trim()) applySelectorPick(by, value.trim());
                    else toast.warning(t('pickSelectorNoElement'));
                    return;
                  }
                  selector.setBy(by as typeof selector.by);
                  selector.setValue(value);
                }}
                selectedNodeId={selectedNodeId}
                onRefresh={() => selectedDevice && hierarchy.refresh()}
                autoRefresh={hierarchy.autoRefresh}
                onAutoRefreshChange={hierarchy.setAutoRefresh}
              />
            </div>

            {/* Selector: hint or selected element */}
            <div
              className={cn(
                'flex shrink-0 items-center gap-2 border-t px-3 py-2',
                selector.value ? 'bg-primary/8' : 'bg-muted/40',
              )}
            >
              {selector.value ? (
                <>
                  <span className='min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground'>
                    <span className='font-semibold text-primary'>[{selector.by}]</span> {selector.value}
                  </span>
                  <Button
                    size='sm'
                    variant='secondary'
                    className='h-8 shrink-0 px-3 text-xs'
                    onClick={selector.tap}
                    disabled={!selectedDevice}
                  >
                    {t('tapSelected')}
                  </Button>
                </>
              ) : (
                <p className='min-w-0 flex-1 text-[11px] leading-snug text-muted-foreground'>
                  {t('selectorBarHint')}
                </p>
              )}
              <Tooltip delayDuration={400}>
                <TooltipTrigger asChild>
                  <button
                    type='button'
                    className='shrink-0 rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground'
                    aria-label={t('tooltipSelectorBar')}
                  >
                    <HelpCircle className='size-3.5' />
                  </button>
                </TooltipTrigger>
                <TooltipContent side='top' className='max-w-[min(100vw-2rem,20rem)] text-xs leading-relaxed'>
                  {t('tooltipSelectorBar')}
                </TooltipContent>
              </Tooltip>
            </div>
          </div>

          {/* ── Recording + scenario editor ───────────────────────────────── */}
          <div className='flex flex-1 flex-col overflow-hidden'>

          {playerMode && selectedDevice ? (
            /* ── Player mode ─────────────────────────────────────────────── */
            <div className='flex flex-1 flex-col items-center justify-start gap-4 overflow-auto p-6'>
              <div className='w-full max-w-lg'>
                <ScenarioPlayer
                  serial={selectedDevice.serial}
                  onClose={() => setPlayerMode(false)}
                  onPlayingChange={hierarchy.setPaused}
                />
              </div>
            </div>
          ) : (
            <>
              {/* ── Recording status bar ──────────────────────────────────── */}
              {record.recording ? (
                <div className='flex shrink-0 flex-col gap-3 border-b border-red-200/80 bg-red-50/90 px-4 py-3 dark:border-red-900/40 dark:bg-red-950/25 sm:flex-row sm:items-center'>
                  <div className='flex min-w-0 flex-1 items-center gap-3'>
                    <span className='relative flex size-3 shrink-0'>
                      <span className='absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75' />
                      <span className='relative inline-flex size-3 rounded-full bg-red-500' />
                    </span>
                    <span className='text-sm font-semibold text-red-800 dark:text-red-300'>
                      {t('recordingActive')}
                    </span>
                    {steps.items.length > 0 && (
                      <span className='rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/50 dark:text-red-200'>
                        {t('stepCount', { count: steps.items.length })}
                      </span>
                    )}
                    {record.pollingXml && (
                      <span className='flex items-center gap-1.5 text-xs text-red-600/80 dark:text-red-400/90'>
                        <RefreshCw size={12} className='animate-spin' />
                        {t('recordingReadingUi')}
                      </span>
                    )}
                  </div>
                  <Button
                    size='sm'
                    variant='destructive'
                    className='w-full shrink-0 sm:w-auto'
                    onClick={() => void record.toggleRecording()}
                  >
                    <Square className='mr-1.5 size-3.5' />
                    {t('stopRecording')}
                  </Button>
                </div>
              ) : (
                <div className='flex shrink-0 flex-col gap-3 border-b bg-gradient-to-r from-muted/40 to-muted/20 px-4 py-3 sm:flex-row sm:items-center'>
                  <div className='min-w-0 flex-1 space-y-0.5'>
                    <p className='text-xs font-semibold text-foreground'>{t('recordingIdleTitle')}</p>
                    <p className='text-[11px] leading-relaxed text-muted-foreground sm:text-xs'>
                      {t.rich('recordingIdleSubtitle', {
                        strong: (c) => <strong className='font-semibold text-foreground'>{c}</strong>,
                      })}
                    </p>
                  </div>
                  <div className='flex shrink-0 flex-wrap items-center gap-2'>
                    <Button
                      size='default'
                      variant='default'
                      className='min-h-10 gap-2 shadow-sm'
                      onClick={() => void record.toggleRecording()}
                      disabled={!selectedDevice}
                    >
                      <Circle className='size-4 fill-current' />
                      {t('startRecording')}
                    </Button>
                    <Button
                      size='default'
                      variant='outline'
                      className='min-h-10 gap-2'
                      onClick={() => setPlayerMode(true)}
                      disabled={!selectedDevice}
                    >
                      <Play className='size-4' />
                      {t('tryRun')}
                    </Button>
                  </div>
                </div>
              )}

              {/* ── Steps / flow editor ───────────────────────────────────── */}
              <div className='flex min-h-0 flex-1 flex-col overflow-hidden px-4 pt-3'>
                <div className='mb-2 flex items-center gap-1.5'>
                  <Clapperboard className='size-3.5 text-muted-foreground' aria-hidden />
                  <span className='text-xs font-semibold uppercase tracking-wide text-muted-foreground'>
                    {t('editorSectionTitle')}
                  </span>
                  <Tooltip delayDuration={400}>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        className='rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground'
                        aria-label={t('tooltipScenarioSection')}
                      >
                        <HelpCircle className='size-3.5' />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side='bottom' className='max-w-[min(100vw-2rem,22rem)] text-xs leading-relaxed'>
                      {t('tooltipScenarioSection')}
                    </TooltipContent>
                  </Tooltip>
                </div>
                {selectorPickTarget && (
                  <div className='mb-2 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-950 dark:text-amber-100'>
                    <Crosshair className='mt-0.5 size-4 shrink-0' aria-hidden />
                    <p className='min-w-0 flex-1 leading-snug'>{t('pickSelectorBanner')}</p>
                    <Tooltip delayDuration={400}>
                      <TooltipTrigger asChild>
                        <button
                          type='button'
                          className='shrink-0 rounded-full p-0.5 text-amber-900/80 hover:bg-amber-500/20 dark:text-amber-200'
                          aria-label={t('tooltipPickBannerMore')}
                        >
                          <HelpCircle className='size-3.5' />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side='left' className='max-w-[min(100vw-2rem,22rem)] text-xs leading-relaxed'>
                        {t('tooltipPickBannerMore')}
                      </TooltipContent>
                    </Tooltip>
                  </div>
                )}
                <div className='min-h-0 flex-1 overflow-hidden rounded-lg border border-dashed border-border/80 bg-background/50'>
                  {steps.items.length === 0 ? (
                    <div className='flex h-full min-h-[160px] flex-col items-center justify-center gap-2 px-6 py-10 text-center'>
                      <div className='rounded-full bg-muted/60 p-3'>
                        <Circle className='size-8 text-muted-foreground/35' strokeWidth={1.25} />
                      </div>
                      <p className='text-sm font-medium text-foreground'>{t('emptyStepsTitle')}</p>
                      <p className='max-w-sm text-xs leading-relaxed text-muted-foreground'>
                        {t('emptyStepsHint')}
                      </p>
                    </div>
                  ) : (
                    <div className='h-full overflow-hidden p-2'>
                      <FlowEditor
                        steps={steps.items as FlowStep[]}
                        onChange={(newSteps) =>
                          steps.setItems(
                            newSteps.map((s: FlowStep, i: number) => ({
                              ...s,
                              _id: (s as any)._id || `step-${Date.now()}-${i}`,
                            })) as any
                          )
                        }
                        maxHeight='calc(100vh - 420px)'
                        selectorPickTarget={selectorPickTarget}
                        onSelectorPickTargetChange={setSelectorPickTarget}
                      />
                    </div>
                  )}
                </div>
              </div>

              {/* ── Bottom action bar ─────────────────────────────────────── */}
              <div className='flex shrink-0 flex-wrap items-center gap-2 border-t border-border/60 bg-muted/15 px-4 py-3'>
                <Button size='sm' variant='outline' onClick={steps.addWait}>
                  <Plus className='mr-1.5 size-3.5' />
                  Thêm chờ
                </Button>

                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size='sm' variant='outline'>
                      <GitBranch className='mr-1.5 size-3.5' />
                      Điều kiện
                      <ChevronDown className='ml-1.5 size-3' />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align='start' className='w-56'>
                    <DropdownMenuLabel className='text-[10px] font-semibold uppercase tracking-wider text-muted-foreground'>
                      Điều kiện
                    </DropdownMenuLabel>
                    <DropdownMenuItem className='gap-2' onClick={() => steps.addFlow('if_element')}>
                      <StepIcon type='if_element' size={14} />
                      Nếu phần tử tồn tại
                    </DropdownMenuItem>
                    <DropdownMenuItem className='gap-2' onClick={() => steps.addFlow('if_variable')}>
                      <StepIcon type='if_variable' size={14} />
                      Nếu biến thỏa điều kiện
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuLabel className='text-[10px] font-semibold uppercase tracking-wider text-muted-foreground'>
                      Lặp lại
                    </DropdownMenuLabel>
                    <DropdownMenuItem className='gap-2' onClick={() => steps.addFlow('repeat')}>
                      <StepIcon type='repeat' size={14} />
                      Lặp N lần
                    </DropdownMenuItem>
                    <DropdownMenuItem className='gap-2' onClick={() => steps.addFlow('repeat_until')}>
                      <StepIcon type='repeat_until' size={14} />
                      Lặp cho đến khi
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>

                <div className='ml-auto flex items-center gap-2'>
                  <Button
                    size='sm'
                    variant='ghost'
                    onClick={steps.copyJson}
                    disabled={steps.items.length === 0}
                    title='Copy JSON'
                  >
                    <Copy className='size-3.5' />
                  </Button>
                  <Button
                    size='sm'
                    variant='default'
                    onClick={steps.openSave}
                    disabled={steps.items.length === 0}
                  >
                    <Save className='mr-1.5 size-3.5' />
                    Lưu kịch bản
                  </Button>
                </div>
              </div>
            </>
          )}
          </div>  {/* end recording editor */}
        </div>    {/* end right column */}
      </div>      {/* end main layout */}

      {/* ── Save dialog ─────────────────────────────────────────────────────── */}
      <Dialog
        open={save.dialogOpen}
        onOpenChange={(o) => {
          save.setDialogOpen(o);
          if (!o) save.setSelectedCampaignId(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {save.selectedCampaignId
                ? t('chooseScenarioTitle', { name: save.campaigns.find((c) => c.id === save.selectedCampaignId)?.name ?? '' })
                : t('saveScenarioTitle')}
            </DialogTitle>
          </DialogHeader>

          {!save.selectedCampaignId ? (
            <div className='space-y-2'>
              <p className='text-xs text-muted-foreground'>{t('stepsRecorded', { count: steps.items.length })}</p>
              {save.campaigns.length === 0 ? (
                <p className='text-sm text-muted-foreground'>{t('noCampaign')}</p>
              ) : (
                save.campaigns.map((c) => (
                  <Button
                    key={c.id}
                    variant='outline'
                    className='w-full justify-start'
                    onClick={() => save.pickCampaign(c.id)}
                    disabled={save.saving !== null}
                  >
                    {c.name}
                  </Button>
                ))
              )}
            </div>
          ) : (
            <div className='space-y-2'>
              <Button
                variant='ghost'
                size='sm'
                className='text-xs text-muted-foreground'
                onClick={() => save.setSelectedCampaignId(null)}
              >
                {t('chooseCampaignAgain')}
              </Button>
              <Button
                variant='default'
                className='w-full justify-start gap-2'
                onClick={() => save.saveAsNew(save.selectedCampaignId!)}
                disabled={save.saving !== null}
              >
                <Plus size={13} />
                {save.saving === 'new' ? t('creating') : t('createNewScenario')}
              </Button>
              {save.campaignScenarios.length > 0 && (
                <>
                  <p className='pt-1 text-xs text-muted-foreground'>{t('overwriteExisting')}</p>
                  {save.campaignScenarios.map((s) => (
                    <Button
                      key={s.id}
                      variant='outline'
                      className='h-auto w-full flex-col items-start justify-start py-2 text-left'
                      onClick={() => save.saveTo(save.selectedCampaignId!, s.id)}
                      disabled={save.saving !== null}
                    >
                      <span className='font-medium'>
                        {save.saving === s.id ? t('saving') : s.name}
                      </span>
                      <span className='text-[11px] font-normal text-muted-foreground'>
                        {t('currentSteps', { count: s.steps.length })}
                      </span>
                    </Button>
                  ))}
                </>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
