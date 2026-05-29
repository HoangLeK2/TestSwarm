'use client';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { UserAvatarProfile } from '@/components/user-avatar-profile';
import { useUser } from '@/features/auth';
import { useLogout } from '@/features/auth/hooks/use-logout';
// import { useRouter } from '@/i18n/navigation';
import { useTranslations } from 'next-intl';
import { DropdownMenuLabel } from '../ui/dropdown-menu';
// import { DropdownMenuGroup } from '../ui/dropdown-menu';
// import { ROUTES } from '@/config/routes';
// import { IconSettings } from '@tabler/icons-react';
import { IconLogout } from '@tabler/icons-react';
import { useConfirm } from '@/providers/modal-provider';

export function UserNav() {
  const { user } = useUser();
  // const router = useRouter();
  const t = useTranslations('navigation');
  const tCommon = useTranslations('common');
  const { handleLogout } = useLogout();
  const confirm = useConfirm();

  if (user) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant='ghost' className='relative h-8 w-8 rounded-full'>
            <UserAvatarProfile user={user} />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          className='w-(--radix-dropdown-menu-trigger-width) z-50 min-w-56 rounded-lg'
          side='bottom'
          align='end'
          sideOffset={10}
          alignOffset={10}
        >
          <DropdownMenuLabel className='p-0 font-normal'>
            <div className='px-1 py-1.5'>
              {user && (
                <UserAvatarProfile
                  className='h-8 w-8 rounded-lg'
                  showInfo
                  user={user}
                />
              )}
            </div>
          </DropdownMenuLabel>
          {/* <DropdownMenuSeparator /> */}
          {/* 
          <DropdownMenuGroup>
            <DropdownMenuItem
              onClick={() =>
                router.push(ROUTES.DASHBOARD.SETTINGS.ORGANIZATION)
              }
            >
              <IconSettings className='mr-2 h-4 w-4' />
              {t('settings')}
            </DropdownMenuItem>
          </DropdownMenuGroup> */}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() =>
              confirm({
                title: t('logout'),
                confirmText: tCommon('confirm'),
                confirmVariant: 'destructive',
                zIndex: 10000,
                onConfirm: handleLogout
              })
            }
            variant='destructive'
          >
            <IconLogout className='mr-2 h-4 w-4 text-destructive' />
            {t('logout')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }
}
