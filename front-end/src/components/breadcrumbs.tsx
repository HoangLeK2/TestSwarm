'use client';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator
} from '@/components/ui/breadcrumb';
import { useBreadcrumbs } from '@/hooks/use-breadcrumbs';
import { IconSlash } from '@tabler/icons-react';
import { Link } from '@/i18n/navigation';
import { Fragment } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip';

export function Breadcrumbs() {
  const items = useBreadcrumbs();
  if (items.length === 0) return null;

  return (
    <Breadcrumb>
      <BreadcrumbList>
        {items.map((item, index) => {
          return (
            <Fragment key={item.title as string}>
              {index !== items.length - 1 && (
                <Tooltip>
                  <TooltipTrigger>
                    <BreadcrumbItem className='hidden max-w-[100px] truncate md:block'>
                      <BreadcrumbLink asChild>
                        <Link href={item.link}>{item.title}</Link>
                      </BreadcrumbLink>
                    </BreadcrumbItem>
                  </TooltipTrigger>
                  <TooltipContent>{item.title}</TooltipContent>
                </Tooltip>
              )}
              {index < items.length - 1 && (
                <BreadcrumbSeparator className='hidden md:block'>
                  <IconSlash />
                </BreadcrumbSeparator>
              )}
              {index === items.length - 1 && (
                <BreadcrumbPage>{item.title}</BreadcrumbPage>
              )}
            </Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
