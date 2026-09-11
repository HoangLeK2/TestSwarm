'use client';

import { formatDistanceToNow } from 'date-fns';
import type { Locale } from 'date-fns';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
  History,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Trash2
} from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { detectAccountEnvironment } from '../../lib/account-environment';
import {
  allowedTransitionTargets,
  isResting,
  normalizeAccountState,
  type AccountStateKey
} from '../../lib/account-fsm';
import type { ColumnDef } from '@tanstack/react-table';
import type { AccountOut } from '../../services/api';
import { EditAccountDialog } from '../edit-account-dialog';
import { AccountStateTransitionDialog } from '../account-state-transition-dialog';
import { AccountDevicesDialog } from '../account-devices-dialog';
import { AccountLoginDialog } from '../account-login-dialog';
import Link from 'next/link';
import { ROUTES } from '@/config/routes';
import type { ResourcePermissionFlags } from '@/features/auth/types/resource-permissions';

type TFn = (key: string, values?: Record<string, any>) => string;

const STATUS_VARIANT: Record<
  string,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  unassigned: 'secondary',
  active: 'default',
  suspended: 'outline',
  banned: 'destructive',
  retired: 'outline'
};

export type { AccountStateKey };

export function getAccountColumns(
  t: TFn,
  statusLabel: Record<AccountStateKey, string>,
  dateLocale: Locale,
  perms: ResourcePermissionFlags,
  onDelete: (account: AccountOut) => void
): ColumnDef<AccountOut>[] {
  return [
    {
      id: 'platform',
      accessorKey: 'platform',
      header: t('colPlatform'),
      cell: ({ row }) => (
        <Badge variant='outline' className='text-[11px]'>
          {row.original.platform}
        </Badge>
      )
    },
    {
      id: 'username',
      accessorKey: 'username',
      header: t('colUsername'),
      cell: ({ row }) => {
        const account = row.original;
        const envFlag = detectAccountEnvironment(account);
        return (
          <div className='flex min-w-0 flex-wrap items-center gap-1.5'>
            <span className='truncate text-sm font-semibold'>
              {account.username}
            </span>
            {envFlag === 'test' ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge
                    variant='outline'
                    className='border-amber-500/50 text-[10px] text-amber-700 dark:text-amber-300'
                  >
                    {t('badgeTest')}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>{t('testAccountHint')}</TooltipContent>
              </Tooltip>
            ) : null}
            {envFlag === 'dev' ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge
                    variant='outline'
                    className='border-orange-500/50 text-[10px] text-orange-700 dark:text-orange-300'
                  >
                    {t('badgeDev')}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>{t('testAccountHint')}</TooltipContent>
              </Tooltip>
            ) : null}
          </div>
        );
      }
    },
    {
      id: 'displayName',
      accessorKey: 'display_name',
      header: t('colDisplayName'),
      cell: ({ row }) => (
        <span className='truncate text-sm text-muted-foreground'>
          {row.original.display_name || '-'}
        </span>
      )
    },
    // What the phone read off the account's own profile, next to — never on top
    // of — the name the operator typed. A login scenario writes both of these;
    // until now they were stored and never shown anywhere on this page.
    {
      id: 'observedName',
      accessorKey: 'observed_display_name',
      header: t('colObservedName'),
      cell: ({ row }) => {
        const name = row.original.observed_display_name;
        if (!name)
          return <span className='text-sm text-muted-foreground'>-</span>;
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className='truncate text-sm'>{name}</span>
            </TooltipTrigger>
            <TooltipContent>{t('observedNameHint')}</TooltipContent>
          </Tooltip>
        );
      }
    },
    {
      id: 'friends',
      accessorKey: 'friends_count',
      header: t('colFriends'),
      cell: ({ row }) => {
        const { friends_count: count, friends_observed_at: at } = row.original;
        if (count === null || count === undefined)
          return <span className='text-sm text-muted-foreground'>-</span>;
        const label = <span className='text-sm tabular-nums'>{count}</span>;
        if (!at) return label;
        return (
          <Tooltip>
            <TooltipTrigger asChild>{label}</TooltipTrigger>
            <TooltipContent>
              {t('friendsHint', {
                at: formatDistanceToNow(new Date(at), {
                  addSuffix: true,
                  locale: dateLocale
                })
              })}
            </TooltipContent>
          </Tooltip>
        );
      }
    },
    {
      id: 'status',
      header: t('colStatus'),
      cell: ({ row }) => {
        const account = row.original;
        const state = normalizeAccountState(
          account.state || account.status
        ) as AccountStateKey;
        const label = statusLabel[state] ?? state;
        const resting = isResting(account.cooldown_until);
        return (
          <div className='flex flex-col gap-0.5'>
            <Badge
              variant={STATUS_VARIANT[state] ?? 'outline'}
              className='w-fit text-[11px]'
            >
              {label}
            </Badge>
            {resting ? (
              <span className='text-[10px] text-muted-foreground'>
                {t('restingUntil', {
                  time: formatDistanceToNow(new Date(account.cooldown_until!), {
                    addSuffix: true,
                    locale: dateLocale
                  })
                })}
              </span>
            ) : null}
            {account.state_reason ? (
              <span className='max-w-[180px] truncate text-[10px] text-muted-foreground'>
                {account.state_reason}
              </span>
            ) : null}
          </div>
        );
      }
    },
    {
      id: 'tags',
      accessorKey: 'tags',
      header: t('colTags'),
      cell: ({ row }) => {
        const tags = row.original.tags;
        if (!tags) return <span className='text-muted-foreground'>-</span>;
        return (
          <div className='flex flex-wrap gap-1'>
            {tags
              .split(',')
              .filter(Boolean)
              .map((tag) => (
                <Badge key={tag} variant='secondary' className='text-[10px]'>
                  {tag.trim()}
                </Badge>
              ))}
          </div>
        );
      }
    },
    {
      id: 'createdAt',
      header: t('colTime'),
      cell: ({ row }) => (
        <span className='whitespace-nowrap text-[11px] text-muted-foreground'>
          {formatDistanceToNow(new Date(row.original.created_at), {
            addSuffix: true,
            locale: dateLocale
          })}
        </span>
      )
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => {
        const account = row.original;
        const current = account.state || account.status;
        const targets = allowedTransitionTargets(current);
        return (
          <div className='flex items-center gap-1'>
            <AccountLoginDialog account={account} canUpdate={perms.canUpdate} />
            <AccountDevicesDialog
              account={account}
              canUpdate={perms.canUpdate}
            />
            {perms.canUpdate || perms.canDelete || perms.canRead ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size='icon' variant='ghost' className='size-8'>
                    <MoreHorizontal size={14} />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align='end'>
                  <DropdownMenuItem asChild>
                    <Link
                      href={`${ROUTES.DASHBOARD.ACTIVITY_HISTORY.ROOT}?account_id=${encodeURIComponent(account.id)}`}
                    >
                      <History className='mr-2 size-4' />
                      {t('history')}
                    </Link>
                  </DropdownMenuItem>
                  {perms.canUpdate ? (
                    <EditAccountDialog
                      account={account}
                      trigger={
                        <DropdownMenuItem
                          onSelect={(event) => event.preventDefault()}
                        >
                          <Pencil className='mr-2 size-4' />
                          {t('edit')}
                        </DropdownMenuItem>
                      }
                    />
                  ) : null}
                  {perms.canUpdate && targets.length > 0 ? (
                    <AccountStateTransitionDialog
                      account={account}
                      trigger={
                        <DropdownMenuItem
                          onSelect={(event) => event.preventDefault()}
                        >
                          <RefreshCw className='mr-2 size-4' />
                          {t('transition')}
                        </DropdownMenuItem>
                      }
                    />
                  ) : null}
                  {perms.canDelete ? (
                    <DropdownMenuItem
                      className='text-destructive'
                      onClick={() => onDelete(account)}
                    >
                      <Trash2 size={14} className='mr-2' />
                      {t('delete')}
                    </DropdownMenuItem>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        );
      }
    }
  ];
}
