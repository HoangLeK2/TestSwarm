'use client';

import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { RelayConnectionState } from '../lib/relay-agent-status';

const STATE_STYLES: Record<
  RelayConnectionState,
  { variant: 'secondary' | 'outline' | 'default'; className?: string }
> = {
  inactive: {
    variant: 'secondary',
    className: 'text-muted-foreground'
  },
  connecting: {
    variant: 'outline',
    className: 'border-primary/35 bg-primary/5 text-primary'
  },
  connected: {
    variant: 'default',
    className:
      'border-transparent bg-emerald-600 text-white hover:bg-emerald-600'
  }
};

export function RelayAgentStatusBadge({
  state
}: {
  state: RelayConnectionState;
}) {
  const t = useTranslations('relayAgentsFeature.connectionStatus');
  const style = STATE_STYLES[state];

  return (
    <Badge
      variant={style.variant}
      className={cn('shrink-0 text-[11px] font-medium', style.className)}
    >
      {state === 'connecting' ? (
        <span className='mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-current' />
      ) : null}
      {t(state)}
    </Badge>
  );
}
