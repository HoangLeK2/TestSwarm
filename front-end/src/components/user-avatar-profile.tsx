import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import type { SessionUser } from '@/features/auth/types/session-user';

interface UserAvatarProfileProps {
  className?: string;
  showInfo?: boolean;
  user: SessionUser;
}

export function UserAvatarProfile({
  className,
  showInfo = false,
  user
}: UserAvatarProfileProps) {
  return (
    <div className='flex items-center gap-2'>
      <Avatar className={className}>
        <AvatarImage src={user.picture || ''} alt={user.givenName || ''} />
        <AvatarFallback className='rounded-lg'>
          {user.givenName?.slice(0, 2)?.toUpperCase() || 'CN'}
        </AvatarFallback>
      </Avatar>

      {showInfo && (
        <div className='grid flex-1 text-left text-sm leading-tight'>
          <span className='truncate font-semibold'>{user.givenName || ''}</span>
          <span className='truncate text-xs'>{user.email || ''}</span>
        </div>
      )}
    </div>
  );
}
