'use client';

import { type ReactNode, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Building2,
  Server,
  ShieldCheck,
  SquareArrowOutUpRight,
  type LucideIcon
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { useQuery } from '@tanstack/react-query';
import { ROUTES } from '@/config/routes';
import { Link } from '@/i18n/navigation';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { formatDate, getLocaleByNextLocale } from '@/lib/format';
import {
  AdminErrorState,
  AdminPageHeader,
  AdminPagination,
  AdminTableSkeleton,
  AdminWorkspaceScopeSelect,
  StatusBadge
} from './admin-shared';
import { adminApi, formatAdminApiError } from '../services/admin-api';
import { useAdminWorkspaceScope } from '../hooks/use-admin-workspace-scope';

const DASHBOARD_WORKSPACE_PAGE_SIZE = 12;

function Metric({
  label,
  value,
  detail
}: {
  label: string;
  value: ReactNode;
  detail?: string;
}) {
  return (
    <div className='rounded-md border bg-background p-4'>
      <p className='text-xs font-medium uppercase text-muted-foreground'>
        {label}
      </p>
      <p className='mt-2 text-2xl font-semibold'>{value}</p>
      {detail ? (
        <p className='mt-1 text-xs text-muted-foreground'>{detail}</p>
      ) : null}
    </div>
  );
}

function AttentionItem({
  icon: Icon,
  label,
  value,
  detail,
  href,
  action
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  detail: string;
  href: string;
  action: string;
}) {
  const hasIssue = value > 0;
  return (
    <div className='grid grid-cols-[1fr_auto_auto] items-center gap-3 px-4 py-3 text-sm'>
      <div className='flex min-w-0 items-center gap-2'>
        <Icon className='size-4 shrink-0 text-muted-foreground' />
        <span className='min-w-0'>
          <span className='block truncate font-medium'>{label}</span>
          <span className='block truncate text-xs text-muted-foreground'>
            {detail}
          </span>
        </span>
      </div>
      <span
        className={`text-right font-semibold tabular-nums ${
          hasIssue ? 'text-foreground' : 'text-muted-foreground'
        }`}
      >
        {value}
      </span>
      <Button asChild variant='ghost' size='sm' className='h-8 px-2'>
        <Link href={href}>{action}</Link>
      </Button>
    </div>
  );
}

export function AdminDashboardPage() {
  const t = useTranslations('adminConsole.dashboard');
  const locale = getLocaleByNextLocale(useLocale());
  const scope = useAdminWorkspaceScope();
  const [workspaceOffset, setWorkspaceOffset] = useState(0);
  const workspaceParams = useMemo(
    () => ({
      workspaceId: scope.scopedWorkspaceId,
      offset: workspaceOffset,
      limit: DASHBOARD_WORKSPACE_PAGE_SIZE
    }),
    [scope.scopedWorkspaceId, workspaceOffset]
  );
  const summary = useQuery({
    queryKey: ['admin-summary', scope.scopedWorkspaceId],
    queryFn: () => adminApi.summary({ workspaceId: scope.scopedWorkspaceId }),
    refetchInterval: 30_000,
    placeholderData: (previous) => previous
  });
  const offlineAgents = summary.data?.offlineAgents ?? 0;
  const staleAgents = summary.data?.staleAgents ?? 0;
  const attentionTotal = offlineAgents + staleAgents;
  const workspaces = useQuery({
    queryKey: ['admin-dashboard-workspaces', workspaceParams],
    queryFn: () => adminApi.listWorkspaces(workspaceParams),
    refetchInterval: 30_000,
    placeholderData: (previous) => previous
  });
  const isInitialSummaryLoading = summary.isLoading && !summary.data;
  const isInitialWorkspacesLoading = workspaces.isLoading && !workspaces.data;
  const metricValue = (value?: number | null) =>
    isInitialSummaryLoading
      ? t('metrics.loading')
      : (value ?? t('metrics.unavailable'));
  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader
        title={t('title')}
        description={t('description')}
        action={
          <AdminWorkspaceScopeSelect
            value={scope.workspaceId}
            onChange={(value) => {
              scope.setWorkspaceId(value);
              setWorkspaceOffset(0);
            }}
            workspaces={scope.workspaces}
            allowGlobalScope={scope.allowGlobalScope}
            workspaceLabel={t('scope.workspace')}
            allWorkspacesLabel={t('scope.allWorkspaces')}
          />
        }
      />
      <div className='space-y-5 p-4 md:p-6'>
        {summary.isError || workspaces.isError ? (
          <AdminErrorState
            message={formatAdminApiError(summary.error ?? workspaces.error)}
            onRetry={() => {
              void summary.refetch();
              void workspaces.refetch();
            }}
          />
        ) : null}

        <div className='grid gap-3 md:grid-cols-3 xl:grid-cols-4'>
          <Metric
            label={t('metrics.workspaces')}
            value={metricValue(summary.data?.totalWorkspaces)}
            detail={t('metrics.activeDetail', {
              count: summary.data?.activeWorkspaces ?? 0
            })}
          />
          <Metric
            label={t('metrics.suspended')}
            value={metricValue(summary.data?.suspendedWorkspaces)}
            detail={t('metrics.archivedDetail', {
              count: summary.data?.archivedWorkspaces ?? 0
            })}
          />
          <Metric
            label={t('metrics.agents')}
            value={metricValue(summary.data?.totalAgents)}
            detail={t('metrics.onlineDetail', {
              count: summary.data?.onlineAgents ?? 0
            })}
          />
          <Metric
            label={t('metrics.devices')}
            value={metricValue(summary.data?.totalDevices)}
            detail={t('metrics.unassignedDetail', {
              count: summary.data?.unassignedDevices ?? 0
            })}
          />
        </div>

        <section className='rounded-md border bg-background'>
          <div className='flex flex-col gap-1 border-b px-4 py-3 md:flex-row md:items-center md:justify-between'>
            <div className='flex min-w-0 items-center gap-2'>
              <Activity className='size-4 shrink-0 text-muted-foreground' />
              <h2 className='text-sm font-semibold'>{t('attention.title')}</h2>
            </div>
            <p className='text-xs text-muted-foreground'>
              {attentionTotal > 0
                ? t('attention.summary', { count: attentionTotal })
                : t('attention.clear')}
            </p>
          </div>
          <div className='divide-y'>
            <AttentionItem
              icon={Server}
              label={t('attention.offlineAgents')}
              value={offlineAgents}
              detail={t('attention.offlineAgentsDetail')}
              href={ROUTES.ADMIN.AGENTS}
              action={t('attention.viewAgents')}
            />
            <AttentionItem
              icon={AlertTriangle}
              label={t('attention.staleAgents')}
              value={staleAgents}
              detail={t('attention.staleAgentsDetail')}
              href={ROUTES.ADMIN.AGENTS}
              action={t('attention.viewAgents')}
            />
          </div>
        </section>

        <section className='rounded-md border bg-background'>
          <div className='flex flex-col gap-3 border-b px-4 py-3 lg:flex-row lg:items-center lg:justify-between'>
            <div className='flex min-w-0 items-center gap-2'>
              <Building2 className='size-4 shrink-0 text-muted-foreground' />
              <div className='min-w-0'>
                <h2 className='text-sm font-semibold'>
                  {t('workspaceOverview.title')}
                </h2>
                <p className='truncate text-xs text-muted-foreground'>
                  {isInitialWorkspacesLoading
                    ? t('workspaceOverview.loadingDescription')
                    : t('workspaceOverview.description', {
                        count: workspaces.data?.total ?? 0
                      })}
                </p>
              </div>
            </div>
            <div className='flex flex-wrap gap-2'>
              {scope.isSuperadmin ? (
                <Button asChild variant='outline' size='sm'>
                  <Link href={ROUTES.ADMIN.WORKSPACE_ADMINS}>
                    <ShieldCheck className='mr-2 size-4' />
                    {t('workspaceOverview.provisionAccounts')}
                  </Link>
                </Button>
              ) : null}
              <Button asChild size='sm'>
                <Link href={ROUTES.ADMIN.WORKSPACES}>
                  <SquareArrowOutUpRight className='mr-2 size-4' />
                  {t('workspaceOverview.manageAll')}
                </Link>
              </Button>
            </div>
          </div>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className='min-w-[260px]'>
                    {t('workspaceOverview.table.workspace')}
                  </TableHead>
                  <TableHead className='min-w-[160px]'>
                    {t('workspaceOverview.table.owner')}
                  </TableHead>
                  <TableHead>{t('workspaceOverview.table.status')}</TableHead>
                  <TableHead className='text-right'>
                    {t('workspaceOverview.table.members')}
                  </TableHead>
                  <TableHead className='text-right'>
                    {t('workspaceOverview.table.admins')}
                  </TableHead>
                  <TableHead className='text-right'>
                    {t('workspaceOverview.table.agents')}
                  </TableHead>
                  <TableHead className='text-right'>
                    {t('workspaceOverview.table.devices')}
                  </TableHead>
                  <TableHead className='min-w-[130px]'>
                    {t('workspaceOverview.table.updated')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isInitialWorkspacesLoading ? (
                  <AdminTableSkeleton columns={8} />
                ) : workspaces.data?.items.length ? (
                  workspaces.data.items.map((workspace) => (
                    <TableRow key={workspace.id}>
                      <TableCell>
                        <div className='min-w-0'>
                          <p className='truncate font-medium'>
                            {workspace.businessName}
                          </p>
                          <p className='truncate text-xs text-muted-foreground'>
                            {workspace.description ||
                              t('workspaceOverview.noDescription')}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='min-w-0'>
                          <p className='truncate text-sm'>
                            {workspace.owner
                              ? t('workspaceOverview.ownerAssigned')
                              : t('workspaceOverview.unassignedOwner')}
                          </p>
                          <p className='truncate text-xs text-muted-foreground'>
                            {workspace.owner
                              ? t('workspaceOverview.ownerManagedInDetails')
                              : t('workspaceOverview.noOwnerEmail')}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell>
                        <StatusBadge value={workspace.status} />
                      </TableCell>
                      <TableCell className='text-right font-medium'>
                        {workspace.memberCount}
                      </TableCell>
                      <TableCell className='text-right font-medium'>
                        {workspace.adminCount}
                      </TableCell>
                      <TableCell className='text-right font-medium'>
                        {workspace.agentCount}
                      </TableCell>
                      <TableCell className='text-right font-medium'>
                        {workspace.deviceCount}
                      </TableCell>
                      <TableCell className='text-sm text-muted-foreground'>
                        {formatDate(
                          workspace.updated_at || workspace.created_at,
                          {
                            month: 'short',
                            day: 'numeric',
                            year: 'numeric'
                          },
                          locale
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={8} className='h-32 text-center'>
                      <div className='mx-auto flex max-w-sm flex-col items-center gap-2 py-5'>
                        <p className='text-sm font-medium text-foreground'>
                          {t('workspaceOverview.emptyTitle')}
                        </p>
                        <p className='text-sm text-muted-foreground'>
                          {t('workspaceOverview.emptyDescription')}
                        </p>
                        <Button asChild size='sm' variant='outline'>
                          <Link href={ROUTES.ADMIN.WORKSPACES}>
                            {t('workspaceOverview.manageAll')}
                          </Link>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <AdminPagination
            offset={workspaceOffset}
            limit={DASHBOARD_WORKSPACE_PAGE_SIZE}
            total={workspaces.data?.total ?? 0}
            onOffsetChange={setWorkspaceOffset}
          />
        </section>

        <div className='grid gap-4 xl:grid-cols-2'>
          <section className='rounded-md border bg-background'>
            <div className='flex items-center gap-2 border-b px-4 py-3'>
              <Building2 className='size-4 text-muted-foreground' />
              <h2 className='text-sm font-semibold'>
                {t('devicesByWorkspace')}
              </h2>
            </div>
            <div className='divide-y'>
              {(summary.data?.devicesByWorkspace ?? []).map((item) => (
                <div
                  key={item.workspaceId}
                  className='flex items-center justify-between gap-3 px-4 py-3 text-sm'
                >
                  <span className='min-w-0 truncate'>{item.workspaceName}</span>
                  <span className='font-medium'>{item.count}</span>
                </div>
              ))}
              {!summary.isLoading &&
              (summary.data?.devicesByWorkspace ?? []).length === 0 ? (
                <p className='px-4 py-8 text-center text-sm text-muted-foreground'>
                  {t('emptyWorkspaceData')}
                </p>
              ) : null}
            </div>
          </section>

          <section className='rounded-md border bg-background'>
            <div className='flex items-center gap-2 border-b px-4 py-3'>
              <Server className='size-4 text-muted-foreground' />
              <h2 className='text-sm font-semibold'>
                {t('agentsByWorkspace')}
              </h2>
            </div>
            <div className='divide-y'>
              {(summary.data?.agentsByWorkspace ?? []).map((item) => (
                <div
                  key={item.workspaceId}
                  className='flex items-center justify-between gap-3 px-4 py-3 text-sm'
                >
                  <span className='min-w-0 truncate'>{item.workspaceName}</span>
                  <span className='font-medium'>{item.count}</span>
                </div>
              ))}
              {!summary.isLoading &&
              (summary.data?.agentsByWorkspace ?? []).length === 0 ? (
                <p className='px-4 py-8 text-center text-sm text-muted-foreground'>
                  {t('emptyAgentData')}
                </p>
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
