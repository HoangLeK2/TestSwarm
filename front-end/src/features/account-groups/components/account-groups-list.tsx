'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { Pencil, Search, Trash2, Users, Users2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  useAccountGroups,
  useDeleteAccountGroup
} from '../hooks/use-account-groups';
import type { AccountGroupOut } from '../services/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { CreateGroupDialog } from './create-group-dialog';
import { EditGroupDialog } from './edit-group-dialog';
import { GroupMembersDialog } from './group-members-dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

export function AccountGroupsList() {
  const t = useTranslations('accountGroupsFeature');
  const [platform, setPlatform] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [editTarget, setEditTarget] = useState<AccountGroupOut | null>(null);
  const [manageTarget, setManageTarget] = useState<AccountGroupOut | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AccountGroupOut | null>(null);

  const { data: groups, isLoading, error } = useAccountGroups();
  const deleteMutation = useDeleteAccountGroup();

  const platforms = useMemo(() => {
    const set = new Set<string>();
    (groups ?? []).forEach((g) => {
      if (g.platform) set.add(g.platform);
    });
    return Array.from(set).sort();
  }, [groups]);

  const filtered = useMemo(() => {
    let list = groups ?? [];
    if (platform !== 'all') {
      list = list.filter((g) => g.platform === platform);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((g) => g.name.toLowerCase().includes(q));
    }
    return list;
  }, [groups, platform, search]);

  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    deleteMutation.mutate(target.id, {
      onSuccess: () => {
        toast.success(t('deleteSuccess'));
        setDeleteTarget(null);
      },
      onError: (err) => {
        toast.error(formatFarmApiError(err, t('deleteConfirmTitle')));
      }
    });
  };

  return (
    <div className='space-y-6'>
      {isLoading ? (
        <p className='text-sm text-muted-foreground'>{t('pageTitle')}...</p>
      ) : error ? (
        <p className='text-sm text-destructive'>
          {formatFarmApiError(error, t('pageTitle'))}
        </p>
      ) : (
        <>
          <div className='flex flex-wrap items-center gap-3'>
            <div className='relative min-w-[220px] flex-1 sm:max-w-sm'>
              <Search
                size={14}
                className='absolute left-2.5 top-2.5 text-muted-foreground'
              />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('searchPlaceholder')}
                className='h-8 pl-8'
              />
            </div>
            <Select value={platform} onValueChange={setPlatform}>
              <SelectTrigger className='h-8 w-[180px]'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='all'>{t('allPlatforms')}</SelectItem>
                {platforms.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className='ml-auto'>
              <CreateGroupDialog />
            </div>
          </div>

          {!filtered.length ? (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-16 text-center'>
              <Users2 className='mx-auto mb-4 size-12 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>
                {t('emptyTitle')}
              </p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('emptyDescription')}
              </p>
              <div className='mt-6'>
                <CreateGroupDialog />
              </div>
            </div>
          ) : (
            <div className='rounded-xl border border-border bg-card'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('columnName')}</TableHead>
                    <TableHead>{t('columnPlatform')}</TableHead>
                    <TableHead className='text-center'>
                      {t('columnMembers')}
                    </TableHead>
                    <TableHead>{t('columnStrategy')}</TableHead>
                    <TableHead>{t('columnUpdated')}</TableHead>
                    <TableHead className='text-right'>
                      {t('columnActions')}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((g) => (
                    <TableRow key={g.id}>
                      <TableCell className='max-w-[260px]'>
                        <div className='min-w-0'>
                          <p className='truncate text-sm font-semibold'>
                            {g.name}
                          </p>
                          {g.description && (
                            <p className='truncate text-[11px] text-muted-foreground'>
                              {g.description}
                            </p>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant='secondary' className='text-[11px]'>
                          {g.platform}
                        </Badge>
                      </TableCell>
                      <TableCell className='text-center'>
                        <Badge variant='outline'>{g.member_count}</Badge>
                      </TableCell>
                      <TableCell>
                        <span className='text-xs text-muted-foreground'>
                          {g.rotation_strategy === 'round_robin'
                            ? t('rotationRoundRobin')
                            : t('rotationLeastRecent')}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className='whitespace-nowrap text-[11px] text-muted-foreground'>
                          {formatDistanceToNow(new Date(g.updated_at), {
                            addSuffix: true,
                            locale: vi
                          })}
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className='flex items-center justify-end gap-1'>
                          <Button
                            size='sm'
                            variant='outline'
                            className='h-7 px-2 text-xs'
                            onClick={() => setManageTarget(g)}
                          >
                            <Users size={13} className='mr-1' />
                            {t('manageMembers')}
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='size-7'
                            title={t('edit')}
                            onClick={() => setEditTarget(g)}
                          >
                            <Pencil size={13} />
                          </Button>
                          <Button
                            size='icon'
                            variant='ghost'
                            className='size-7 text-destructive hover:text-destructive'
                            title={t('delete')}
                            onClick={() => setDeleteTarget(g)}
                          >
                            <Trash2 size={13} />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      )}

      {editTarget && (
        <EditGroupDialog
          group={editTarget}
          open={!!editTarget}
          onOpenChange={(o) => !o && setEditTarget(null)}
        />
      )}
      {manageTarget && (
        <GroupMembersDialog
          group={manageTarget}
          open={!!manageTarget}
          onOpenChange={(o) => !o && setManageTarget(null)}
        />
      )}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
      >
        <AlertDialogContent className='z-[1100]'>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('deleteConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('deleteConfirmDesc', { name: deleteTarget?.name ?? '' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>
              {t('deleteConfirmCancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              disabled={deleteMutation.isPending}
              className='bg-destructive text-white hover:bg-destructive/90'
            >
              {t('deleteConfirmOk')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
