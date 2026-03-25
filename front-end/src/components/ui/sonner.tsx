'use client';

import { useTheme } from 'next-themes';
import { Toaster as Sonner, ToasterProps } from 'sonner';

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = 'system' } = useTheme();

  return (
    <Sonner
      theme={theme as ToasterProps['theme']}
      className='toaster group'
      toastOptions={{
        classNames: {
          toast:
            'group toast-base bg-background text-foreground border border-border shadow-lg rounded-lg p-4',
          title: 'font-semibold',
          description: 'text-sm opacity-90',
          actionButton:
            'bg-primary text-primary-foreground hover:bg-primary/90 px-3 py-1.5 rounded-md text-sm font-medium',
          cancelButton:
            'bg-muted text-muted-foreground hover:bg-muted/90 px-3 py-1.5 rounded-md text-sm font-medium',
          closeButton: 'bg-transparent hover:bg-muted rounded-md p-1',
          // Status-specific classNames
          success: 'bg-background !text-success border-success',
          error: 'bg-background !text-error border-error',
          warning: 'bg-background !text-warning border-warning',
          info: 'bg-background !text-info border-info'
        }
      }}
      duration={2000}
      {...props}
    />
  );
};

export { Toaster };
