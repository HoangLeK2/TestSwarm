'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { AlertCircle, Code2, List, SlidersHorizontal } from 'lucide-react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { DeviceVarsJsonPanel } from '@/components/device-vars-json-panel';
import { cn } from '@/lib/utils';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import { RecoveryPolicyEditor } from '@/features/campaigns/components/recovery-policy-editor';
import type {
  CampaignDeviceOut,
  RecoveryPolicy
} from '@/features/campaigns/types';
import type { ScenarioTemplateOut } from '@/features/scenario-templates/services/api';

const VariableEditor = dynamic(
  () => import('@/components/variable-editor').then((m) => m.VariableEditor),
  { ssr: false }
);

type DeviceVarsPanelState = {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  draft: string;
  onDraftChange: (value: string) => void;
  jsonError?: string;
  deviceLabel?: string;
  baseVariables?: Record<string, unknown>;
  globalVariablesPreview?: Record<string, unknown>;
};

function serializeVariables(variables: Record<string, any>) {
  return JSON.stringify(variables);
}

export function ControlRecordVariablesDialog({
  open,
  onOpenChange,
  variables,
  onVariablesChange,
  savePending,
  saveDisabled,
  labels
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  variables: Record<string, any>;
  onVariablesChange: (
    variables: Record<string, any>
  ) => void | Promise<unknown>;
  savePending?: boolean;
  saveDisabled?: boolean;
  labels: {
    title: string;
    variableCount: string | null;
    headerSubtitleLead: string;
    headerSubtitleTrail: string;
    pageSummary?: string;
    pageSummaryWarning?: string;
    cancel: string;
    save: string;
    saving: string;
  };
}) {
  const variableCount = Object.keys(variables).length;
  const [submitting, setSubmitting] = useState(false);
  const [draftVariables, setDraftVariables] =
    useState<Record<string, any>>(variables);
  const committedSignature = useMemo(
    () => serializeVariables(variables),
    [variables]
  );
  const draftSignature = useMemo(
    () => serializeVariables(draftVariables),
    [draftVariables]
  );
  const hasDraftChanges = draftSignature !== committedSignature;
  const isSaving = submitting || savePending === true;

  useEffect(() => {
    if (open) setDraftVariables(variables);
  }, [open, variables]);

  const closeAndDiscard = useCallback(() => {
    setDraftVariables(variables);
    onOpenChange(false);
  }, [onOpenChange, variables]);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (isSaving) return;
      if (!nextOpen) {
        closeAndDiscard();
        return;
      }
      onOpenChange(true);
    },
    [closeAndDiscard, isSaving, onOpenChange]
  );

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (isSaving || saveDisabled) return;
      if (!hasDraftChanges) {
        onOpenChange(false);
        return;
      }
      setSubmitting(true);
      try {
        await onVariablesChange(draftVariables);
        onOpenChange(false);
      } catch {
        // Caller owns the toast; keep the dialog open so the draft is not lost.
      } finally {
        setSubmitting(false);
      }
    },
    [
      draftVariables,
      hasDraftChanges,
      isSaving,
      onOpenChange,
      onVariablesChange,
      saveDisabled
    ]
  );

  const preventInputEnterSubmit = useCallback(
    (event: KeyboardEvent<HTMLFormElement>) => {
      if (event.defaultPrevented || event.key !== 'Enter') return;
      const target = event.target;
      if (target instanceof HTMLInputElement) {
        event.preventDefault();
      }
    },
    []
  );

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className='!grid max-h-[min(85dvh,720px)] max-w-2xl grid-rows-[auto_minmax(0,1fr)_auto] gap-3 overflow-hidden'>
        <form
          className='contents'
          onSubmit={handleSubmit}
          onKeyDown={preventInputEnterSubmit}
        >
          <DialogHeader className='shrink-0 space-y-1.5'>
            <DialogTitle className='flex flex-wrap items-center gap-2 text-base'>
              <SlidersHorizontal className='size-4 shrink-0' />
              {labels.title}
              {variableCount > 0 && labels.variableCount ? (
                <Badge
                  variant='secondary'
                  className='h-6 text-[11px] font-normal'
                >
                  {labels.variableCount}
                </Badge>
              ) : null}
            </DialogTitle>
            <DialogDescription className='text-xs'>
              {labels.headerSubtitleLead}{' '}
              <code className='rounded bg-muted/80 px-1 py-0.5 font-mono text-[11px] text-foreground'>
                {'${VAR}'}
              </code>{' '}
              {labels.headerSubtitleTrail}
            </DialogDescription>
            {labels.pageSummary ? (
              <p className='rounded-md border border-border/70 bg-muted/40 px-2 py-1.5 text-xs text-muted-foreground'>
                {labels.pageSummary}
                {labels.pageSummaryWarning ? (
                  <span className='ml-2 font-medium text-amber-700 dark:text-amber-300'>
                    {labels.pageSummaryWarning}
                  </span>
                ) : null}
              </p>
            ) : null}
          </DialogHeader>
          <div className='min-h-0 overflow-y-auto overscroll-y-contain pr-1 [-webkit-overflow-scrolling:touch]'>
            <VariableEditor
              variables={draftVariables}
              onChange={setDraftVariables}
              disabled={isSaving || saveDisabled}
            />
          </div>
          <div className='flex justify-end gap-2 border-t pt-3'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={isSaving}
              onClick={closeAndDiscard}
            >
              {labels.cancel}
            </Button>
            <Button
              type='submit'
              size='sm'
              disabled={!hasDraftChanges || isSaving || saveDisabled}
            >
              {isSaving ? labels.saving : labels.save}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ControlRecordDeviceVarsDialog({
  open,
  onOpenChange,
  campaignDevices,
  selectedScenarioDeviceId,
  deviceVarEnabledByDevice,
  selectScenarioDeviceForVars,
  panel,
  onCancel,
  onSave,
  saveDisabled,
  saveLabel,
  labels
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  campaignDevices: CampaignDeviceOut[];
  selectedScenarioDeviceId: string | null;
  deviceVarEnabledByDevice: Record<string, boolean>;
  selectScenarioDeviceForVars: (id: string, serial: string) => void;
  panel: DeviceVarsPanelState;
  onCancel: () => void;
  onSave: () => void;
  saveDisabled: boolean;
  saveLabel: string;
  labels: {
    title: string;
    scopeHint: string;
    instructions: string;
    noDevicesInCampaign: string;
    badgePerDevice: string;
    badgeGlobal: string;
    cancel: string;
  };
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='!grid max-h-[min(88dvh,760px)] !w-[min(94vw,980px)] !max-w-[980px] grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-4 overflow-hidden'>
        <DialogHeader className='shrink-0'>
          <DialogTitle className='flex items-center gap-2 text-base'>
            <SlidersHorizontal className='size-4' />
            {labels.title}
          </DialogTitle>
        </DialogHeader>
        <p className='-mt-1 shrink-0 text-[12px] text-muted-foreground'>
          {labels.scopeHint}
        </p>
        <div className='shrink-0 rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground'>
          {labels.instructions}
        </div>
        <div className='min-h-0 overflow-y-auto overscroll-y-contain pr-1 [-webkit-overflow-scrolling:touch]'>
          {campaignDevices.length === 0 ? (
            <p className='text-xs text-muted-foreground'>
              {labels.noDevicesInCampaign}
            </p>
          ) : (
            <div className='grid min-h-[430px] grid-cols-[260px_1fr] divide-x rounded-md border'>
              <div className='min-h-0 overflow-y-auto p-2'>
                {campaignDevices.map((d) => {
                  const active = selectedScenarioDeviceId === d.id;
                  const enabled = deviceVarEnabledByDevice[d.id] === true;
                  return (
                    <button
                      key={d.id}
                      type='button'
                      className={cn(
                        'mb-1 flex w-full items-center gap-2 rounded border border-transparent px-2 py-2 text-left text-xs hover:bg-muted/60',
                        active && 'border-primary/30 bg-primary/[0.06]'
                      )}
                      onClick={() =>
                        selectScenarioDeviceForVars(d.id, d.serial)
                      }
                    >
                      <span className='min-w-0 flex-1'>
                        <span className='block truncate font-medium'>
                          {d.name || d.serial}
                        </span>
                        <span className='block truncate font-mono text-[10px] text-muted-foreground'>
                          {d.serial}
                        </span>
                      </span>
                      <Badge
                        variant={enabled ? 'default' : 'secondary'}
                        className='shrink-0 text-[10px]'
                      >
                        {enabled ? labels.badgePerDevice : labels.badgeGlobal}
                      </Badge>
                    </button>
                  );
                })}
              </div>
              <div className='min-h-0 p-4'>
                <DeviceVarsJsonPanel
                  {...panel}
                  editorClassName='min-h-[330px]'
                  emptyClassName='min-h-[330px]'
                />
              </div>
            </div>
          )}
        </div>
        <div className='flex justify-end gap-2'>
          <Button variant='outline' size='sm' onClick={onCancel}>
            {labels.cancel}
          </Button>
          <Button size='sm' onClick={onSave} disabled={saveDisabled}>
            {saveLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ControlRecordRecoveryDialog({
  open,
  onOpenChange,
  activeCampaignId,
  selectedSerial,
  value,
  onChange,
  savePending,
  onBeforeRecord,
  onCancel,
  onSave,
  labels
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  activeCampaignId: string | null;
  selectedSerial: string | null;
  value: RecoveryPolicy;
  onChange: (value: RecoveryPolicy) => void;
  savePending: boolean;
  onBeforeRecord: (policy: RecoveryPolicy) => Promise<void>;
  onCancel: () => void;
  onSave: () => void;
  labels: {
    title: string;
    description: string;
    standaloneWarning: string;
    cancel: string;
    saving: string;
    save: string;
  };
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='flex max-h-[min(88dvh,720px)] max-w-lg flex-col gap-0 overflow-hidden p-0 sm:max-w-xl'>
        <DialogHeader className='space-y-1.5 border-b px-5 py-4'>
          <DialogTitle className='flex items-center gap-2 text-base'>
            <AlertCircle className='size-4 shrink-0 text-amber-600' />
            {labels.title}
          </DialogTitle>
          <DialogDescription className='text-xs leading-relaxed'>
            {labels.description}
          </DialogDescription>
        </DialogHeader>

        <div className='min-h-0 flex-1 overflow-y-auto px-5 py-4'>
          {!activeCampaignId ? (
            <p className='bg-amber-500/8 mb-3 rounded-md border border-amber-500/25 px-3 py-2 text-xs leading-relaxed text-amber-900 dark:text-amber-100'>
              {labels.standaloneWarning}
            </p>
          ) : null}
          <RecoveryPolicyEditor
            value={value}
            onChange={onChange}
            disabled={savePending}
            recordCampaignId={activeCampaignId}
            recordDeviceSerial={selectedSerial}
            variant='embedded'
            scenarioFilter='recovery'
            onBeforeRecord={onBeforeRecord}
          />
        </div>

        <div className='flex justify-end gap-2 border-t px-5 py-3'>
          <Button variant='ghost' size='sm' onClick={onCancel}>
            {labels.cancel}
          </Button>
          <Button
            size='sm'
            onClick={onSave}
            disabled={!activeCampaignId || savePending}
          >
            {savePending ? labels.saving : labels.save}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ControlRecordJsonDialog({
  open,
  onOpenChange,
  steps,
  labels
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  steps: Record<string, any>[];
  labels: {
    title: string;
    stepCount: string;
  };
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[min(90dvh,920px)] max-w-2xl grid-rows-[auto_minmax(0,1fr)] gap-4 overflow-hidden'>
        <DialogHeader className='shrink-0'>
          <DialogTitle className='flex flex-wrap items-center gap-2 pr-8 text-base'>
            <Code2 className='size-4 shrink-0' />
            {labels.title}
            {steps.length > 0 && (
              <span className='rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary'>
                {labels.stepCount}
              </span>
            )}
          </DialogTitle>
        </DialogHeader>
        <div className='flex min-h-0 flex-col'>
          <pre className='min-h-0 max-w-full flex-1 overflow-x-auto overflow-y-auto overscroll-y-contain rounded-md border border-border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed'>
            {JSON.stringify(
              steps.map((s: any) => {
                const { _id, ...rest } = s;
                void _id;
                return rest;
              }),
              null,
              2
            )}
          </pre>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ControlRecordExitConfirmDialog({
  open,
  onOpenChange,
  onConfirm,
  labels
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  labels: {
    title: string;
    description: string;
    cancel: string;
    confirm: string;
  };
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{labels.title}</AlertDialogTitle>
          <AlertDialogDescription>{labels.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{labels.cancel}</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            {labels.confirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function ControlRecordTakeoverConfirmDialog({
  open,
  onOpenChange,
  pending,
  onConfirm,
  labels
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pending: boolean;
  onConfirm: () => void;
  labels: {
    title: string;
    description: string;
    cancel: string;
    confirm: string;
  };
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{labels.title}</AlertDialogTitle>
          <AlertDialogDescription>{labels.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>
            {labels.cancel}
          </AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={(e) => {
              e.preventDefault();
              onConfirm();
            }}
          >
            {labels.confirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function ControlRecordTemplatePreviewDialog({
  template,
  onOpenChange,
  onCancel,
  onAppend,
  labels
}: {
  template: ScenarioTemplateOut | null;
  onOpenChange: (open: boolean) => void;
  onCancel: () => void;
  onAppend: () => void;
  labels: {
    builtinBadge: string;
    formatStepCount: (count: number) => string;
    noSteps: string;
    cancel: string;
    append: string;
  };
}) {
  return (
    <Dialog open={template !== null} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-xl'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            <List className='size-4 text-emerald-600' />
            <span className='truncate'>{template?.name ?? ''}</span>
            {template?.is_builtin && (
              <Badge
                variant='secondary'
                className='h-5 px-1.5 text-[10px] font-semibold uppercase tracking-wide'
              >
                {labels.builtinBadge}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>
        {template && (
          <div className='space-y-3'>
            {template.description && (
              <p className='text-xs leading-relaxed text-muted-foreground'>
                {template.description}
              </p>
            )}
            <div className='flex items-center gap-2 text-xs text-muted-foreground'>
              <span className='font-semibold text-foreground/80'>
                {labels.formatStepCount(
                  Array.isArray(template.steps) ? template.steps.length : 0
                )}
              </span>
              {template.category && <span>· {template.category}</span>}
            </div>
            <div className='max-h-[50vh] overflow-y-auto rounded-md border border-border/60 bg-muted/30 p-2'>
              {Array.isArray(template.steps) && template.steps.length > 0 ? (
                <ol className='space-y-1'>
                  {template.steps.map((step: any, i: number) => {
                    const type =
                      typeof step?.type === 'string' ? step.type : 'unknown';
                    return (
                      <li
                        key={i}
                        className='flex items-start gap-2 rounded border border-border/40 bg-background px-2 py-1.5 text-xs'
                      >
                        <span className='flex h-5 w-5 shrink-0 items-center justify-center rounded bg-indigo-50 text-indigo-600 ring-1 ring-inset ring-indigo-100'>
                          <StepIcon type={type as any} size={12} />
                        </span>
                        <span className='min-w-0 flex-1'>
                          <span className='mr-1 text-[10px] font-semibold uppercase text-muted-foreground'>
                            #{i + 1}
                          </span>
                          <span className='font-medium text-foreground/90'>
                            {type}
                          </span>
                          {(step?.name || step?.label) && (
                            <span className='ml-1 text-muted-foreground'>
                              · {String(step.name || step.label)}
                            </span>
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <p className='py-4 text-center text-xs text-muted-foreground'>
                  {labels.noSteps}
                </p>
              )}
            </div>
            <div className='flex items-center justify-end gap-2 pt-1'>
              <Button variant='outline' size='sm' onClick={onCancel}>
                {labels.cancel}
              </Button>
              <Button
                size='sm'
                onClick={onAppend}
                disabled={
                  !Array.isArray(template.steps) || template.steps.length === 0
                }
              >
                {labels.append}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
