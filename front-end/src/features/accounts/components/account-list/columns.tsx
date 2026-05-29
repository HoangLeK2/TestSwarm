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
import { MoreHorizontal, Trash2 } from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { detectAccountEnvironment } from '../../lib/account-environment';
import type { ColumnDef } from '@tanstack/react-table';
import type { AccountOut } from '../../services/api';
import { EditAccountDialog } from '../edit-account-dialog';
import { AccountHistoryDialog } from '../account-history-dialog';

type TFn = (key: string, values?: Record<string, any>) => string;

const STATUS_VARIANT: Record<
  string,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  active: 'default',
  cooldown: 'secondary',
  banned: 'destructive',
  disabled: 'outline'
};

const ACCOUNT_STATUSES = ['active', 'cooldown', 'banned', 'disabled'] as const;
export type AccountStatusKey = (typeof ACCOUNT_STATUSES)[number];

export function getAccountColumns(
  t: TFn,
  statusLabel: Record<AccountStatusKey, string>,
  dateLocale: Locale,
  onDelete: (account: AccountOut) => void,
  onStatusChange: (account: AccountOut, status: string) => void
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
    {
      id: 'status',
      header: t('colStatus'),
      cell: ({ row }) => (
        <Badge
          variant={STATUS_VARIANT[row.original.status] ?? 'outline'}
          className='text-[11px]'
        >
          {statusLabel[row.original.status as AccountStatusKey] ??
            row.original.status}
        </Badge>
      )
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
        return (
          <div className='flex items-center gap-1'>
            <AccountHistoryDialog account={account} />
            <EditAccountDialog account={account} />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size='icon' variant='ghost' className='size-8'>
                  <MoreHorizontal size={14} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                {ACCOUNT_STATUSES.filter((s) => s !== account.status).map(
                  (s) => (
                    <DropdownMenuItem
                      key={s}
                      onClick={() => onStatusChange(account, s)}
                    >
                      {t('setStatus', { status: statusLabel[s] })}
                    </DropdownMenuItem>
                  )
                )}
                <DropdownMenuItem
                  className='text-destructive'
                  onClick={() => onDelete(account)}
                >
                  <Trash2 size={14} className='mr-2' />
                  {t('delete')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        );
      }
    }
  ];
}
