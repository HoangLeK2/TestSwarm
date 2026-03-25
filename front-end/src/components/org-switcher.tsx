'use client';

import { ChevronsUpDown, Settings, UserPlus, Check } from 'lucide-react';
import * as React from 'react';

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel
} from '@/components/ui/dropdown-menu';
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem
} from '@/components/ui/sidebar';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import { useTranslations } from 'next-intl';
import { useSidebar } from '@/components/ui/sidebar';
import { cn } from '@/lib/utils';
import { OverflowTooltip } from './overflow-tooltip';
import type { ProtoOrganization } from '@/features/device-farm';
import { useRouter } from '@/i18n/navigation';
import Image from 'next/image';
import { ROUTES } from '@/config/routes';
import { useConfirm } from '@/providers/modal-provider';
import { formatOrgDisplayName } from '@/features/organization/utils/org-name';

export function OrgSwitcher() {
  const { open } = useSidebar();
  const { currentOrg, organizations, setCurrentOrg } = useOrganization();
  const router = useRouter();
  const t = useTranslations('organization');
  const confirm = useConfirm();

  const noNameFallback = t('noName');

  const formatOrgName = React.useCallback(
    (name?: string | null) => formatOrgDisplayName(name, noNameFallback),
    [noNameFallback]
  );

  const currentOrgName = formatOrgName(currentOrg?.businessName);

  const handleOrgSwitch = async (org: any) => {
    const confirmed = await confirm({
      title: t('switchOrg'),
      description: t('switchOrgConfirmation', { name: org.businessName })
    });
    if (confirmed) {
      setCurrentOrg(org);
      router.push(ROUTES.DASHBOARD.ROOT);
    }
  };

  const handleSettings = () => {
    router.push(ROUTES.DASHBOARD.ORGANIZATION_SETTINGS(currentOrg?.id || ''));
  };

  const handleInviteMembers = () => {
    router.push(ROUTES.DASHBOARD.ORGANIZATION_MEMBER(currentOrg?.id || ''));
  };

  const enableShowOrgList = organizations.length > 1;

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size='lg'
              className={cn(
                'w-full gap-3 data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground'
              )}
            >
              <div className='flex aspect-square size-8 items-center justify-center rounded-lg'>
                <Image
                  src={currentOrg?.businessLogo || '/logo.png'}
                  alt='nda-trace-logo'
                  className='rounded-full object-contain'
                  width={32}
                  height={32}
                />
              </div>
              {open && (
                <>
                  <div className='flex min-w-0 flex-1 flex-col gap-0.5 leading-none'>
                    <OverflowTooltip asChild>
                      <span className='block min-w-0 max-w-full truncate text-sm sm:text-base lg:max-w-[250px] xl:max-w-[320px]'>
                        {currentOrgName}
                      </span>
                    </OverflowTooltip>
                    {/* <span className='max-w-[150px] truncate text-xs text-muted-foreground'>
                      {currentOrg?.businessEmail}
                    </span> */}
                  </div>
                  <ChevronsUpDown className='ml-3 shrink-0' />
                </>
              )}
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className='w-64'
            align='start'
            sideOffset={14}
            alignOffset={10}
            side='right'
          >
            <div className='flex items-center gap-3 p-2'>
              <Image
                src={currentOrg?.businessLogo || '/logo.png'}
                alt='nda-trace-logo'
                className='size-8 shrink-0 rounded-full object-contain'
                width={32}
                height={32}
              />
              <div className='flex min-w-0 flex-1 flex-col gap-1 leading-tight'>
                <OverflowTooltip asChild>
                  <span className='line-clamp-2 block min-w-0 max-w-full text-pretty text-sm font-semibold'>
                    {currentOrg?.businessName || t('noName')}
                  </span>
                </OverflowTooltip>
                <span className='line-clamp-1 block min-w-0 max-w-full text-pretty break-words text-xs text-muted-foreground sm:line-clamp-2'>
                  {currentOrg?.businessEmail}
                </span>
              </div>
            </div>

            <DropdownMenuSeparator />

            {/* General Actions */}
            <DropdownMenuItem
              onClick={handleSettings}
              className='flex items-center gap-3 p-2'
            >
              <Settings className='h-4 w-4' />
              <span>{t('settings')}</span>
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={handleInviteMembers}
              className='flex items-center gap-3 p-2'
            >
              <UserPlus className='h-4 w-4' />
              <span>{t('inviteMembers')}</span>
            </DropdownMenuItem>

            {enableShowOrgList && (
              <>
                <DropdownMenuSeparator />

                <DropdownMenuLabel className='px-3 py-2 text-xs font-medium text-muted-foreground'>
                  {t('shortTitle')}
                </DropdownMenuLabel>

                <DropdownMenuItem
                  className={cn(
                    'flex items-center justify-between bg-muted/50 p-2',
                    'hover:bg-muted/70'
                  )}
                >
                  <div className='flex items-center gap-3'>
                    <Image
                      src={currentOrg?.businessLogo || '/logo.png'}
                      alt='workspace'
                      width={32}
                      height={32}
                      className='h-8 w-8 flex-shrink-0 rounded-full object-contain'
                    />
                    <OverflowTooltip asChild>
                      <span className='truncate text-sm font-medium'>
                        {currentOrg?.businessName || t('noName')}
                      </span>
                    </OverflowTooltip>
                  </div>
                  <Check className='h-4 w-4 text-foreground' />
                </DropdownMenuItem>

                {organizations
                  .filter((org) => org.id !== currentOrg?.id)
                  .map((org: ProtoOrganization) => (
                    <DropdownMenuItem
                      key={org.id}
                      onSelect={() => handleOrgSwitch(org)}
                      className='flex items-center gap-3 p-2'
                    >
                      <Image
                        src={org.businessLogo || '/logo.png'}
                        alt={org.businessName || t('noName')}
                        width={32}
                        height={32}
                        className='h-8 w-8 flex-shrink-0 rounded-full object-contain'
                      />
                      <OverflowTooltip asChild>
                        <span className='max-w-[200px] truncate text-sm font-medium'>
                          {org.businessName || t('noName')}
                        </span>
                      </OverflowTooltip>
                    </DropdownMenuItem>
                  ))}
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
