'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Database, FileText } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import {
  ADMIN_PAGE_SIZE,
  AdminErrorState,
  AdminPageHeader,
  AdminPagination,
  AdminTableSkeleton,
  AdminWorkspaceScopeSelect,
  SearchField
} from './admin-shared';
import { useAdminWorkspaceScope } from '../hooks/use-admin-workspace-scope';
import { adminApi, formatAdminApiError } from '../services/admin-api';

const ALL = '__all__';

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

function previewText(title?: string | null, body?: string | null) {
  return title?.trim() || body?.trim() || '-';
}

export function AdminContentPage() {
  const t = useTranslations('adminConsole.content');
  const scope = useAdminWorkspaceScope();
  const [search, setSearch] = useState('');
  const [contentType, setContentType] = useState(ALL);
  const [platform, setPlatform] = useState(ALL);
  const [offset, setOffset] = useState(0);

  const params = useMemo(
    () => ({
      search: search || undefined,
      content_type: contentType === ALL ? undefined : contentType,
      platform: platform === ALL ? undefined : platform,
      workspaceId: scope.scopedWorkspaceId,
      offset,
      limit: ADMIN_PAGE_SIZE
    }),
    [contentType, offset, platform, scope.scopedWorkspaceId, search]
  );

  const content = useQuery({
    queryKey: ['admin-content', params],
    queryFn: () => adminApi.listContent(params),
    refetchInterval: 30_000
  });

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader title={t('title')} description={t('description')} />
      <div className='space-y-4 p-4 md:p-6'>
        <div className='grid gap-3 rounded-md border bg-background p-3 lg:grid-cols-[minmax(220px,1fr)_260px_170px_170px]'>
          <SearchField
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            placeholder={t('searchPlaceholder')}
          />
          <AdminWorkspaceScopeSelect
            value={scope.workspaceId}
            onChange={(value) => {
              scope.setWorkspaceId(value);
              setOffset(0);
            }}
            workspaces={scope.workspaces}
            allowGlobalScope={scope.allowGlobalScope}
            workspaceLabel={t('filters.workspace')}
            allWorkspacesLabel={t('filters.allWorkspaces')}
          />
          <Select
            value={contentType}
            onValueChange={(value) => {
              setContentType(value);
              setOffset(0);
            }}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder={t('filters.type')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('filters.allTypes')}</SelectItem>
              <SelectItem value='fb_post'>{t('types.posts')}</SelectItem>
              <SelectItem value='fb_comment'>{t('types.comments')}</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={platform}
            onValueChange={(value) => {
              setPlatform(value);
              setOffset(0);
            }}
          >
            <SelectTrigger className='w-full'>
              <SelectValue placeholder={t('filters.platform')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('filters.allPlatforms')}</SelectItem>
              <SelectItem value='facebook'>Facebook</SelectItem>
              <SelectItem value='tiktok'>TikTok</SelectItem>
              <SelectItem value='instagram'>Instagram</SelectItem>
              <SelectItem value='youtube'>YouTube</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {content.isError ? (
          <AdminErrorState
            message={formatAdminApiError(content.error)}
            onRetry={() => void content.refetch()}
          />
        ) : null}

        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='flex items-center justify-between gap-3 border-b px-3 py-2 text-sm'>
            <div className='flex items-center gap-2 text-muted-foreground'>
              <Database className='size-4' />
              <span>{t('total', { count: content.data?.total ?? 0 })}</span>
            </div>
          </div>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.workspace')}</TableHead>
                  <TableHead>{t('table.content')}</TableHead>
                  <TableHead>{t('table.type')}</TableHead>
                  <TableHead>{t('table.author')}</TableHead>
                  <TableHead>{t('table.device')}</TableHead>
                  <TableHead>{t('table.execution')}</TableHead>
                  <TableHead>{t('table.extracted')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {content.isLoading ? <AdminTableSkeleton columns={7} /> : null}
                {content.data?.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <div className='min-w-[180px]'>
                        <p className='font-medium'>
                          {item.workspaceName || item.workspaceId}
                        </p>
                        <p className='text-xs text-muted-foreground'>
                          {item.workspaceId}
                        </p>
                      </div>
                    </TableCell>
                    {/* TableCell is whitespace-nowrap, so the clamp needs it re-enabled. */}
                    <TableCell className='whitespace-normal'>
                      <div className='w-[420px] max-w-[420px]'>
                        <p className='line-clamp-2 break-words text-sm font-medium'>
                          {previewText(item.title, item.body)}
                        </p>
                        <p className='mt-1 flex items-center gap-1 text-xs text-muted-foreground'>
                          <FileText className='size-3 shrink-0' />
                          <span className='min-w-0 truncate'>
                            {item.collection} · {item.content_hash}
                          </span>
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant='outline'>{item.content_type}</Badge>
                    </TableCell>
                    <TableCell className='text-sm'>
                      {item.author || '-'}
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {item.device_serial || '-'}
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {item.execution_id || item.campaign_id || '-'}
                    </TableCell>
                    <TableCell className='text-sm text-muted-foreground'>
                      {dateLabel(item.extracted_at || item.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
                {!content.isLoading && content.data?.items.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={7}
                      className='h-28 text-center text-sm text-muted-foreground'
                    >
                      {t('empty')}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
          <AdminPagination
            offset={offset}
            limit={ADMIN_PAGE_SIZE}
            total={content.data?.total ?? 0}
            onOffsetChange={setOffset}
          />
        </div>
      </div>
    </div>
  );
}
