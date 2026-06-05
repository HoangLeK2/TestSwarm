'use client';

import { useRef, useState, type ReactNode } from 'react';
import { FileUp, Loader2, Upload } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { useImportOrgScenario } from '../hooks/use-org-scenarios';
import {
  ImportResolveModeField,
  type ImportResolveMode
} from './import-resolve-mode-field';

export function ImportOrgScenarioDialog({
  targetScenarioId,
  onImported,
  triggerLabel,
  triggerVariant = 'outline',
  triggerSize = 'sm'
}: {
  /** Import body into this scenario (detail tab). Omit to create a new library scenario. */
  targetScenarioId?: string;
  onImported?: (scenarioId: string) => void;
  triggerLabel?: string;
  triggerVariant?: 'default' | 'outline' | 'secondary' | 'ghost';
  triggerSize?: 'default' | 'sm' | 'lg' | 'icon';
}) {
  const t = useTranslations('orgScenariosFeature.importDialog');
  const intoExisting = Boolean((targetScenarioId ?? '').trim());
  const [open, setOpen] = useState(false);
  const [resolve, setResolve] = useState<ImportResolveMode>('create_stub');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { mutate, isPending, error, reset } = useImportOrgScenario();

  const clearFile = () => {
    setSelectedFile(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      reset();
      clearFile();
    }
  };

  const runImport = () => {
    if (!selectedFile) return;
    mutate(
      {
        file: selectedFile,
        resolve,
        targetScenarioId: intoExisting ? targetScenarioId : undefined
      },
      {
        onSuccess: (data) => {
          reset();
          setOpen(false);
          clearFile();
          const id = intoExisting
            ? (targetScenarioId ?? '')
            : (data.scenario_id ?? '');
          if (intoExisting) {
            toast.success(t('intoExistingSuccess'));
          } else {
            toast.success(t('importSuccess'));
          }
          for (const warning of data.warnings ?? []) {
            if (typeof warning === 'string' && warning.trim()) {
              toast.warning(warning.trim());
            }
          }
          if (id) onImported?.(id);
        }
      }
    );
  };

  const title = intoExisting ? t('intoExistingTitle') : t('title');
  const hint = intoExisting ? t('intoExistingHint') : t('hint');
  const triggerText = triggerLabel ?? t('trigger');
  const failedMessage = intoExisting
    ? t('intoExistingFailed')
    : t('importFailed');

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size={triggerSize} variant={triggerVariant}>
          <Upload size={16} className='mr-1' />
          {triggerText}
        </Button>
      </DialogTrigger>
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{hint}</DialogDescription>
        </DialogHeader>
        <div className='space-y-4'>
          <input
            ref={inputRef}
            type='file'
            accept='.yaml,.yml,.json,application/json,text/yaml'
            className='hidden'
            disabled={isPending}
            onChange={(event) => {
              const file = event.target.files?.[0];
              setSelectedFile(file ?? null);
            }}
          />
          <div className='space-y-2'>
            <Button
              type='button'
              variant='outline'
              className='w-full'
              disabled={isPending}
              onClick={() => inputRef.current?.click()}
            >
              <FileUp className='mr-2 size-4' />
              {t('selectFile')}
            </Button>
            {selectedFile ? (
              <p className='text-xs text-muted-foreground'>
                {t('selectedFile', { name: selectedFile.name })}
              </p>
            ) : null}
          </div>
          <ImportResolveModeField
            value={resolve}
            disabled={isPending}
            onChange={setResolve}
          />
          {error ? (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, failedMessage)}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            disabled={isPending}
            onClick={() => handleOpenChange(false)}
          >
            {t('cancel')}
          </Button>
          <Button
            type='button'
            disabled={!selectedFile || isPending}
            onClick={runImport}
          >
            {isPending ? (
              <Loader2 className='mr-2 size-4 animate-spin' />
            ) : (
              <Upload className='mr-2 size-4' />
            )}
            {isPending ? t('importing') : t('submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Inline import control for empty body preview areas. */
export function ImportOrgScenarioInlineTrigger({
  targetScenarioId,
  onImported,
  children
}: {
  targetScenarioId: string;
  onImported?: (scenarioId: string) => void;
  children: ReactNode;
}) {
  const t = useTranslations('orgScenariosFeature.importDialog');
  const inputRef = useRef<HTMLInputElement>(null);
  const { mutate, isPending } = useImportOrgScenario();

  return (
    <>
      <input
        ref={inputRef}
        type='file'
        accept='.yaml,.yml,.json,application/json,text/yaml'
        className='sr-only'
        disabled={isPending}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          mutate(
            { file, targetScenarioId, resolve: 'create_stub' },
            {
              onSuccess: (data) => {
                toast.success(t('intoExistingSuccess'));
                for (const warning of data.warnings ?? []) {
                  if (typeof warning === 'string' && warning.trim()) {
                    toast.warning(warning.trim());
                  }
                }
                onImported?.(targetScenarioId);
                if (inputRef.current) inputRef.current.value = '';
              },
              onError: (error) =>
                toast.error(formatFarmApiError(error, t('intoExistingFailed')))
            }
          );
        }}
      />
      <span
        role='button'
        tabIndex={0}
        className='inline'
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        {children}
      </span>
    </>
  );
}
