import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const typographyVariants = cva('', {
  variants: {
    variant: {
      h1: 'scroll-m-20 text-4xl font-extrabold tracking-tight lg:text-5xl',
      h2: 'scroll-m-20 pb-2 text-3xl font-semibold tracking-tight first:mt-0',
      h3: 'scroll-m-20 text-2xl font-semibold tracking-tight',
      h4: 'scroll-m-20 text-xl font-semibold tracking-tight',
      h5: 'text-lg font-semibold',
      h6: 'text-base font-semibold',
      p: 'leading-7',
      blockquote: 'border-l-2 pl-6 italic',
      ul: 'my-6 ml-6 list-disc [&>li]:mt-2',
      ol: 'my-6 ml-6 list-decimal [&>li]:mt-2',
      code: 'relative rounded bg-muted px-[0.3rem] py-[0.2rem] font-mono text-sm font-semibold',
      lead: 'text-xl text-muted-foreground',
      large: 'text-lg font-semibold',
      small: 'text-sm font-medium leading-none',
      muted: 'text-sm text-muted-foreground'
    },
    align: {
      left: 'text-left',
      center: 'text-center',
      right: 'text-right',
      justify: 'text-justify'
    }
  },
  defaultVariants: {
    variant: 'p',
    align: 'left'
  }
});

interface TypographyProps
  extends React.HTMLAttributes<HTMLElement>,
    VariantProps<typeof typographyVariants> {
  asChild?: boolean;
  as?: keyof React.ReactNode;
}

const Typography = React.forwardRef<HTMLElement, TypographyProps>(
  ({ className, variant, align, asChild = false, as, ...props }, ref) => {
    const Comp = asChild
      ? Slot
      : as || (getDefaultElement(variant) as keyof React.ReactNode);

    return (
      <Comp
        className={cn(typographyVariants({ variant, align, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);

Typography.displayName = 'Typography';

function getDefaultElement(variant: TypographyProps['variant']) {
  switch (variant) {
    case 'h1':
      return 'h1';
    case 'h2':
      return 'h2';
    case 'h3':
      return 'h3';
    case 'h4':
      return 'h4';
    case 'h5':
      return 'h5';
    case 'h6':
      return 'h6';
    case 'blockquote':
      return 'blockquote';
    case 'ul':
      return 'ul';
    case 'ol':
      return 'ol';
    case 'code':
      return 'code';
    case 'lead':
    case 'large':
    case 'small':
    case 'muted':
    case 'p':
    default:
      return 'p';
  }
}

export { Typography, typographyVariants };
export type { TypographyProps };
