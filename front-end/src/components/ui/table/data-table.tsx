import { type Table as TanstackTable, flexRender } from '@tanstack/react-table';
import * as React from 'react';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { DataTablePagination } from '@/components/ui/table/data-table-pagination';
import { getCommonPinningStyles } from '@/lib/data-table';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import { DataTableSkeleton } from './data-table-skeleton';
import { useDataTableLoading } from '@/hooks/use-data-table-loading';

interface LoadingProps {
  isLoading: boolean;
  content?: React.ReactNode;
  minDuration?: number; // minimum loading duration in ms
}

interface DataTableProps<TData> extends React.ComponentProps<'div'> {
  table: TanstackTable<TData>;
  actionBar?: React.ReactNode;
  showPagination?: boolean;
  skeletonRowCount?: number;
  loading?: LoadingProps;
  total?: number;
}

export function DataTable<TData>({
  table,
  actionBar,
  children,
  className,
  showPagination = true,
  loading,
  total = 0,
  ...props
}: DataTableProps<TData>) {
  const tableTranslations = useTranslations('components.table');

  // Use minimum loading hook if loading is provided
  const dataTableLoading = useDataTableLoading({
    isLoading: loading?.isLoading ?? false,
    minDuration: loading?.minDuration ?? 500
  });

  const finalLoading = loading
    ? {
        isLoading: dataTableLoading.isMinLoading,
        content: loading.content
      }
    : undefined;

  return (
    <div
      className={cn('flex w-full flex-col gap-2.5 overflow-auto', className)}
      {...props}
    >
      {children}
      {/* <DataTableViewOptions table={table} /> */}
      {finalLoading?.isLoading ? (
        finalLoading?.content ? (
          finalLoading?.content
        ) : (
          <DataTableSkeleton columnCount={3} rowCount={3} />
        )
      ) : (
        <>
          <div className='z-10 overflow-auto rounded border'>
            <Table>
              <TableHeader className='sticky top-0 z-10 w-full'>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id} className='w-full !bg-muted'>
                    {headerGroup.headers.map((header) => (
                      <TableHead
                        className='!bg-muted'
                        key={header.id}
                        colSpan={header.colSpan}
                        style={{
                          ...getCommonPinningStyles({
                            column: header.column,
                            withBorder: true
                          })
                        }}
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext()
                            )}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel()?.rows?.length ? (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      data-state={row.getIsSelected() && 'selected'}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                          key={cell.id}
                          className={cn(
                            cell.column.columnDef.meta?.cellClassName
                          )}
                          style={{
                            ...getCommonPinningStyles({
                              column: cell.column,
                              withBorder: true
                            })
                          }}
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={table.getAllColumns()?.length}
                      className='h-24 text-center'
                    >
                      {tableTranslations('noData')}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {/* <ScrollBar orientation='horizontal' /> */}
          {showPagination && (
            <div className='flex flex-col gap-2.5'>
              <DataTablePagination table={table} total={total} />

              {actionBar &&
                table.getFilteredSelectedRowModel()?.rows?.length > 0 &&
                actionBar}
            </div>
          )}
        </>
      )}
    </div>
  );
}
