'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { FileCode, Search } from 'lucide-react';
import { toast } from 'sonner';
import { useSearchParams } from 'next/navigation';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { Can } from '@/features/auth';
import { useUser } from '@/features/auth/hooks/use-auth';
import { CreateTemplateDialog } from '@/features/scenario-templates/components/create-template-dialog';
import { useConfirm } from '@/providers/modal-provider';
import { isSuperadminRole } from '@/lib/nav-access';
import { cn } from '@/lib/utils';
import {
  useArchiveOrgScenario,
  useOrgScenarios,
  useRestoreOrgScenario,
  useScenarioTemplatesCatalog
} from '../../hooks/use-org-scenarios';
import {
  orgScenarioToLibraryItem,
  templateToLibraryItem,
  type ScenarioLibraryItem
} from '../../lib/scenario-library-item';
import { isSystemTemplateItem } from '../../lib/constants';
import { CreateOrgScenarioDialog } from '../create-scenario-dialog';
import { ImportOrgScenarioDialog } from '../import-scenario-dialog';
import { ScenarioDetailSheet } from '../scenario-detail-sheet';
import { getOrgScenarioColumns } from './columns';
import { isOrgScenarioVisibleInLibrary } from '../../lib/campaign-scenario-eligibility';

type LibraryTab = 'org' | 'system';
type ScenarioRoleFilter = 'all' | 'regular' | 'recovery';

function isRecoveryScenario(item: ScenarioLibraryItem): boolean {
  return (
    item.is_recovery_scenario === true || (item.recovery_usage_count ?? 0) > 0
  );
}

