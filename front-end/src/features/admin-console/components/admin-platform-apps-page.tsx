'use client';

import { type FormEvent, useMemo, useState } from 'react';
import { Copy, PackagePlus, Trash2, Upload } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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
  StatusBadge,
  SubmitSpinner
} from './admin-shared';
import {
  adminApi,
  formatAdminApiError,
  type PlatformAppReleaseOut
} from '../services/admin-api';

const ALL = '__all__';

function dateLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '-';
}

function bytesLabel(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '-';
  const mb = value / 1024 / 1024;
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

export function AdminPlatformAppsPage() {
  const t = useTranslations('adminConsole.platformApps');
  const tAdmin = useTranslations('adminConsole');
  const qc = useQueryClient();
  const [status, setStatus] = useState(ALL);
  const [offset, setOffset] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [notes, setNotes] = useState('');
  const [deleteRelease, setDeleteRelease] =
    useState<PlatformAppReleaseOut | null>(null);

  const params = useMemo(
    () => ({
      status: status === ALL ? undefined : status,
      offset,
      limit: ADMIN_PAGE_SIZE
    }),
    [offset, status]
  );

  const releases = useQuery({
    queryKey: ['admin-platform-apps-facebook', params],
    queryFn: () => adminApi.listFacebookAppReleases(params)
  });

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error(t('errors.fileRequired'));
      return adminApi.uploadFacebookAppRelease(file, notes);
    },
    onSuccess: () => {
      setFile(null);
      setNotes('');
      toast.success(t('toast.uploaded'));
      void qc.invalidateQueries({ queryKey: ['admin-platform-apps-facebook'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const publishMutation = useMutation({
    mutationFn: (release: PlatformAppReleaseOut) =>
      adminApi.publishFacebookAppRelease(release.id),
    onSuccess: () => {
      toast.success(t('toast.published'));
      void qc.invalidateQueries({ queryKey: ['admin-platform-apps-facebook'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const archiveMutation = useMutation({
    mutationFn: (release: PlatformAppReleaseOut) =>
      adminApi.archiveFacebookAppRelease(release.id),
    onSuccess: () => {
      toast.success(t('toast.archived'));
      void qc.invalidateQueries({ queryKey: ['admin-platform-apps-facebook'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const deleteMutation = useMutation({
    mutationFn: (release: PlatformAppReleaseOut) =>
      adminApi.deleteFacebookAppRelease(release.id),
    onSuccess: () => {
      setDeleteRelease(null);
      toast.success(t('toast.deleted'));
      void qc.invalidateQueries({ queryKey: ['admin-platform-apps-facebook'] });
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  const copyDownloadUrlMutation = useMutation({
    mutationFn: (release: PlatformAppReleaseOut) =>
      adminApi.getFacebookAppReleaseDownloadUrl(release.id),
    onSuccess: async (data) => {
      await navigator.clipboard.writeText(data.download_url);
      toast.success(t('toast.copied'));
    },
    onError: (error) => toast.error(formatAdminApiError(error))
  });

  function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    uploadMutation.mutate();
  }

  return (
    <div className='min-h-full bg-muted/20'>
      <AdminPageHeader title={t('title')} description={t('description')} />
      <div className='space-y-4 p-4 md:p-6'>
        <form
          className='grid gap-3 rounded-md border bg-background p-3 lg:grid-cols-[minmax(260px,1fr)_minmax(220px,1fr)_auto]'
          onSubmit={onUpload}
        >
          <div className='space-y-2'>
            <Label htmlFor='facebook-apk'>{t('upload.file')}</Label>
            <Input
              id='facebook-apk'
              type='file'
              accept='.apk,application/vnd.android.package-archive'
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <div className='space-y-2'>
            <Label htmlFor='facebook-apk-notes'>{t('upload.notes')}</Label>
            <Input
              id='facebook-apk-notes'
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder={t('upload.notesPlaceholder')}
            />
          </div>
          <div className='flex items-end'>
            <Button
              type='submit'
              className='w-full lg:w-auto'
              disabled={!file || uploadMutation.isPending}
            >
              {uploadMutation.isPending ? (
                <SubmitSpinner />
              ) : (
                <Upload className='mr-2 size-4' />
              )}
              {t('upload.submit')}
            </Button>
          </div>
        </form>

        <div className='flex justify-end'>
          <Select
            value={status}
            onValueChange={(value) => {
              setStatus(value);
              setOffset(0);
            }}
          >
            <SelectTrigger className='w-full md:w-[220px]'>
              <SelectValue placeholder={t('filters.status')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t('filters.allStatuses')}</SelectItem>
              <SelectItem value='draft'>{t('statuses.draft')}</SelectItem>
              <SelectItem value='active'>{t('statuses.active')}</SelectItem>
              <SelectItem value='archived'>{t('statuses.archived')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {releases.isError ? (
          <AdminErrorState
            message={formatAdminApiError(releases.error)}
            onRetry={() => void releases.refetch()}
          />
        ) : null}

        <div className='overflow-hidden rounded-md border bg-background'>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('table.release')}</TableHead>
                  <TableHead>{t('table.status')}</TableHead>
                  <TableHead>{t('table.size')}</TableHead>
                  <TableHead>{t('table.sha')}</TableHead>
                  <TableHead>{t('table.published')}</TableHead>
                  <TableHead className='text-right'>
                    {t('table.actions')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {releases.isLoading ? <AdminTableSkeleton columns={6} /> : null}
                {releases.data?.items.map((release) => (
                  <TableRow key={release.id}>
                    <TableCell>
                      <div className='min-w-[220px]'>
                        <p className='font-medium'>{release.version_name}</p>
                        <p className='text-xs text-muted-foreground'>
                          {release.package_name}
                          {release.version_code
                            ? ` · ${release.version_code}`
                            : ''}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge value={release.status} />
                    </TableCell>
                    <TableCell>{bytesLabel(release.size_bytes)}</TableCell>
                    <TableCell>
                      <code className='text-xs'>
                        {release.sha256.slice(0, 12)}
                      </code>
                    </TableCell>
                    <TableCell>{dateLabel(release.published_at)}</TableCell>
                    <TableCell>
                      <div className='flex justify-end gap-2'>
                        <Button
                          type='button'
                          variant='outline'
                          size='sm'
                          onClick={() =>
                            copyDownloadUrlMutation.mutate(release)
                          }
                          disabled={copyDownloadUrlMutation.isPending}
                        >
                          <Copy className='mr-1.5 size-3.5' />
                          {t('actions.copyUrl')}
                        </Button>
                        {release.status !== 'active' ? (
                          <Button
                            type='button'
                            size='sm'
                            onClick={() => publishMutation.mutate(release)}
                            disabled={publishMutation.isPending}
                          >
                            <PackagePlus className='mr-1.5 size-3.5' />
                            {t('actions.publish')}
                          </Button>
                        ) : null}
                        {release.status !== 'archived' ? (
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            onClick={() => archiveMutation.mutate(release)}
                            disabled={archiveMutation.isPending}
                          >
                            {t('actions.archive')}
                          </Button>
                        ) : null}
                        <Button
                          type='button'
                          variant='destructive-outline'
                          size='sm'
                          onClick={() => setDeleteRelease(release)}
                          disabled={deleteMutation.isPending}
                        >
                          <Trash2 className='mr-1.5 size-3.5' />
                          {t('actions.delete')}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {!releases.isLoading && releases.data?.items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className='h-24 text-center'>
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
            total={releases.data?.total ?? 0}
            onOffsetChange={setOffset}
          />
        </div>
      </div>
      <AlertDialog
        open={!!deleteRelease}
        onOpenChange={(open) => !open && setDeleteRelease(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('delete.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('delete.description', {
                version: deleteRelease?.version_name ?? '-'
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>
              {tAdmin('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              className='bg-destructive text-destructive-foreground hover:bg-destructive/90'
              disabled={deleteMutation.isPending}
              onClick={() =>
                deleteRelease && deleteMutation.mutate(deleteRelease)
              }
            >
              {t('delete.confirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
