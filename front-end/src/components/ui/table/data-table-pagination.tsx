import type { Table } from '@tanstack/react-table';
import { ChevronsLeft, ChevronsRight } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { ChevronLeftIcon, ChevronRightIcon } from '@radix-ui/react-icons';

interface DataTablePaginationProps<TData> extends React.ComponentProps<'div'> {
  table: Table<TData>;
  pageSizeOptions?: number[];
  total?: number;
  showRowsPerPage?: boolean;
}

type TablePaginationControlsProps = React.ComponentProps<'div'> & {
  pageIndex: number;
  pageCount: number;
  pageSize: number;
  pageSizeOptions?: number[];
  total?: number;
  showRowsPerPage?: boolean;
  onPageIndexChange: (pageIndex: number) => void;
  onPageSizeChange: (pageSize: number) => void;
};

export function TablePaginationControls({
  pageIndex,
  pageCount,
  pageSize,
  pageSizeOptions = [10, 20, 30, 40, 50],
  className,
  total = 0,
  showRowsPerPage = true,
  onPageIndexChange,
  onPageSizeChange,
  ...props
}: TablePaginationControlsProps) {
  const t = useTranslations('components.table');
  const canPreviousPage = pageIndex > 0;
  const canNextPage = pageIndex < pageCount - 1;

  return (
    <div
      className={cn(
        'flex w-full flex-col-reverse items-center justify-between gap-4 overflow-auto p-1 sm:flex-row sm:gap-8',
        className
      )}
      {...props}
    >
      <div className='flex-1 whitespace-nowrap text-sm text-muted-foreground'>
        {/* {table.getFilteredSelectedRowModel().rows.length > 0 ? (
          <>
            {t('rowsSelected', {
              count: table.getFilteredSelectedRowModel().rows.length
            })}
          </>
        ) : (
          <>
            {t('rowsTotal', {
              count: table.getFilteredRowModel().rows.length
            })}
          </>
        )}{' '} */}
        {!!total && (
          <span className='text-xs text-muted-foreground'>
            {t('total')}: {total}
          </span>
        )}
      </div>
      <div className='flex flex-col-reverse items-center gap-4 sm:flex-row sm:gap-6 lg:gap-8'>
        {showRowsPerPage ? (
          <div className='flex items-center space-x-2'>
            <p className='whitespace-nowrap text-sm font-medium'>
              {t('rowsPerPage')}
            </p>
            <Select
              value={`${pageSize}`}
              onValueChange={(value) => {
                onPageSizeChange(Number(value));
              }}
            >
              <SelectTrigger className='h-8 w-[4.5rem] [&[data-size]]:h-8'>
                <SelectValue placeholder={pageSize} />
              </SelectTrigger>
              <SelectContent side='top'>
                {pageSizeOptions.map((pageSize) => (
                  <SelectItem key={pageSize} value={`${pageSize}`}>
                    {pageSize}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        <div className='flex items-center justify-center text-sm font-medium'>
          {t('pageOf', {
            current: pageIndex + 1,
            total: pageCount
          })}
        </div>
        <div className='flex items-center space-x-2'>
          <Button
            aria-label={t('goToFirstPage')}
            variant='outline'
            size='icon'
            className='hidden size-8 lg:flex'
            onClick={() => onPageIndexChange(0)}
            disabled={!canPreviousPage}
          >
            <ChevronsLeft />
          </Button>
          <Button
            aria-label={t('goToPreviousPage')}
            variant='outline'
            size='icon'
            className='size-8'
            onClick={() => onPageIndexChange(pageIndex - 1)}
            disabled={!canPreviousPage}
          >
            <ChevronLeftIcon />
          </Button>
          <Button
            aria-label={t('goToNextPage')}
            variant='outline'
            size='icon'
            className='size-8'
            onClick={() => onPageIndexChange(pageIndex + 1)}
            disabled={!canNextPage}
          >
            <ChevronRightIcon />
          </Button>
          <Button
            aria-label={t('goToLastPage')}
            variant='outline'
            size='icon'
            className='hidden size-8 lg:flex'
            onClick={() => onPageIndexChange(pageCount - 1)}
            disabled={!canNextPage}
          >
            <ChevronsRight />
          </Button>
        </div>
      </div>
    </div>
  );
}

export function DataTablePagination<TData>({
  table,
  pageSizeOptions = [10, 20, 30, 40, 50],
  className,
  total = 0,
  showRowsPerPage = true,
  ...props
}: DataTablePaginationProps<TData>) {
  return (
    <TablePaginationControls
      pageIndex={table.getState().pagination.pageIndex}
      pageCount={table.getPageCount()}
      pageSize={table.getState().pagination.pageSize}
      pageSizeOptions={pageSizeOptions}
      className={className}
      total={total}
      showRowsPerPage={showRowsPerPage}
      onPageIndexChange={(pageIndex) => table.setPageIndex(pageIndex)}
      onPageSizeChange={(pageSize) => table.setPageSize(pageSize)}
      {...props}
    />
  );
}