export function ScenarioLibrary() {
  const t = useTranslations('orgScenariosFeature.list');
  const tCommon = useTranslations('common');
  const searchParams = useSearchParams();
  const router = useRouter();
  const { user } = useUser();
  const isSuperadmin = isSuperadminRole(user?.role);
  const confirm = useConfirm();
  const [search, setSearch] = useState('');
  const [showHidden, setShowHidden] = useState(false);
  const [roleFilter, setRoleFilter] = useState<ScenarioRoleFilter>('all');
  const [activeTab, setActiveTab] = useState<LibraryTab>('org');
  const [selected, setSelected] = useState<ScenarioLibraryItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  /** Prevents deep-link effect from reopening sheet after user closes it while URL still has scenario_id. */
  const openedDeepLinkRef = useRef<string | null>(null);

  const {
    data: orgScenarios,
    isLoading: orgLoading,
    error: orgError
  } = useOrgScenarios({ include_archived: showHidden });
  const {
    data: templates,
    isLoading: templatesLoading,
    error: templatesError
  } = useScenarioTemplatesCatalog();
  const archiveMutation = useArchiveOrgScenario();
  const restoreMutation = useRestoreOrgScenario();

  const isLoading = activeTab === 'org' ? orgLoading : templatesLoading;
  const error = activeTab === 'org' ? orgError : templatesError;

  const orgLibraryItems = useMemo(
    () =>
      (orgScenarios ?? [])
        .filter((s) => isOrgScenarioVisibleInLibrary(s))
        .map((scenario) => orgScenarioToLibraryItem(scenario)),
    [orgScenarios]
  );

  const counts = useMemo(() => {
    const visibleOrg = orgLibraryItems.filter(
      (s) => s.status !== 'archived'
    ).length;
    const hiddenOrg = orgLibraryItems.filter(
      (s) => s.status === 'archived'
    ).length;
    const recovery = orgLibraryItems.filter(
      (s) => s.status !== 'archived' && isRecoveryScenario(s)
    ).length;
    const regular = orgLibraryItems.filter(
      (s) => s.status !== 'archived' && !isRecoveryScenario(s)
    ).length;
    const system = (templates ?? []).length;
    return { org: visibleOrg, hidden: hiddenOrg, system, recovery, regular };
  }, [orgLibraryItems, templates]);

  const filtered = useMemo(() => {
    let items: ScenarioLibraryItem[] =
      activeTab === 'system'
        ? (templates ?? []).map(templateToLibraryItem)
        : orgLibraryItems;

    if (activeTab === 'org' && !showHidden) {
      items = items.filter((item) => item.status !== 'archived');
    }

    if (activeTab === 'org' && roleFilter !== 'all') {
      items = items.filter((item) => {
        const isRecovery = isRecoveryScenario(item);
        return roleFilter === 'recovery' ? isRecovery : !isRecovery;
      });
    }

    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.description?.toLowerCase().includes(q) ||
        (item.tags ?? []).some((tag: string) => tag.toLowerCase().includes(q))
    );
  }, [orgLibraryItems, templates, search, activeTab, showHidden, roleFilter]);

  // Deep-link: when returning from control-record page, reopen the scenario sheet.
  // URL: /dashboard/org-scenarios?scenario_id=...
  const deepLinkScenarioId = (searchParams.get('scenario_id') ?? '').trim();
  useEffect(() => {
    if (!deepLinkScenarioId) {
      openedDeepLinkRef.current = null;
      return;
    }
    if (openedDeepLinkRef.current === deepLinkScenarioId) return;
    const candidates =
      activeTab === 'system'
        ? (templates ?? []).map(templateToLibraryItem)
        : orgLibraryItems;
    const found = candidates.find((s) => s.id === deepLinkScenarioId);
    if (found) {
      openedDeepLinkRef.current = deepLinkScenarioId;
      setSelected(found);
      setDetailOpen(true);
    }
  }, [deepLinkScenarioId, activeTab, orgLibraryItems, templates]);

  const handleDetailOpenChange = useCallback(
    (open: boolean) => {
      setDetailOpen(open);
      if (open) return;
      if (deepLinkScenarioId) {
        openedDeepLinkRef.current = deepLinkScenarioId;
      }
      if (!searchParams.has('scenario_id')) return;
      const params = new URLSearchParams(searchParams.toString());
      params.delete('scenario_id');
      const qs = params.toString();
      router.replace(
        qs ? `${ROUTES.ORG_SCENARIOS.ROOT}?${qs}` : ROUTES.ORG_SCENARIOS.ROOT,
        { scroll: false }
      );
    },
    [deepLinkScenarioId, router, searchParams]
  );

  const openScenario = useCallback((scenario: ScenarioLibraryItem) => {
    setSelected(scenario);
    setDetailOpen(true);
  }, []);

  const handleArchive = useCallback(
    (scenario: ScenarioLibraryItem) => {
      if (isSystemTemplateItem(scenario)) return;
      void (async () => {
        const ok = await confirm({
          title: t('archiveTitle'),
          description: t('archiveConfirm', { name: scenario.name }),
          confirmText: tCommon('confirm'),
          cancelText: tCommon('cancel'),
          confirmVariant: 'destructive',
          zIndex: 10_000
        });
        if (!ok) return;
        archiveMutation.mutate(scenario.id, {
          onSuccess: () => toast.success(t('archiveSuccess')),
          onError: () => toast.error(t('archiveFailed'))
        });
      })();
    },
    [archiveMutation, confirm, t, tCommon]
  );

  const handleRestore = useCallback(
    (scenario: ScenarioLibraryItem) => {
      if (isSystemTemplateItem(scenario)) return;
      void (async () => {
        const ok = await confirm({
          title: t('restoreTitle'),
          description: t('restoreConfirm', { name: scenario.name }),
          confirmText: tCommon('confirm'),
          cancelText: tCommon('cancel'),
          zIndex: 10_000
        });
        if (!ok) return;
        restoreMutation.mutate(scenario.id, {
          onSuccess: () => toast.success(t('restoreSuccess')),
          onError: () => toast.error(t('restoreFailed'))
        });
      })();
    },
    [confirm, restoreMutation, t, tCommon]
  );

  const columns = useMemo(
    () =>
      getOrgScenarioColumns(t, openScenario, handleArchive, handleRestore, {
        showSourceColumn: false
      }),
    [t, openScenario, handleArchive, handleRestore]
  );

  const { table } = useDataTable<ScenarioLibraryItem>({
    data: filtered,
    columns,
    pageCount: 1
  });

  const searchPlaceholder =
    activeTab === 'system'
      ? t('searchTemplatesPlaceholder')
      : t('searchLibraryPlaceholder');

  return (
    <>
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          setActiveTab(value as LibraryTab);
          setSearch('');
          setRoleFilter('all');
        }}
        className='space-y-0'
      >
        <Card className='gap-0 overflow-hidden border-0 bg-transparent py-0 shadow-none'>
          <CardHeader className='space-y-4 px-0 py-0'>
            <div className='flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
              <TabsList className='grid h-10 w-full grid-cols-2 sm:w-auto sm:min-w-[22rem]'>
                <TabsTrigger value='org' className='gap-1.5 text-sm'>
                  {t('tabLibrary')}
                  <span className='rounded-full bg-background/80 px-1.5 py-0.5 text-[11px] font-normal tabular-nums text-muted-foreground'>
                    {counts.org}
                  </span>
                </TabsTrigger>
                <TabsTrigger value='system' className='gap-1.5 text-sm'>
                  {t('tabTemplates')}
                  <span className='rounded-full bg-background/80 px-1.5 py-0.5 text-[11px] font-normal tabular-nums text-muted-foreground'>
                    {counts.system}
                  </span>
                </TabsTrigger>
              </TabsList>

              <div className='flex shrink-0 flex-wrap justify-end gap-2'>
                {activeTab === 'org' ? (
                  <Can object='scenarios' action='create'>
                    <ImportOrgScenarioDialog />
                    <CreateOrgScenarioDialog />
                  </Can>
                ) : isSuperadmin ? (
                  <Can object='scenario-templates' action='create'>
                    <CreateTemplateDialog />
                  </Can>
                ) : null}
              </div>
            </div>

            <div className='flex w-full flex-col gap-3 sm:flex-row sm:items-center'>
              <div className='relative mb-5 w-full min-w-0 flex-1'>
                <Search
                  size={16}
                  className='pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground'
                />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={searchPlaceholder}
                  className='h-10 w-full border-border/80 bg-background pl-9'
                />
              </div>
              {activeTab === 'org' ? (
                <Tabs
                  value={roleFilter}
                  onValueChange={(value) =>
                    setRoleFilter(value as ScenarioRoleFilter)
                  }
                  className='shrink-0'
                >
                  <TabsList className='grid h-10 w-full grid-cols-3 sm:w-auto'>
                    <TabsTrigger value='all' className='text-xs'>
                      {t('roleFilterAll', { count: counts.org })}
                    </TabsTrigger>
                    <TabsTrigger value='regular' className='text-xs'>
                      {t('roleFilterMain', { count: counts.regular })}
                    </TabsTrigger>
                    <TabsTrigger value='recovery' className='text-xs'>
                      {t('roleFilterRecovery', { count: counts.recovery })}
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
              ) : null}
              {activeTab === 'org' && counts.hidden > 0 ? (
                <label
                  className={cn(
                    'flex shrink-0 cursor-pointer items-center gap-2 rounded-md border border-border/80',
                    'bg-background px-3 py-2 text-sm text-muted-foreground transition-colors',
                    'hover:bg-muted/50'
                  )}
                >
                  <Checkbox
                    checked={showHidden}
                    onCheckedChange={(checked) =>
                      setShowHidden(checked === true)
                    }
                  />
                  <span>
                    {t('showHidden')}{' '}
                    <span className='font-medium text-foreground'>
                      ({counts.hidden})
                    </span>
                  </span>
                </label>
              ) : null}
            </div>
          </CardHeader>

          <CardContent className='p-0'>
            {isLoading && (
              <p className='py-8 text-sm text-muted-foreground'>
                {t('loading')}
              </p>
            )}
            {error && (
              <p className='py-8 text-sm text-destructive'>{t('loadError')}</p>
            )}
            {!isLoading && !filtered.length && (
              <div className='py-6'>
                <EmptyState
                  t={t}
                  tab={activeTab}
                  hasSearch={Boolean(search.trim())}
                  showHidden={showHidden}
                  isSuperadmin={isSuperadmin}
                />
              </div>
            )}
            {filtered.length > 0 ? (
              <DataTable
                table={table}
                total={filtered.length}
                className='border-0 shadow-none [&>div>div]:border-0 [&_table]:text-sm'
              />
            ) : null}
          </CardContent>
        </Card>
      </Tabs>

      <ScenarioDetailSheet
        item={selected}
        open={detailOpen}
        onOpenChange={handleDetailOpenChange}
      />
    </>
  );
}

