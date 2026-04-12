import { cn } from '@/lib/utils';
import { Breadcrumbs } from '../breadcrumbs';
import { LanguageSwitcher } from '../language-switcher';
import { Separator } from '../ui/separator';
import { SidebarTrigger } from '../ui/sidebar';
import { ModeToggle } from './ThemeToggle/theme-toggle';
import { UserNav } from './user-nav';
import { DeviceEventNotifications } from '@/features/devices/components/device-event-notifications';

export default function Header({
  className
}: {
  className?: string | undefined;
}) {
  return (
    <header
      data-navbar-style='sticky'
      className={cn(
        'group-has-data-[collapsible=icon]/sidebar-wrapper:h-12 flex h-12 shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear data-[navbar-style=sticky]:sticky data-[navbar-style=sticky]:top-0 data-[navbar-style=sticky]:z-50 data-[navbar-style=sticky]:overflow-hidden data-[navbar-style=sticky]:rounded-t-[inherit] data-[navbar-style=sticky]:bg-background/50 data-[navbar-style=sticky]:backdrop-blur-md',
        !!className && className
      )}
    >
      <div className={cn('flex w-full items-center justify-between')}>
        <div className='flex items-center gap-2 px-4'>
          <SidebarTrigger className='-ml-1' />
          <Separator orientation='vertical' className='mr-2 h-4' />
          <Breadcrumbs />
        </div>

        <div className='flex items-center gap-2 px-4'>
          <DeviceEventNotifications />
          <LanguageSwitcher />
          <ModeToggle />
          <UserNav />
        </div>
      </div>
    </header>
  );
}
