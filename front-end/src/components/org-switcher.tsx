'use client';

import {
  ArrowLeft,
  ChevronsUpDown,
  Settings,
  UserPlus,
  Check,
  Search
} from 'lucide-react';
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
import { usePathname, useRouter } from '@/i18n/navigation';
import Image from 'next/image';
import { ROUTES } from '@/config/routes';
import { useConfirm } from '@/providers/modal-provider';
import { formatOrgDisplayName } from '@/features/organization/utils/org-name';
import { useQueryClient } from '@tanstack/react-query';
import { Input } from '@/components/ui/input';
import { useOrganizationsInfinite } from '@/features/organization/hooks/use-organizations';
import { useUser } from '@/features/auth';

export function OrgSwitcher() {
  const { open } = useSidebar();
  const { currentOrg, setCurrentOrg } = useOrganization();
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations('organization');
  const { user } = useUser();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [orgSearch, setOrgSearch] = React.useState('');
  const [orgSearchInput, setOrgSearchInput] = React.useState('');
  const {
    data: orgPages,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage
  } = useOrganizationsInfinite(orgSearch);

  const switcherOrgs = React.useMemo(() => {
    const merged = orgPages?.pages.flatMap((p) => p?.items ?? []) ?? [];
    const seen = new Set<string>();
    return merged.filter((org) => {
      if (seen.has(org.id)) return false;
      seen.add(org.id);
      return true;
    });
  }, [orgPages]);

  const noNameFallback = t('noName');

  const formatOrgName = React.useCallback(
    (name?: string | null) => formatOrgDisplayName(name, noNameFallback),
    [noNameFallback]
  );

  const currentOrgName = formatOrgName(currentOrg?.businessName);
  const isAdminConsole =
    pathname === ROUTES.ADMIN.ROOT ||
    pathname.startsWith(`${ROUTES.ADMIN.ROOT}/`);
  const canReturnToAdminConsole =
    user?.role === 'superadmin' || user?.orgRole === 'admin';

  if (isAdminConsole) {
    return (
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            size='lg'
            className='w-full cursor-default gap-3 hover:bg-transparent active:bg-transparent'
            aria-label={t('adminConsoleTitle')}
          >
            <div className='flex aspect-square size-8 items-center justify-center rounded-lg'>
              <Image
                src='/logo.png'
                alt='admin-console-logo'
                className='rounded-full object-contain'
                width={32}
                height={32}
              />
            </div>
            {open ? (
              <div className='flex min-w-0 flex-1 flex-col gap-0.5 leading-none'>
                <OverflowTooltip asChild>
                  <span className='block min-w-0 max-w-full truncate text-sm font-semibold sm:text-base lg:max-w-[250px] xl:max-w-[320px]'>
                    {t('adminConsoleTitle')}
                  </span>
                </OverflowTooltip>
                <span className='truncate text-xs text-muted-foreground'>
                  {t('adminConsoleScope')}
                </span>
              </div>
            ) : null}
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    );
  }

  const handleOrgSwitch = async (org: any) => {
    const confirmed = await confirm({
      title: t('switchOrg'),
      description: t('switchOrgConfirmation', { name: org.businessName })
    });
    if (confirmed) {
      setCurrentOrg(org);
      await queryClient.invalidateQueries();
      router.push(ROUTES.DASHBOARD.ROOT);
    }
  };

  const handleSettings = () => {
    router.push(ROUTES.DASHBOARD.ORGANIZATION);
  };

  const handleInviteMembers = () => {
    router.push(ROUTES.DASHBOARD.ORGANIZATION_MEMBER);
  };

  const enableShowOrgList =
    switcherOrgs.length > 1 ||
    (orgPages?.pages[0]?.total ?? switcherOrgs.length) > 1;

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

            {canReturnToAdminConsole ? (
              <>
                <DropdownMenuItem
                  onClick={() => router.push(ROUTES.ADMIN.ROOT)}
                  className='flex items-center gap-3 p-2'
                >
                  <ArrowLeft className='h-4 w-4' />
                  <span>{t('backToAdminConsole')}</span>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            ) : null}

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

                <div className='px-2 pb-2'>
                  <div className='relative'>
                    <Search className='absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
                    <Input
                      value={orgSearchInput}
                      onChange={(e) => setOrgSearchInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          setOrgSearch(orgSearchInput.trim());
                        }
                      }}
                      placeholder={t('searchOrgs')}
                      className='h-8 pl-8 text-xs'
                      onClick={(e) => e.stopPropagation()}
                    />
                  </div>
                </div>

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

                {switcherOrgs
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

                {hasNextPage ? (
                  <DropdownMenuItem
                    className='justify-center p-2 text-xs text-muted-foreground'
                    onSelect={(e) => {
                      e.preventDefault();
                      void fetchNextPage();
                    }}
                  >
                    {isFetchingNextPage ? '…' : t('loadMoreOrgs')}
                  </DropdownMenuItem>
                ) : null}
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
