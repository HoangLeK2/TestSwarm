'use client';

import { useEffect } from 'react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export type CoreEmptyStateCta = {
  label: string;
  href?: string;
  onClick?: () => void;
};

export type CoreEmptyStateProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  /** Shown when user lacks permission for the primary CTA. */
  readOnlyHint?: string;
  cta?: CoreEmptyStateCta;
  secondaryCta?: CoreEmptyStateCta;
  variant?: 'no-data' | 'no-results';
  className?: string;
  /** Analytics hook — fired once on mount. */
  trackingKey?: string;
};

function trackEmptyStateView(key: string | undefined) {
  if (!key || typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent('core-empty-state:view', { detail: { key } })
  );
}

function CtaButton({
  cta,
  variant
}: {
  cta: CoreEmptyStateCta;
  variant: 'default' | 'outline';
}) {
  if (cta.href) {
    return (
      <Button asChild size='sm' variant={variant} className='min-w-[8rem]'>
        <Link href={cta.href}>{cta.label}</Link>
      </Button>
    );
  }
  return (
    <Button
      size='sm'
      variant={variant}
      className='min-w-[8rem]'
      onClick={cta.onClick}
    >
      {cta.label}
    </Button>
  );
}

/** RBAC-aware empty state for core dashboard workflows (DF-T-11-017). */
export function CoreEmptyState({
  icon: Icon,
  title,
  description,
  readOnlyHint,
  cta,
  secondaryCta,
  variant = 'no-data',
  className,
  trackingKey
}: CoreEmptyStateProps) {
  useEffect(() => {
    trackEmptyStateView(trackingKey);
  }, [trackingKey]);

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-12 text-center sm:px-10 sm:py-16',
        variant === 'no-results'
          ? 'border-border/60 bg-muted/10'
          : 'border-border bg-muted/20',
        className
      )}
    >
      <div className='mb-4 flex size-14 shrink-0 items-center justify-center rounded-full bg-muted/60'>
        <Icon className='size-7 text-muted-foreground/70' strokeWidth={1.5} />
      </div>
      <p className='max-w-md text-sm font-semibold text-foreground'>{title}</p>
      <p className='mt-2 max-w-md text-xs leading-relaxed text-muted-foreground'>
        {description}
      </p>
      {readOnlyHint ? (
        <p className='mt-3 max-w-md text-xs text-muted-foreground/80'>
          {readOnlyHint}
        </p>
      ) : null}
      {(cta || secondaryCta) && (
        <div className='mt-5 flex w-full max-w-sm flex-col items-stretch gap-2 sm:flex-row sm:justify-center'>
          {cta ? <CtaButton cta={cta} variant='default' /> : null}
          {secondaryCta ? (
            <CtaButton cta={secondaryCta} variant='outline' />
          ) : null}
        </div>
      )}
    </div>
  );
}
