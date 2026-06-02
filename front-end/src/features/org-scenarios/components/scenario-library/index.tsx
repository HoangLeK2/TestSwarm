'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { FileCode, Search } from 'lucide-react';
import { toast } from 'sonner';
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
import { CampaignHintBanner } from './campaign-hint-banner';

type LibraryTab = 'org' | 'system';

export function ScenarioLibrary() {
  const t = useTranslations('orgScenariosFeature.list');
  const tCommon = useTranslations('common');
  const { user } = useUser();
  const isSuperadmin = isSuperadminRole(user?.role);
  const confirm = useConfirm();
  const [search, setSearch] = useState('');
  const [showHidden, setShowHidden] = useState(false);
  const [activeTab, setActiveTab] = useState<LibraryTab>('org');
  const [selected, setSelected] = useState<ScenarioLibraryItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const { data: orgScenarios, isLoading: orgLoading, error: orgError } =
    useOrgScenarios({ include_archived: showHidden });
  const {
    data: templates,
    isLoading: templatesLoading,
    error: templatesError
  } = useScenarioTemplatesCatalog();
  const archiveMutation = useArchiveOrgScenario();
  const restoreMutation = useRestoreOrgScenario();

  const isLoading = activeTab === 'org' ? orgLoading : templatesLoading;
  const error = activeTab === 'org' ? orgError : templatesError;

  const counts = useMemo(() => {
    const orgItems = (orgScenarios ?? []).map(orgScenarioToLibraryItem);
    const visibleOrg = orgItems.filter((s) => s.status !== 'archived').length;
    const hiddenOrg = orgItems.filter((s) => s.status === 'archived').length;
    const system = (templates ?? []).length;
    return { org: visibleOrg, hidden: hiddenOrg, system };
  }, [orgScenarios, templates]);

  const filtered = useMemo(() => {
    let items: ScenarioLibraryItem[] =
      activeTab === 'system'
        ? (templates ?? []).map(templateToLibraryItem)
        : (orgScenarios ?? []).map(orgScenarioToLibraryItem);

    if (activeTab === 'org' && !showHidden) {
      items = items.filter((item) => item.status !== 'archived');
    }

    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.description?.toLowerCase().includes(q) ||
        (item.tags ?? []).some((tag: string) => tag.toLowerCase().includes(q))
    );
  }, [orgScenarios, templates, search, activeTab, showHidden]);

  const openScenario = (scenario: ScenarioLibraryItem) => {
    setSelected(scenario);
    setDetailOpen(true);
  };

  const handleArchive = (scenario: ScenarioLibraryItem) => {
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
  };

  const handleRestore = (scenario: ScenarioLibraryItem) => {
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
  };

  const columns = useMemo(
    () =>
      getOrgScenarioColumns(t, openScenario, handleArchive, handleRestore, {
        showSourceColumn: false
      }),
    [t]
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
        }}
        className='space-y-0'
      >
        <Card className='overflow-hidden border-border/80 shadow-sm'>
          <CardHeader className='space-y-4 border-b bg-muted/20 px-4 py-4 sm:px-6'>
            <div className='flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between'>
              <TabsList className='grid h-10 w-full grid-cols-2 lg:w-[360px]'>
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

              <div className='flex flex-wrap gap-2'>
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

          {activeTab === 'org' ? <CampaignHintBanner /> : null}

          <div className='flex flex-col gap-3 sm:flex-row sm:items-center'>
            <div className='relative flex-1 sm:max-w-sm'>
              <Search
                size={16}
                className='pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground'
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={searchPlaceholder}
                className='h-10 border-border/80 bg-background pl-9'
              />
            </div>
            {activeTab === 'org' && counts.hidden > 0 ? (
              <label
                className={cn(
                  'flex cursor-pointer items-center gap-2 rounded-md border border-border/80',
                  'bg-background px-3 py-2 text-sm text-muted-foreground transition-colors',
                  'hover:bg-muted/50'
                )}
              >
                <Checkbox
                  checked={showHidden}
                  onCheckedChange={(checked) => setShowHidden(checked === true)}
                />
                <span>
                  {t('showHidden')}{' '}
                  <span className='font-medium text-foreground'>({counts.hidden})</span>
                </span>
              </label>
            ) : null}
          </div>
        </CardHeader>

          <CardContent className='p-0'>
          {isLoading && (
            <p className='px-6 py-8 text-sm text-muted-foreground'>{t('loading')}</p>
          )}
          {error && (
            <p className='px-6 py-8 text-sm text-destructive'>{t('loadError')}</p>
          )}
          {!isLoading && !filtered.length && (
            <div className='px-4 py-6 sm:px-6'>
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
                className='border-0 shadow-none [&_table]:text-sm'
              />
            ) : null}
          </CardContent>
        </Card>
      </Tabs>

      <ScenarioDetailSheet
        item={selected}
        open={detailOpen}
        onOpenChange={setDetailOpen}
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
        <p className='text-sm font-medium text-foreground'>{t('templatesEmptyTitle')}</p>
        <p className='mt-1 text-sm text-muted-foreground'>{t('templatesEmpty')}</p>
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
      <p className='mt-1 text-sm text-muted-foreground'>{t('emptyDescription')}</p>
      <div className='mt-5 flex flex-wrap justify-center gap-2'>
        <Can object='scenarios' action='create'>
          <ImportOrgScenarioDialog />
          <CreateOrgScenarioDialog />
        </Can>
      </div>
    </div>
  );
}