function EmptyState({
  t,
  tab,
  hasSearch,
  showHidden,
  isSuperadmin
}: {
  t: (key: string) => string;
  tab: LibraryTab;
  hasSearch: boolean;
  showHidden: boolean;
  isSuperadmin: boolean;
}) {
  if (hasSearch) {
    return (
      <div className='rounded-xl border border-dashed bg-muted/20 px-6 py-14 text-center text-sm text-muted-foreground'>
        {tab === 'system' ? t('templatesNoResults') : t('libraryNoResults')}
      </div>
    );
  }

  if (tab === 'org' && showHidden) {
    return (
      <div className='rounded-xl border border-dashed bg-muted/20 px-6 py-14 text-center text-sm text-muted-foreground'>
        {t('libraryNoResults')}
      </div>
    );
  }

  if (tab === 'system') {
    return (
      <div className='rounded-xl border border-dashed bg-muted/20 px-6 py-14 text-center'>
        <FileCode className='mx-auto mb-3 size-10 text-muted-foreground/60' />
        <p className='text-sm font-medium text-foreground'>
          {t('templatesEmptyTitle')}
        </p>
        <p className='mt-1 text-sm text-muted-foreground'>
          {t('templatesEmpty')}
        </p>
        {isSuperadmin ? (
          <div className='mt-5 flex justify-center'>
            <Can object='scenario-templates' action='create'>
              <CreateTemplateDialog />
            </Can>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className='rounded-xl border border-dashed bg-muted/20 px-6 py-14 text-center'>
      <FileCode className='mx-auto mb-3 size-10 text-muted-foreground/60' />
      <p className='text-sm font-medium text-foreground'>{t('emptyTitle')}</p>
      <p className='mt-1 text-sm text-muted-foreground'>
        {t('emptyDescription')}
      </p>
      <div className='mt-5 flex flex-wrap justify-center gap-2'>
        <Can object='scenarios' action='create'>
          <ImportOrgScenarioDialog />
          <CreateOrgScenarioDialog />
        </Can>
      </div>
    </div>
  );
}
