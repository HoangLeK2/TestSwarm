'use client';

import Link from 'next/link';
import { DeviceTile } from './device-tile';
import { Button } from '@/components/ui/button';
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
  RefreshCw
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { useControlRecord } from '../hooks/use-control-record';
import { ControlRecordStepLabel } from './control-record/step-label';
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
    toggleRecording
  } = useControlRecord(initialSerial);

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
        <div className='w-full shrink-0 lg:w-auto' style={{ maxWidth: 360 }}>
          {selectedDevice && (
            <DeviceTile
              device={selectedDevice}
              logLines={logs[selectedDevice.serial] ?? []}
              mode={mode}
              wsSend={sendAndRecord}
              onToggleMode={handleToggleMode}
              onRestart={handleRestart}
            />
          )}
        </div>

        <Card className=''>
          <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
            <CardTitle className='text-sm'>{t('scenarioCardTitle')}</CardTitle>
            <div className='flex items-center gap-2'>
              {recording && selectedDevice && (
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
            </div>
          </CardHeader>
          <CardContent className='space-y-3'>
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
              <Button size='sm' variant='outline' onClick={loadHierarchy} disabled={!selectedDevice}>
                {t('getHierarchy')}
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
            <div className='max-h-[320px] space-y-1 overflow-y-auto rounded border border-border/60 bg-muted/30 p-2'>
              {steps.length === 0 ? (
                <p className='py-4 text-center text-xs text-muted-foreground'>
                  {t('noSteps')}
                </p>
              ) : (
                steps.map((step, i) => (
                  <div
                    key={i}
                    className='flex items-center justify-between gap-2 rounded bg-background px-2 py-1.5 text-xs'
                  >
                    <ControlRecordStepLabel step={step} />
                    <Button
                      size='icon'
                      variant='ghost'
                      className='size-6 shrink-0'
                      onClick={() => removeStep(i)}
                    >
                      <Trash2 className='size-3' />
                    </Button>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Dialog open={hierarchyOpen} onOpenChange={setHierarchyOpen}>
        <DialogContent className='max-w-5xl max-h-[90vh] flex flex-col gap-4'>
          <DialogHeader className='gap-1'>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <DialogTitle className='text-base'>UI Hierarchy (uiautomator2)</DialogTitle>
              <div className='flex items-center gap-2'>
                <span className='text-xs text-muted-foreground'>{t('autoRefresh')}</span>
                <Button size='sm' variant='outline' onClick={refreshHierarchy} disabled={!selectedDevice}>
                  {t('refreshNow')}
                </Button>
              </div>
            </div>
            <p className='text-xs text-muted-foreground'>
              {t('hierarchyHint')}
            </p>
          </DialogHeader>
          <div className='grid grid-cols-1 lg:grid-cols-[1fr,320px] gap-4 flex-1 min-h-0'>
            <div className='rounded-lg border bg-muted/30 overflow-hidden min-h-[240px]'>
              <div className='bg-muted/60 px-3 py-1.5 text-xs font-medium text-muted-foreground border-b'>
                {t('xmlDump')}
              </div>
              <pre className='p-3 text-[10px] font-mono whitespace-pre-wrap break-all overflow-auto max-h-[50vh]'>
                {hierarchyXml === 'Đang tải…' || hierarchyXml === 'Loading…'
                  ? t('loading')
                  : hierarchyXml.startsWith('Lỗi:') || hierarchyXml.startsWith('Error:')
                    ? hierarchyXml
                    : !hierarchyXml || hierarchyXml.trim() === ''
                      ? t('hierarchyUnavailable')
                      : hierarchyXml}
              </pre>
            </div>
            <div className='rounded-lg border bg-card overflow-hidden flex flex-col min-h-0'>
              <div className='bg-muted/60 px-3 py-1.5 flex items-center justify-between border-b'>
                <span className='text-xs font-medium'>{t('chooseSelector')}</span>
                <span className='text-[10px] text-muted-foreground'>
                  {parsedHierarchyNodes.length} mục
                </span>
              </div>
              <div className='flex-1 overflow-auto p-2'>
                {parsedHierarchyNodes.length === 0 ? (
                  <div className='p-3 text-xs text-muted-foreground space-y-1'>
                    <p>{t('selectorNotFound')}</p>
                    <p>{t('selectorNeedAccessibility')}</p>
                    <code className='block mt-2 p-2 rounded bg-muted text-[10px]'>
                      Cài đặt → Trợ năng → STFService → Bật
                    </code>
                  </div>
                ) : (
                  <ul className='space-y-1'>
                    {parsedHierarchyNodes.map((n) => (
                      <li key={n.id}>
                        <button
                          type='button'
                          className='w-full text-left rounded-md px-2 py-2 hover:bg-muted/80 focus:bg-muted/80 focus:outline-none border border-transparent hover:border-border transition-colors'
                          onClick={() => {
                            setSelectorBy(n.by);
                            setSelectorValue(n.value);
                            setHierarchyOpen(false);
                          }}
                        >
                          <div className='flex items-center gap-1.5 flex-wrap'>
                            <span className='inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-medium bg-primary/10 text-primary'>
                              {n.by}
                            </span>
                            {n.clickable && (
                              <span className='text-[9px] text-muted-foreground'>clickable</span>
                            )}
                          </div>
                          <div className='mt-0.5 truncate text-xs font-medium' title={n.label}>
                            {n.label}
                          </div>
                          {n.package && (
                            <div className='mt-0.5 text-[10px] text-muted-foreground truncate' title={n.package}>
                              {n.package}
                            </div>
                          )}
                          <div className='mt-0.5 text-[9px] text-muted-foreground font-mono truncate' title={n.value}>
                            {n.value.length > 56 ? `${n.value.slice(0, 56)}…` : n.value}
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

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
