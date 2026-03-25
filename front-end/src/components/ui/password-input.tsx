'use client';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Eye, EyeOff } from 'lucide-react';
import { useTranslations } from 'next-intl';
import * as React from 'react';
import { Input } from './input';

export interface PasswordInputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ className, ...props }, ref) => {
    const [showPassword, setShowPassword] = React.useState(false);
    const t = useTranslations('common');

    const togglePasswordVisibility = () => {
      setShowPassword((prev) => !prev);
    };

    return (
      <div className='relative'>
        <Input
          type={showPassword ? 'text' : 'password'}
          className={cn(className)}
          ref={ref}
          {...props}
        />
        <Button
          type='button'
          variant='ghost'
          size='sm'
          className='absolute right-0 top-0 h-full'
          onClick={togglePasswordVisibility}
          disabled={props.disabled}
          aria-label={showPassword ? t('hidePassword') : t('showPassword')}
        >
          {showPassword ? (
            <EyeOff className='h-4 w-4 text-muted-foreground' />
          ) : (
            <Eye className='h-4 w-4 text-muted-foreground' />
          )}
        </Button>
      </div>
    );
  }
);

PasswordInput.displayName = 'PasswordInput';

export { PasswordInput };
