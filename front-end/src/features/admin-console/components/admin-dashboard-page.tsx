'use client';

import { useMemo } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowRightLeft,
  Building2,
  LogIn,
  Server,
  ShieldCheck,
  SquareArrowOutUpRight,
  Smartphone
} from 'lucide-react';
import { useLocale, useTranslations } from 'next-intl';
import { useQuery } from '@tanstack/react-query';
import { ROUTES } from '@/config/routes';
import { Link, useRouter } from '@/i18n/navigation';
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
import type { ProtoOrganization } from '@/features/device-farm';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import {
  AdminErrorState,
  AdminPageHeader,
  AdminWorkspaceScopeSelect,
  StatusBadge
} from './admin-shared';
import {
  adminApi,
  type AdminWorkspaceOut,
  formatAdminApiError
} from '../services/admin-api';
import { useAdminWorkspaceScope } from '../hooks/use-admin-workspace-scope';

function Metric({
  label,
  value,
  detail
}: {
  label: string;
  value: number;
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

function workspaceToOrganization(
  workspace: AdminWorkspaceOut
): ProtoOrganization {
  return {
    id: workspace.id,
    businessName: workspace.businessName,
    businessEmail: workspace.businessEmail ?? null,
    businessLogo: workspace.businessLogo ?? null,
    slug: workspace.slug,
    status: workspace.status,
    plan: workspace.plan,
    created_at: workspace.created_at
  };
}

export function AdminDashboardPage() {
  const t = useTranslations('adminConsole.dashboard');
  const locale = getLocaleByNextLocale(useLocale());
  const scope = useAdminWorkspaceScope();
  const router = useRouter();
  const { setCurrentOrg } = useOrganization();
  const workspaceParams = useMemo(
    () => ({
      workspaceId: scope.scopedWorkspaceId,
      offset: 0,
      limit: 12
    }),
    [scope.scopedWorkspaceId]
  );
  const summary = useQuery({
    queryKey: ['admin-summary', scope.scopedWorkspaceId],
    queryFn: () => adminApi.summary({ workspaceId: scope.scopedWorkspaceId }),
    refetchInterval: 30_000
  });
  const workspaces = useQuery({
    queryKey: ['admin-dashboard-workspaces', workspaceParams],
    queryFn: () => adminApi.listWorkspaces(workspaceParams),
    refetchInterval: 30_000
  });
  const enterWorkspace = (workspace: AdminWorkspaceOut) => {
    setCurrentOrg(workspaceToOrganization(workspace));
    router.push(ROUTES.DEVICES.ROOT);
  };

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader
        title={t('title')}
        description={t('description')}
        action={
          <AdminWorkspaceScopeSelect
            value={scope.workspaceId}
            onChange={scope.setWorkspaceId}
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
            value={summary.data?.totalWorkspaces ?? 0}
            detail={t('metrics.activeDetail', {
              count: summary.data?.activeWorkspaces ?? 0
            })}
          />
          <Metric
            label={t('metrics.suspended')}
            value={summary.data?.suspendedWorkspaces ?? 0}
            detail={t('metrics.archivedDetail', {
              count: summary.data?.archivedWorkspaces ?? 0
            })}
          />
          <Metric
            label={t('metrics.agents')}
            value={summary.data?.totalAgents ?? 0}
            detail={t('metrics.onlineDetail', {
              count: summary.data?.onlineAgents ?? 0
            })}
          />
          <Metric
            label={t('metrics.devices')}
            value={summary.data?.totalDevices ?? 0}
            detail={t('metrics.unassignedDetail', {
              count: summary.data?.unassignedDevices ?? 0
            })}
          />
        </div>

        <section className='rounded-md border bg-background'>
          <div className='flex flex-col gap-3 border-b px-4 py-3 lg:flex-row lg:items-center lg:justify-between'>
            <div className='flex min-w-0 items-center gap-2'>
              <Building2 className='size-4 shrink-0 text-muted-foreground' />
              <div className='min-w-0'>
                <h2 className='text-sm font-semibold'>
                  {t('workspaceOverview.title')}
                </h2>
                <p className='truncate text-xs text-muted-foreground'>
                  {t('workspaceOverview.description', {
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
              <Button asChild variant='outline' size='sm'>
                <Link href={ROUTES.ADMIN.AGENTS}>
                  <ArrowRightLeft className='mr-2 size-4' />
                  {t('workspaceOverview.allocatePhones')}
                </Link>
              </Button>
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
                  <TableHead className='text-right'>
                    {t('workspaceOverview.table.action')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {workspaces.isLoading ? (
                  Array.from({ length: 5 }).map((_, index) => (
                    <TableRow key={index}>
                      <TableCell colSpan={9}>
                        <div className='h-6 animate-pulse rounded bg-muted' />
                      </TableCell>
                    </TableRow>
                  ))
                ) : workspaces.data?.items.length ? (
                  workspaces.data.items.map((workspace) => (
                    <TableRow key={workspace.id}>
                      <TableCell>
                        <div className='min-w-0'>
                          <p className='truncate font-medium'>
                            {workspace.businessName}
                          </p>
                          <p className='truncate text-xs text-muted-foreground'>
                            {workspace.businessEmail || workspace.description}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className='min-w-0'>
                          <p className='truncate text-sm'>
                            {workspace.owner?.name ||
                              t('workspaceOverview.unassignedOwner')}
                          </p>
                          <p className='truncate text-xs text-muted-foreground'>
                            {workspace.owner?.email || workspace.slug || '-'}
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
                      <TableCell className='text-right'>
                        <Button
                          variant='ghost'
                          size='sm'
                          onClick={() => enterWorkspace(workspace)}
                        >
                          <LogIn className='mr-2 size-4' />
                          {t('workspaceOverview.enterWorkspace')}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={9}
                      className='h-24 text-center text-sm text-muted-foreground'
                    >
                      {t('workspaceOverview.empty')}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
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

        <section className='rounded-md border bg-background'>
          <div className='flex items-center gap-2 border-b px-4 py-3'>
            <Activity className='size-4 text-muted-foreground' />
            <h2 className='text-sm font-semibold'>{t('healthWarnings')}</h2>
          </div>
          <div className='grid gap-3 p-4 md:grid-cols-3'>
            <div className='flex items-center justify-between rounded-md border p-3 text-sm'>
              <span className='flex items-center gap-2'>
                <Server className='size-4 text-muted-foreground' />
                {t('offlineAgents')}
              </span>
              <StatusBadge
                value={
                  (summary.data?.offlineAgents ?? 0) > 0 ? 'offline' : 'online'
                }
              />
            </div>
            <div className='flex items-center justify-between rounded-md border p-3 text-sm'>
              <span className='flex items-center gap-2'>
                <AlertTriangle className='size-4 text-muted-foreground' />
                {t('staleAgents')}
              </span>
              <span className='font-medium'>
                {summary.data?.staleAgents ?? 0}
              </span>
            </div>
            <div className='flex items-center justify-between rounded-md border p-3 text-sm'>
              <span className='flex items-center gap-2'>
                <Smartphone className='size-4 text-muted-foreground' />
                {t('unassignedDevices')}
              </span>
              <span className='font-medium'>
                {summary.data?.unassignedDevices ?? 0}
              </span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
