'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FlowEditor } from '@/features/campaigns/components/flow-editor/flow-editor';
import {
  countScenarioVariables,
  extractPreviewSteps
} from '../lib/parse-scenario-body';
import { ImportOrgScenarioInlineTrigger } from './import-scenario-dialog';

export function ScenarioBodyPreview({
  body,
  kind,
  rawJson,
  importTargetScenarioId,
  onImported
}: {
  body: Record<string, unknown> | null | undefined;
  kind?: string;
  rawJson?: string;
  importTargetScenarioId?: string;
  onImported?: () => void;
}) {
  const t = useTranslations('orgScenariosFeature.detail');
  const [showRaw, setShowRaw] = useState(false);

  const steps = useMemo(() => extractPreviewSteps(body), [body]);
  const variableCount = useMemo(
    () =>
      countScenarioVariables(
        body?.variables as Record<string, unknown> | undefined
      ),
    [body]
  );

  const hasFlow = steps.length > 0;

  return (
    <div className='space-y-3'>
      <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
        {kind ? (
          <Badge variant='outline' className='font-normal'>
            {kind === 'graph' ? t('kind.graph') : t('kind.sequence')}
          </Badge>
        ) : null}
        {hasFlow ? (
          <span>{t('stepsPreviewCount', { count: steps.length })}</span>
        ) : (
          <span>{t('noStepsPreview')}</span>
        )}
        {variableCount > 0 ? (
          <span>{t('variablesCount', { count: variableCount })}</span>
        ) : null}
      </div>

      {hasFlow ? (
        <div className='min-w-0 overflow-hidden rounded-lg border bg-background'>
          <FlowEditor
            nestedInDialog
            steps={steps}
            onChange={() => {}}
            maxHeight='min(52vh, 520px)'
            compact
          />
        </div>
      ) : (
        <div className='rounded-lg border border-dashed bg-muted/20 px-3 py-4 text-sm text-muted-foreground'>
          <p>{t('emptyBodyPreview')}</p>
          {importTargetScenarioId ? (
            <p className='mt-2'>
              <ImportOrgScenarioInlineTrigger
                targetScenarioId={importTargetScenarioId}
                onImported={onImported}
              >
                <span className='cursor-pointer font-medium text-primary underline-offset-4 hover:underline'>
                  {t('emptyBodyImportLink')}
                </span>
              </ImportOrgScenarioInlineTrigger>
              {' · '}
              <span>{t('emptyBodyOrRecord')}</span>
            </p>
          ) : null}
        </div>
      )}

      {rawJson ? (
        <div className='space-y-2'>
          <Button
            type='button'
            variant='ghost'
            size='sm'
            className='h-8 gap-1.5 px-2 text-xs text-muted-foreground'
            onClick={() => setShowRaw((v) => !v)}
          >
            {showRaw ? (
              <ChevronDown className='size-3.5' />
            ) : (
              <ChevronRight className='size-3.5' />
            )}
            {t('toggleRawJson')}
          </Button>
          {showRaw ? (
            <pre className='max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg border bg-muted/20 p-3 font-mono text-[10px] leading-relaxed'>
              {rawJson}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
