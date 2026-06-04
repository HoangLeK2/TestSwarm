'use client';

import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import {
  CheckCircle2,
  Eye,
  EyeOff,
  FileCode,
  MoreHorizontal,
  RotateCcw
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import type { ColumnDef } from '@tanstack/react-table';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
import { cn } from '@/lib/utils';
import type { ScenarioLibraryItem } from '../../lib/scenario-library-item';
import { isSystemTemplateItem } from '../../lib/constants';
import { CloneTemplateDialog } from '../clone-template-dialog';
import { CreateCampaignFromScenarioButton } from '../create-campaign-from-scenario-button';

type TFn = (key: string, values?: Record<string, any>) => string;

function statusVariant(status: string) {
  if (status === 'active') return 'default' as const;
  if (status === 'archived') return 'secondary' as const;
  return 'outline' as const;
}

function statusLabel(t: TFn, status: string) {
  if (status === 'draft') return t('statusDraft');
  if (status === 'active') return t('statusActive');
  if (status === 'archived') return t('statusArchived');
  return status;
}

export function getOrgScenarioColumns(
  t: TFn,
  onOpen: (scenario: ScenarioLibraryItem) => void,
  onArchive: (scenario: ScenarioLibraryItem) => void,
  onRestore: (scenario: ScenarioLibraryItem) => void,
  options?: { showSourceColumn?: boolean }
): ColumnDef<ScenarioLibraryItem>[] {
  const showSource = options?.showSourceColumn !== false;

  const cols: ColumnDef<ScenarioLibraryItem>[] = [
    {
      accessorKey: 'name',
      header: t('colName'),
      cell: ({ row }) => {
        const item = row.original;
        const isSystem = isSystemTemplateItem(item);
        const isArchived = item.status === 'archived';
        return (
          <button
            type='button'
            className='group flex min-w-0 max-w-[280px] items-center gap-3 text-left'
            onClick={() => onOpen(item)}
          >
            <div
              className={cn(
                'flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted/60 transition-colors',
                'group-hover:border-primary/30 group-hover:bg-primary/5'
              )}
            >
              <FileCode className='size-4 text-muted-foreground group-hover:text-primary' />
            </div>
            <div className='min-w-0 flex-1'>
              <span className='block truncate font-medium text-foreground group-hover:text-primary'>
                {item.name}
              </span>
              <span className='mt-0.5 flex flex-wrap items-center gap-1.5'>
                {isArchived ? (
                  <Badge variant='secondary' className='h-5 px-1.5 text-[10px]'>
                    {t('statusArchived')}
                  </Badge>
                ) : null}
                {isSystem ? (
                  <span className='text-[11px] text-muted-foreground'>
                    {t('templateBadge')}
                  </span>
                ) : null}
              </span>
            </div>
          </button>
        );
      }
    }
  ];

  if (showSource) {
    cols.push({
      id: 'source',
      header: t('colSource'),
      cell: ({ row }) =>
        isSystemTemplateItem(row.original) ? (
          <Badge variant='secondary' className='font-normal'>
            {t('templateBadge')}
          </Badge>
        ) : (
          <Badge variant='outline' className='font-normal'>
            {t('orgBadge')}
          </Badge>
        )
    });
  }

  return [
    ...cols,
    {
      accessorKey: 'description',
      header: t('colDescription'),
      cell: ({ row }) => (
        <span className='line-clamp-2 max-w-[240px] text-sm text-muted-foreground'>
          {row.original.description || '—'}
        </span>
      )
    },
    {
      accessorKey: 'status',
      header: t('colStatus'),
      cell: ({ row }) =>
        isSystemTemplateItem(row.original) ? (
          <span className='text-sm text-muted-foreground'>—</span>
        ) : (
          <Badge
            variant={statusVariant(row.original.status)}
            className='font-normal'
          >
            {statusLabel(t, row.original.status)}
          </Badge>
        )
    },
    {
      id: 'runnable',
      header: t('colRunnable'),
      cell: ({ row }) =>
        row.original.is_runnable ? (
          <span className='inline-flex items-center gap-1.5 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-400'>
            <CheckCircle2 className='size-3.5 shrink-0' />
            {t('runnableYes')}
          </span>
        ) : (
          <span className='inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-0.5 text-xs text-muted-foreground'>
            {t('runnableNo')}
          </span>
        )
    },
    {
      accessorKey: 'tags',
      header: t('colTags'),
      cell: ({ row }) => {
        const tags = row.original.tags ?? [];
        if (!tags.length) {
          return <span className='text-sm text-muted-foreground'>—</span>;
        }
        return (
          <div className='flex max-w-[180px] flex-wrap gap-1'>
            {tags.slice(0, 3).map((tag: string) => (
              <Badge key={tag} variant='secondary' className='font-normal'>
                {tag}
              </Badge>
            ))}
            {tags.length > 3 ? (
              <Badge variant='outline' className='font-normal'>
                +{tags.length - 3}
              </Badge>
            ) : null}
          </div>
        );
      }
    },
    {
      accessorKey: 'updated_at',
      header: t('colUpdated'),
      cell: ({ row }) => {
        const date = new Date(row.original.updated_at);
        if (Number.isNaN(date.getTime())) return '—';
        return (
          <span className='whitespace-nowrap text-sm text-muted-foreground'>
            {formatDistanceToNow(date, { addSuffix: true, locale: vi })}
          </span>
        );
      }
    },
    {
      id: 'actions',
      header: () => <span className='sr-only'>{t('colActions')}</span>,
      cell: ({ row }) => (
        <ScenarioRowActions
          scenario={row.original}
          t={t}
          onOpen={onOpen}
          onArchive={onArchive}
          onRestore={onRestore}
        />
      )
    }
  ];
}

function ScenarioRowActions({
  scenario,
  t,
  onOpen,
  onArchive,
  onRestore
}: {
  scenario: ScenarioLibraryItem;
  t: TFn;
  onOpen: (scenario: ScenarioLibraryItem) => void;
  onArchive: (scenario: ScenarioLibraryItem) => void;
  onRestore: (scenario: ScenarioLibraryItem) => void;
}) {
  const perms = useResourcePermissions('scenarios');
  const campaignPerms = useResourcePermissions('campaigns');
  const isSystem = isSystemTemplateItem(scenario);
  const isArchived = scenario.status === 'archived';
  return (
    <div className='flex items-center justify-end gap-1'>
      <Button
        size='sm'
        variant='outline'
        className='hidden h-8 sm:inline-flex'
        onClick={() => onOpen(scenario)}
      >
        {isSystem ? t('previewTemplate') : t('open')}
      </Button>

      {isSystem && perms.canCreate ? (
        <CloneTemplateDialog
          template={scenario}
          variant='outline'
          className='h-8'
        />
      ) : null}

      {!isSystem && !isArchived && campaignPerms.canCreate ? (
        <CreateCampaignFromScenarioButton
          scenarioId={scenario.id}
          scenarioName={scenario.name}
          isRunnable={scenario.is_runnable}
          variant='default'
          className='hidden h-8 lg:inline-flex'
        />
      ) : null}

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size='sm'
            variant='ghost'
            className='size-8 p-0'
            aria-label={t('colActions')}
          >
            <MoreHorizontal className='size-4' />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end' className='w-52'>
          <DropdownMenuItem
            className='gap-2 sm:hidden'
            onClick={() => onOpen(scenario)}
          >
            <Eye className='size-4' />
            {isSystem ? t('previewTemplate') : t('open')}
          </DropdownMenuItem>
          {!isSystem && !isArchived && campaignPerms.canCreate ? (
            <DropdownMenuItem
              className='gap-2 lg:hidden'
              onSelect={(e) => e.preventDefault()}
            >
              <CreateCampaignFromScenarioButton
                scenarioId={scenario.id}
                scenarioName={scenario.name}
                isRunnable={scenario.is_runnable}
                variant='outline'
                className='h-8 w-full'
              />
            </DropdownMenuItem>
          ) : null}
          {!isSystem && isArchived && perms.canUpdate ? (
            <DropdownMenuItem
              className='gap-2'
              onClick={() => onRestore(scenario)}
            >
              <RotateCcw className='size-4' />
              {t('restoreShort')}
            </DropdownMenuItem>
          ) : null}
          {!isSystem && !isArchived && perms.canDelete ? (
            <>
              {(perms.canUpdate || campaignPerms.canCreate) && (
                <DropdownMenuSeparator />
              )}
              <DropdownMenuItem
                className='gap-2 text-destructive focus:text-destructive'
                onClick={() => onArchive(scenario)}
              >
                <EyeOff className='size-4' />
                {t('archive')}
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
