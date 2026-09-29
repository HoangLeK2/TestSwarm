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
  CalendarClock,
  Footprints,
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
import { AccountVerificationSetupDialog } from '../account-verification-setup-dialog';
import { AccountDevicesDialog } from '../account-devices-dialog';
import { AccountLoginDialog } from '../account-login-dialog';
import { AccountStepTraceDialog } from '../account-step-trace-dialog';
import Link from 'next/link';
import { ROUTES } from '@/config/routes';
import type { ResourcePermissionFlags } from '@/features/auth/types/resource-permissions';

type TFn = (key: string, values?: Record<string, any>) => string;

const STATUS_VARIANT: Record<
  string,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  unassigned: 'secondary',
  assigned: 'outline',
  active: 'default',
  suspended: 'outline',
  banned: 'destructive',
  retired: 'outline'
};

export type { AccountStateKey };

function readableStateReason(reason: string | null | undefined, t: TFn) {
  if (!reason) return '';
  const normalized = reason.trim().toLowerCase();
  if (!normalized) return '';
  if (
    normalized.includes('no device') ||
    normalized.includes('unlinked') ||
    normalized.includes('device linked')
  ) {
    return t('reasonNoDevice');
  }
  if (
    normalized.includes('band') ||
    normalized.includes('ban') ||
    normalized.includes('cấm')
  ) {
    return t('reasonBanned');
  }
  if (normalized.includes('checkpoint') || normalized.includes('verify')) {
    return t('reasonVerification');
  }
  if (normalized.includes('manual')) return t('reasonManual');
  return t('reasonNeedsReview');
}

function accountDisplayName(account: AccountOut, t: TFn) {
  const displayName =
    account.display_name || account.observed_display_name || '';
  if (/^\d{8,}$/.test(displayName.trim())) return t('unnamed');
  return displayName || t('unnamed');
}

function shortAccountCode(username: string) {
  const clean = username.trim();
  if (clean.length <= 4) return clean;
  return clean.slice(-4);
}

function visibleTags(account: AccountOut) {
  const platform = account.platform?.trim().toLowerCase();
  return (account.tags || '')
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
    .filter((tag) => tag.toLowerCase() !== platform);
}

