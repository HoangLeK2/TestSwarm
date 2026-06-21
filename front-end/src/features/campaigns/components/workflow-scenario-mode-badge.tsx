'use client';

import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { useTranslations } from 'next-intl';

export function WorkflowScenarioModeBadge({
  mode,
  scenarioName,
  className
}: {
  mode: 'main' | 'recovery';
  scenarioName?: string | null;
  className?: string;
}) {
  const t = useTranslations('campaignsFeature.list');
  const isRecovery = mode === 'recovery';

  return (
    <Badge
      variant='secondary'
      title={scenarioName ?? undefined}
      className={cn(
        'h-4 max-w-[9rem] shrink-0 truncate px-1.5 text-[9px] font-bold',
        isRecovery &&
          'border-sky-500/30 bg-sky-500/10 text-sky-800 dark:text-sky-200',
        className
      )}
    >
      {isRecovery && scenarioName?.trim()
        ? scenarioName.trim()
        : t(
            isRecovery
              ? 'monitorScenarioModeRecovery'
              : 'monitorScenarioModeMain'
          )}
    </Badge>
  );
}
