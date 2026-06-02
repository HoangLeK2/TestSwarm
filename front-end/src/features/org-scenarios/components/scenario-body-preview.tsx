'use client';

import dynamic from 'next/dynamic';
import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import {
  countScenarioVariables,
  extractPreviewSteps
} from '../lib/parse-scenario-body';

const FlowEditor = dynamic(
  () =>
    import('@/features/campaigns/components/flow-editor').then(
      (m) => m.FlowEditor
    ),
  {
    ssr: false,
    loading: () => (
      <div className='h-40 animate-pulse rounded-lg border bg-muted/30' />
    )
  }
);

export function ScenarioBodyPreview({
  body,
  kind,
  rawJson
}: {
  body: Record<string, unknown> | null | undefined;
  kind?: string;
  rawJson?: string;
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
          <span>
            {t('stepsPreviewCount', { count: steps.length })}
          </span>
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
        <p className='rounded-lg border border-dashed bg-muted/20 px-3 py-4 text-sm text-muted-foreground'>
          {t('emptyBodyPreview')}
        </p>
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
            <pre className='max-h-48 overflow-auto rounded-lg border bg-muted/20 p-3 font-mono text-[10px] leading-relaxed whitespace-pre-wrap break-all'>
              {rawJson}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