export function getAccountColumns(
  t: TFn,
  statusLabel: Record<AccountStateKey, string>,
  dateLocale: Locale,
  perms: ResourcePermissionFlags,
  onDelete: (account: AccountOut) => void
): ColumnDef<AccountOut>[] {
  return [
    {
      id: 'account',
      header: t('colAccount'),
      cell: ({ row }) => {
        const account = row.original;
        const envFlag = detectAccountEnvironment(account);
        return (
          <div className='min-w-[240px] space-y-2'>
            <div className='flex min-w-0 flex-wrap items-center gap-1.5'>
              <span className='truncate text-sm font-semibold'>
                {accountDisplayName(account, t)}
              </span>
              <Badge variant='outline' className='text-[10px] capitalize'>
                {account.platform}
              </Badge>
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
            <div className='space-y-0.5 text-xs text-muted-foreground'>
              <p>
                {t('loginCode', { code: shortAccountCode(account.username) })}
              </p>
              {account.observed_display_name && account.display_name ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <p className='truncate'>
                      {t('observedNameValue', {
                        name: account.observed_display_name
                      })}
                    </p>
                  </TooltipTrigger>
                  <TooltipContent>{t('observedNameHint')}</TooltipContent>
                </Tooltip>
              ) : null}
            </div>
          </div>
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
        const reason = readableStateReason(account.state_reason, t);
        return (
          <div className='flex min-w-[180px] flex-col gap-1'>
            <Badge
              variant={STATUS_VARIANT[state] ?? 'outline'}
              className='w-fit text-[11px]'
            >
              {label}
            </Badge>
            {reason ? (
              <span className='text-xs text-muted-foreground'>{reason}</span>
            ) : null}
            {resting ? (
              <span className='text-xs text-muted-foreground'>
                {t('restingUntil', {
                  time: formatDistanceToNow(new Date(account.cooldown_until!), {
                    addSuffix: true,
                    locale: dateLocale
                  })
                })}
              </span>
            ) : null}
            {account.verification_hold_until ? (
              <span className='text-xs text-muted-foreground'>
                {t('verificationHoldUntil', {
                  time: formatDistanceToNow(
                    new Date(account.verification_hold_until),
                    {
                      addSuffix: true,
                      locale: dateLocale
                    }
                  )
                })}
              </span>
            ) : null}
          </div>
        );
      }
    },
    {
      id: 'phone',
      accessorKey: 'assigned_device_name',
      header: t('colPhone'),
      cell: ({ row }) => (
        <span className='text-sm'>
          {row.original.assigned_device_name || (
            <span className='text-muted-foreground'>{t('phoneUnassigned')}</span>
          )}
        </span>
      )
    },
    {
      id: 'friends',
      accessorKey: 'friends_count',
      header: t('colFriends'),
      cell: ({ row }) => {
        const { friends_count: count, friends_observed_at: at } = row.original;
        if (count === null || count === undefined) {
          return (
            <span className='text-sm text-muted-foreground'>
              {t('unknown')}
            </span>
          );
        }
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
      id: 'tags',
      accessorKey: 'tags',
      header: t('colTags'),
      cell: ({ row }) => {
        const tags = visibleTags(row.original);
        if (tags.length === 0) {
          return (
            <span className='text-sm text-muted-foreground'>{t('noTags')}</span>
          );
        }
        return (
          <div className='flex max-w-[180px] flex-wrap gap-1'>
            {tags.map((tag) => (
              <Badge key={tag} variant='secondary' className='text-[10px]'>
                {tag.trim()}
              </Badge>
            ))}
          </div>
        );
      }
    },
    {
      id: 'notes',
      accessorKey: 'notes',
      header: t('colNotes'),
      cell: ({ row }) => {
        const notes = row.original.notes?.trim();
        if (!notes) {
          return (
            <span className='text-sm text-muted-foreground'>
              {t('noNotes')}
            </span>
          );
        }
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className='block max-w-[220px] truncate text-sm'>
                {notes}
              </span>
            </TooltipTrigger>
            <TooltipContent className='max-w-sm whitespace-pre-wrap'>
              {notes}
            </TooltipContent>
          </Tooltip>
        );
      }
    },
    {
      id: 'createdAt',
      header: t('colTime'),
      cell: ({ row }) => (
        <span className='whitespace-nowrap text-xs text-muted-foreground'>
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
        const canSetupVerification = targets.includes('suspended');
        const hasVerificationSetup = Boolean(account.verification_hold_until);
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
                  <Button
                    size='icon'
                    variant='ghost'
                    className='size-8'
                    aria-label={t('moreActions', {
                      account: accountDisplayName(account, t)
                    })}
                  >
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
                  <AccountStepTraceDialog
                    account={account}
                    trigger={
                      <DropdownMenuItem
                        onSelect={(event) => event.preventDefault()}
                      >
                        <Footprints className='mr-2 size-4' />
                        {t('stepTrace')}
                      </DropdownMenuItem>
                    }
                  />
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
                  {perms.canUpdate && canSetupVerification ? (
                    <AccountStateTransitionDialog
                      account={account}
                      defaultTo='suspended'
                      trigger={
                        <DropdownMenuItem
                          onSelect={(event) => event.preventDefault()}
                        >
                          <CalendarClock className='mr-2 size-4' />
                          {t('setupVerification')}
                        </DropdownMenuItem>
                      }
                    />
                  ) : null}
                  {hasVerificationSetup ? (
                    <AccountVerificationSetupDialog
                      account={account}
                      trigger={
                        <DropdownMenuItem
                          onSelect={(event) => event.preventDefault()}
                        >
                          <CalendarClock className='mr-2 size-4' />
                          {t('viewVerificationSetup')}
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
