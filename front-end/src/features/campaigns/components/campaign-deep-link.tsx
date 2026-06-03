'use client';

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode
} from 'react';
import { useSearchParams } from 'next/navigation';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';

type CampaignFocusContextValue = {
  focusCampaignId: string | null;
  onFocusCampaignHandled: () => void;
};

const CampaignFocusContext = createContext<CampaignFocusContextValue | null>(
  null
);

export function useCampaignFocusFromDeepLink(): CampaignFocusContextValue {
  const ctx = useContext(CampaignFocusContext);
  return (
    ctx ?? {
      focusCampaignId: null,
      onFocusCampaignHandled: () => {}
    }
  );
}

/**
 * Reads `?campaign_id=` for list scroll/highlight (does not open the monitor modal).
 */
export function CampaignDeepLink({ children }: { children: ReactNode }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const focusCampaignId = useMemo(() => {
    const id = (searchParams.get('campaign_id') ?? '').trim();
    return id || null;
  }, [searchParams]);

  const onFocusCampaignHandled = useCallback(() => {
    if (focusCampaignId) router.replace(ROUTES.CAMPAIGNS.ROOT);
  }, [focusCampaignId, router]);

  const value = useMemo(
    () => ({ focusCampaignId, onFocusCampaignHandled }),
    [focusCampaignId, onFocusCampaignHandled]
  );

  return (
    <CampaignFocusContext.Provider value={value}>
      {children}
    </CampaignFocusContext.Provider>
  );
}
