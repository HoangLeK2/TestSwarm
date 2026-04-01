import { formatDistanceToNow } from 'date-fns';
import { vi } from 'date-fns/locale';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Copy, MoreHorizontal, Trash2 } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import type { ScenarioTemplateOut } from '../../services/api';
import { EditTemplateDialog } from '../edit-template-dialog';
import { UseTemplateDialog } from '../use-template-dialog';

type TFn = (key: string, values?: Record<string, any>) => string;

export function getTemplateColumns(
  t: TFn,
  onDelete: (template: ScenarioTemplateOut) => void,
  onDuplicate: (template: ScenarioTemplateOut) => void
): ColumnDef<ScenarioTemplateOut>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: t('colName'),
      cell: ({ row }) => (
        <div>
          <span className='truncate text-sm font-semibold'>
            {row.original.name}
          </span>
          {row.original.is_builtin && (
            <Badge variant='outline' className='ml-2 text-[10px]'>
              built-in
            </Badge>
          )}
        </div>
      )
    },
    {
      id: 'category',
      accessorKey: 'category',
      header: t('colCategory'),
      cell: ({ row }) => (
        <Badge variant='secondary' className='text-[11px]'>
          {row.original.category}
        </Badge>
      )
    },
    {
      id: 'description',
      accessorKey: 'description',
      header: t('colDescription'),
      cell: ({ row }) => (
        <span className='line-clamp-1 text-sm text-muted-foreground'>
          {row.original.description || '-'}
        </span>
      )
    },
    {
      id: 'steps',
      header: t('colSteps'),
      cell: ({ row }) => (
        <Badge variant='outline'>{row.original.steps?.length ?? 0}</Badge>
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
            locale: vi
          })}
        </span>
      )
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => {
        const tpl = row.original;
        return (
          <div className='flex items-center gap-1'>
            <UseTemplateDialog template={tpl} />
            {!tpl.is_builtin && <EditTemplateDialog template={tpl} />}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size='icon' variant='ghost' className='size-8'>
                  <MoreHorizontal size={14} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuItem onClick={() => onDuplicate(tpl)}>
                  <Copy size={14} className='mr-2' />
                  {t('duplicate')}
                </DropdownMenuItem>
                {!tpl.is_builtin && (
                  <DropdownMenuItem
                    className='text-destructive'
                    onClick={() => onDelete(tpl)}
                  >
                    <Trash2 size={14} className='mr-2' />
                    {t('delete')}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        );
      }
    }
  ];
}
