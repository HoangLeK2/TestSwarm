'use client';

import Link from 'next/link';
import { DeviceTile } from './device-tile';
import { Button } from '@/components/ui/button';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Circle,
  Square,
  Copy,
  Trash2,
  Plus,
  Save,
  ArrowLeft,
  RefreshCw,
  Play
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { useState } from 'react';
import { useControlRecord, type StepWithId } from '../hooks/use-control-record';
import { ControlRecordStepLabel } from './control-record/step-label';
import { XmlTreeViewer } from './control-record/xml-tree-viewer';
import { ScenarioPlayer } from './control-record/scenario-player';
import { useTranslations } from 'next-intl';

type ControlRecordViewProps = {
  initialSerial?: string | null;
};

export function ControlRecordView({ initialSerial }: ControlRecordViewProps = {}) {
  const t = useTranslations('devicesControlRecord.view');
  const {
    error,
    connectedDevices,
    selectedDevice,
    selectedSerial,
    setSelectedSerial,
    logs,
    sendAndRecord,
    modes,
    handleToggleMode,
    handleRestart,
    wsConnected,
    recording,
    pollingXml,
    refreshRecordXml,
    steps,
    mode,
    addWaitStep,
    removeStep,
    moveStep,
    copyJson,
    openSaveDialog,
    saveDialogOpen,
    setSaveDialogOpen,
    campaigns,
    savingCampaignId,
    selectedCampaignId,
    setSelectedCampaignId,
    campaignScenarios,
    handlePickCampaign,
    saveToScenario,
    saveAsNewScenario,
    hierarchyOpen,
    setHierarchyOpen,
    hierarchyXml,
    loadHierarchy,
    refreshHierarchy,
    parsedHierarchyNodes,
    selectorBy,
    setSelectorBy,
    selectorValue,
    setSelectorValue,
    handleTapSelector,
    toggleRecording,
    autoRefreshHierarchy,
    setAutoRefreshHierarchy,
    hierarchyLoading,
    hierarchyPaused,
    setHierarchyPaused,
  } = useControlRecord(initialSerial);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor),
  );
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      const oldIndex = steps.findIndex((s) => s._id === active.id);
      const newIndex = steps.findIndex((s) => s._id === over.id);
      if (oldIndex !== -1 && newIndex !== -1) moveStep(oldIndex, newIndex);
    }
  };

  const [highlightBounds, setHighlightBounds] = useState<[number, number, number, number] | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [playerMode, setPlayerMode] = useState(false);

  if (error) {
    return (
      <div className='rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive'>
        {error}
      </div>
    );
  }

  if (connectedDevices.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-20 text-center'>
        <p className='mb-2 text-sm text-muted-foreground'>{t('noDeviceConnected')}</p>
        <Button asChild size='sm' variant='outline'>
          <Link href={ROUTES.DEVICES.MANAGE}>
            <ArrowLeft className='mr-1.5 size-4' />
            {t('addDevice')}
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-center gap-4'>
        <Button asChild variant='ghost' size='sm'>
          <Link href={ROUTES.DEVICES.ROOT}>
            <ArrowLeft className='mr-1.5 size-4' />
            Farm
          </Link>
        </Button>
        <div className='flex items-center gap-2'>
          <span className='text-sm font-medium text-muted-foreground'>{t('selectDevice')}</span>
          <Select
            value={selectedSerial ?? ''}
            onValueChange={(v) => setSelectedSerial(v || null)}
          >
            <SelectTrigger className='w-[260px]'>
              <SelectValue placeholder={t('selectPhonePlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {connectedDevices.map((d) => (
                <SelectItem key={d.serial} value={d.serial}>
                  {d.brand} {d.model} — {d.serial.slice(0, 12)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <span className='text-xs text-muted-foreground'>
          {wsConnected ? '🟢 WS' : '🔴 WS'}
        </span>
        {selectedDevice?.touch_method && (
          <span className='text-xs text-muted-foreground' title={t('touchMethodTitle')}>
            Touch: {selectedDevice.touch_method === 'u2' ? 'uiautomator2' : selectedDevice.touch_method}
          </span>
        )}
      </div>

      <div className='flex flex-col gap-4 lg:flex-row lg:items-start'>
        {/* Column 1: Device Preview */}
        <div className='w-full shrink-0 lg:w-auto' style={{ maxWidth: 320 }}>
          {selectedDevice && (
            <DeviceTile
              device={selectedDevice}
              logLines={logs[selectedDevice.serial] ?? []}
              mode={mode}
              wsSend={sendAndRecord}
              onToggleMode={handleToggleMode}
              onRestart={handleRestart}
              highlightBounds={highlightBounds}
            />
          )}
        </div>

        {/* Column 2: XML Tree Viewer */}
        <div className='min-w-[300px] flex-1' style={{ minHeight: 400, maxHeight: 'calc(100vh - 200px)' }}>
          <XmlTreeViewer
            xml={hierarchyXml}
            loading={hierarchyLoading ?? false}
            onNodeSelect={({ bounds, by, value }) => {
              setHighlightBounds(bounds);
              setSelectedNodeId(null); // will be updated by tree interaction
              setSelectorBy(by as typeof selectorBy);
              setSelectorValue(value);
            }}
            selectedNodeId={selectedNodeId}
            onRefresh={() => {
              if (selectedDevice) refreshHierarchy();
            }}
            autoRefresh={autoRefreshHierarchy ?? true}
            onAutoRefreshChange={setAutoRefreshHierarchy ?? (() => {})}
          />
        </div>

        {/* Column 3: Scenario Card */}
        <Card className='w-full lg:w-[380px] shrink-0'>
          <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
            <CardTitle className='text-sm'>{playerMode ? 'Scenario Player' : t('scenarioCardTitle')}</CardTitle>
            <div className='flex items-center gap-2'>
              {!playerMode && (
                <Button
                  size='sm'
                  variant='outline'
                  onClick={() => setPlayerMode(true)}
                  disabled={!selectedDevice}
                >
                  <Play className='mr-1 size-3.5' />
                  Play
                </Button>
              )}
              {!playerMode && recording && selectedDevice && (
                <>
                  {pollingXml ? (
                    <span className='flex items-center gap-1 text-[11px] text-muted-foreground animate-pulse'>
                      <RefreshCw size={11} className='animate-spin' />
                      {t('waitingUi')}
                    </span>
                  ) : (
                    <Button
                      size='sm'
                      variant='outline'
                      className='h-7 gap-1 text-[11px] px-2'
                      onClick={() =>
                        refreshRecordXml(selectedDevice.serial).then((xml) => {
                          if (xml) toast.success(t('xmlRefreshed'));
                          else toast.warning(t('xmlFetchFailed'));
                        })
                      }
                    >
                      <RefreshCw size={11} />
                      {t('getXml')}
                    </Button>
                  )}
                </>
              )}
              {!playerMode && (
                <Button
                  size='sm'
                  variant={recording ? 'destructive' : 'secondary'}
                  onClick={() => void toggleRecording()}
                >
                  {recording ? (
                    <>
                      <Square className='mr-1 size-3.5' />
                      {t('stopRecord')}
                    </>
                  ) : (
                    <>
                      <Circle className='mr-1 size-3.5' />
                      {t('record')}
                    </>
                  )}
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className='space-y-3'>
            {playerMode && selectedDevice ? (
              <ScenarioPlayer
                serial={selectedDevice.serial}
                onClose={() => setPlayerMode(false)}
                onPlayingChange={setHierarchyPaused}
              />
            ) : (
            <>
            <p className='text-xs text-muted-foreground'>
              {t.rich('recordingHint', { strong: (chunks) => <strong>{chunks}</strong> })}
            </p>
            <p className='text-xs text-muted-foreground'>
              {t('selectorHint')}
            </p>
            <div className='flex flex-wrap items-center gap-2'>
              <select
                className='rounded border bg-background text-xs px-2 py-1.5'
                value={selectorBy}
                onChange={(e) => setSelectorBy(e.target.value as typeof selectorBy)}
              >
                <option value='text'>text</option>
                <option value='resource-id'>resource-id</option>
                <option value='description'>description (content-desc)</option>
                <option value='descriptionContains'>descriptionContains</option>
                <option value='descriptionStartsWith'>descriptionStartsWith</option>
                <option value='xpath'>xpath</option>
                <option value='class name'>class name</option>
              </select>
              <input
                className='min-w-[120px] flex-1 rounded border bg-background px-2 py-1.5 text-xs font-mono'
                placeholder={t('selectorPlaceholder')}
                value={selectorValue}
                onChange={(e) => setSelectorValue(e.target.value)}
              />
              <Button
                size='sm'
                variant='secondary'
                onClick={handleTapSelector}
                disabled={!selectedDevice || !selectorValue.trim()}
              >
                {t('tapU2')}
              </Button>
            </div>
            <div className='flex gap-1.5'>
              <Button size='sm' variant='outline' onClick={addWaitStep}>
                <Plus className='mr-1 size-3' />
                {t('addWait')}
              </Button>
              <Button size='sm' variant='outline' onClick={copyJson} disabled={steps.length === 0}>
                <Copy className='mr-1 size-3' />
                {t('copyJson')}
              </Button>
              <Button size='sm' variant='outline' onClick={openSaveDialog} disabled={steps.length === 0}>
                <Save className='mr-1 size-3' />
                {t('saveToCampaign')}
              </Button>
            </div>
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              modifiers={[restrictToVerticalAxis]}
              onDragEnd={handleDragEnd}
            >
              <SortableContext items={steps.map((s) => s._id)} strategy={verticalListSortingStrategy}>
                <div className='max-h-[320px] space-y-1 overflow-y-auto rounded border border-border/60 bg-muted/30 p-2'>
                  {steps.length === 0 ? (
                    <p className='py-4 text-center text-xs text-muted-foreground'>
                      {t('noSteps')}
                    </p>
                  ) : (
                    steps.map((step, i) => (
                      <SortableStepItem key={step._id} step={step} index={i} onRemove={removeStep} />
                    ))
                  )}
                </div>
              </SortableContext>
            </DndContext>
            </>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog
        open={saveDialogOpen}
        onOpenChange={(o) => {
          setSaveDialogOpen(o);
          if (!o) setSelectedCampaignId(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {selectedCampaignId
                ? t('chooseScenarioTitle', { name: campaigns.find((c) => c.id === selectedCampaignId)?.name ?? '' })
                : t('saveScenarioTitle')}
            </DialogTitle>
          </DialogHeader>

          {!selectedCampaignId ? (
            <div className='space-y-2'>
              <p className='text-xs text-muted-foreground'>{t('stepsRecorded', { count: steps.length })}</p>
              {campaigns.length === 0 ? (
                <p className='text-sm text-muted-foreground'>{t('noCampaign')}</p>
              ) : (
                campaigns.map((c) => (
                  <Button
                    key={c.id}
                    variant='outline'
                    className='w-full justify-start'
                    onClick={() => handlePickCampaign(c.id)}
                    disabled={savingCampaignId !== null}
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
                onClick={() => setSelectedCampaignId(null)}
              >
                {t('chooseCampaignAgain')}
              </Button>
              <Button
                variant='default'
                className='w-full justify-start gap-2'
                onClick={() => saveAsNewScenario(selectedCampaignId)}
                disabled={savingCampaignId !== null}
              >
                <Plus size={13} />
                {savingCampaignId === 'new' ? t('creating') : t('createNewScenario')}
              </Button>
              {campaignScenarios.length > 0 && (
                <>
                  <p className='text-xs text-muted-foreground pt-1'>{t('overwriteExisting')}</p>
                  {campaignScenarios.map((s) => (
                    <Button
                      key={s.id}
                      variant='outline'
                      className='w-full justify-start text-left flex-col items-start h-auto py-2'
                      onClick={() => saveToScenario(selectedCampaignId, s.id)}
                      disabled={savingCampaignId !== null}
                    >
                      <span className='font-medium'>{savingCampaignId === s.id ? t('saving') : s.name}</span>
                      <span className='text-[11px] text-muted-foreground font-normal'>
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

// ── Sortable step item for drag-and-drop ─────────────────────────────────

function SortableStepItem({
  step,
  index,
  onRemove,
}: {
  step: StepWithId;
  index: number;
  onRemove: (i: number) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: step._id,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className='flex items-center gap-1 rounded bg-background px-1 py-1.5 text-xs'
    >
      {/* Drag handle */}
      <button
        {...attributes}
        {...listeners}
        className='flex-shrink-0 cursor-grab px-1 text-muted-foreground hover:text-foreground active:cursor-grabbing'
        title='Drag to reorder'
      >
        &#x2630;
      </button>
      <span className='flex-1 truncate'>
        <ControlRecordStepLabel step={step} />
      </span>
      <Button
        size='icon'
        variant='ghost'
        className='size-6 shrink-0'
        onClick={() => onRemove(index)}
      >
        <Trash2 className='size-3' />
      </Button>
    </div>
  );
}
