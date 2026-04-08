'use client';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  SidebarSeparator,
  useSidebar
} from '@/components/ui/sidebar';
// import { useUser } from '@/features/auth/hooks/use-auth';
//  import { useMediaQuery } from '@/hooks/use-media-query';
import { useNavItems } from '@/hooks/use-nav-items';
import { Link, usePathname, useRouter } from '@/i18n/navigation';
import { IconChevronRight } from '@tabler/icons-react';
import { useTranslations } from 'next-intl';
import * as React from 'react';
import { Icons } from '../icons';
import { OrgSwitcher } from '../org-switcher';
import { Button } from '../ui/button';
import { ROUTES } from '@/config/routes';
import { ArrowLeft } from 'lucide-react';
import {
  TooltipContent,
  Tooltip,
  TooltipTrigger,
  TooltipProvider
} from '../ui/tooltip';

import { useUser } from '@/features/auth';
import { useLogout } from '@/features/auth/hooks/use-logout';
import { FadeInSide } from '@/components/motion/fade-in-side';
import { TitleTooltip } from '../title-tooltip';
import { cn } from '@/lib/utils';

export const quickActions = (_t: any): { label: string; link: string; icon: React.ReactNode }[] =>
  [];

function SidebarMainMenu({ isSettingsPage }: { isSettingsPage: boolean }) {
  const t = useTranslations('navigation');
  const tCommon = useTranslations('common');
  const { baseItems, settingItems } = useNavItems();
  const pathname = usePathname();
  const { open } = useSidebar();
  const router = useRouter();

  const dropdownItemClasses = 'relative !pl-3';
  const dropdownItemActiveClasses =
    'before:absolute before:left-0 before:top-1/2 before:h-full before:w-0.5 before:-translate-y-1/2 before:rounded-full before:bg-primary';

  const handleBackToDashboard = () => {
    router.push(ROUTES.DASHBOARD.ROOT);
  };

  const menuItems = isSettingsPage ? settingItems : baseItems;

  return (
    <>
      <SidebarHeader>
        <OrgSwitcher />
        {isSettingsPage && (
          <div
            className={cn(
              'group/settings flex cursor-pointer items-center',
              open && 'gap-3'
            )}
            onClick={handleBackToDashboard}
          >
            {open ? (
              <div className='flex items-center gap-3 px-3'>
                <Button
                  variant='outline'
                  size='sm'
                  aria-label={tCommon('back')}
                  className='size-7 transition-transform duration-200 ease-in-out group-hover/settings:-translate-x-1'
                >
                  <ArrowLeft size={16} />
                </Button>
                <span className='text-lg font-medium'>{t('settings')}</span>
              </div>
            ) : (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant='outline' className='w-full'>
                      <ArrowLeft size={16} />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side='right'>
                    <p>{t('settings')}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        )}
      </SidebarHeader>
      <SidebarContent className='relative overflow-hidden'>
        <FadeInSide key={isSettingsPage ? 'settings' : 'main'}>
          {!isSettingsPage && quickActions(t).length > 0 && (
            <SidebarGroup className='bottom-b py-0 shadow-md'>
              <div className='my-2 flex w-full flex-col gap-2'>
                {quickActions(t).map((item) => {
                  return (
                    <Link
                      href={item.link as string}
                      key={item.label}
                      className='flex !w-full items-center justify-center'
                    >
                      {!open ? (
                        <TitleTooltip content={item.label} side='right'>
                          <Button size='icon' className='size-8'>
                            <span>{item.icon}</span>
                          </Button>
                        </TitleTooltip>
                      ) : (
                        <Button
                          variant='outline-primary'
                          className='flex w-full items-center justify-start'
                        >
                          <span>{item.icon}</span>
                          {open && <span>{item.label}</span>}
                        </Button>
                      )}
                    </Link>
                  );
                })}
              </div>
            </SidebarGroup>
          )}
          <SidebarGroup className='!mt-0 h-[calc(100vh-100px-31px-64px)] overflow-y-auto'>
            <SidebarMenu className='!z-10 space-y-3'>
              {menuItems.map((item) => {
                const Icon = item.icon ? Icons[item.icon] : Icons.logo;
                const isChildActive = item?.items?.some(
                  (subItem) => pathname === subItem.url
                );
                if (item.type === 'divider') {
                  return (
                    <SidebarSeparator
                      key={`${item.title}-divider`}
                      className='my-2'
                    />
                  );
                }
                if (item.type === 'group') {
                  return (
                    <SidebarGroup
                      key={`${item.title}-group`}
                      className='p-0'
                      data-sidebar='group'
                    >
                      <SidebarGroupLabel className='group-data-[collapsible=icon]:hidden'>
                        {item.title}
                      </SidebarGroupLabel>
                      <SidebarMenu>
                        {item.items?.map((subItem) => {
                          const Icon = subItem.icon
                            ? Icons[subItem.icon]
                            : Icons.logo;
                          return (
                            <SidebarMenuItem key={subItem.title}>
                              <SidebarMenuButton
                                className={cn(
                                  dropdownItemClasses,
                                  pathname === subItem.url &&
                                    dropdownItemActiveClasses
                                )}
                                isActive={pathname === subItem.url}
                                asChild
                                tooltip={subItem.title}
                              >
                                <Link href={subItem.url || ''}>
                                  {subItem.icon && <Icon />}
                                  <span>{subItem.title}</span>
                                </Link>
                              </SidebarMenuButton>
                            </SidebarMenuItem>
                          );
                        })}
                      </SidebarMenu>
                    </SidebarGroup>
                  );
                }
                return item?.items && item?.items?.length > 0 ? (
                  <Collapsible
                    key={item.title}
                    asChild
                    defaultOpen={item.isActive || isChildActive}
                    className='group/collapsible'
                  >
                    <SidebarMenuItem>
                      <CollapsibleTrigger asChild>
                        <SidebarMenuButton
                          tooltip={item.title}
                          isActive={pathname === item.url || isChildActive}
                        >
                          {item.icon && <Icon />}
                          <span>{item.title}</span>
                          <IconChevronRight className='ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90' />
                        </SidebarMenuButton>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <SidebarMenuSub>
                          {item.items?.map((subItem) => (
                            <SidebarMenuSubItem key={subItem.title}>
                              <SidebarMenuSubButton
                                className={cn(
                                  dropdownItemClasses,
                                  pathname === subItem.url &&
                                    dropdownItemActiveClasses
                                )}
                                asChild
                                isActive={pathname === subItem.url}
                              >
                                <Link href={subItem.url || ''}>
                                  <span>{subItem.title}</span>
                                </Link>
                              </SidebarMenuSubButton>
                            </SidebarMenuSubItem>
                          ))}
                        </SidebarMenuSub>
                      </CollapsibleContent>
                    </SidebarMenuItem>
                  </Collapsible>
                ) : (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      asChild
                      tooltip={item.title}
                      isActive={pathname === item.url}
                    >
                      <Link href={item.url || ''}>
                        <Icon />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroup>
        </FadeInSide>
      </SidebarContent>
    </>
  );
}

export default function AppSidebar() {
  const t = useTranslations('navigation');
  const { handleLogout } = useLogout();

  // const { isOpen } = useMediaQuery();
  const { user } = useUser();
  const router = useRouter();
  const pathname = usePathname();
  const isSettingsPage = pathname.includes(
    ROUTES.DASHBOARD.ORGANIZATION_SETTINGS('')
  );
  const { open } = useSidebar();
  return (
    <Sidebar collapsible='icon'>
      <SidebarMainMenu isSettingsPage={isSettingsPage} />

      <SidebarFooter>
        {open && (
          <div className='flex !w-full items-center justify-center text-center text-[10px] text-muted-foreground'>
            &copy; {new Date().getFullYear()} Device Farm - 1.0.0
          </div>
        )}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
