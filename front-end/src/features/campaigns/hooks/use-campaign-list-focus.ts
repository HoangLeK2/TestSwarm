'use client';

import { useEffect, useRef, useState } from 'react';
import { campaignRowAnchorId } from '../lib/campaign-row-anchor';

const HIGHLIGHT_MS = 4500;

/**
 * Scroll to and briefly highlight a campaign row when `focusCampaignId` is set (deep link).
 */
export function useCampaignListFocus(
  focusCampaignId: string | null,
  campaigns: { id: string }[] | undefined,
  onHandled?: () => void
) {
  const [highlightCampaignId, setHighlightCampaignId] = useState<string | null>(
    null
  );
  const handledRef = useRef(false);

  useEffect(() => {
    if (!focusCampaignId) {
      handledRef.current = false;
      return;
    }
    if (!campaigns?.length || handledRef.current) return;

    const exists = campaigns.some((c) => c.id === focusCampaignId);
    if (!exists) {
      handledRef.current = true;
      onHandled?.();
      return;
    }

    let highlightTimer: ReturnType<typeof setTimeout> | undefined;

    const run = () => {
      const el = document.getElementById(campaignRowAnchorId(focusCampaignId));
      if (!el) return false;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      handledRef.current = true;
      setHighlightCampaignId(focusCampaignId);
      onHandled?.();
      highlightTimer = setTimeout(
        () => setHighlightCampaignId(null),
        HIGHLIGHT_MS
      );
      return true;
    };

    if (run()) {
      return () => {
        if (highlightTimer) clearTimeout(highlightTimer);
      };
    }

    const retry = window.setTimeout(() => {
      if (!handledRef.current) run();
    }, 120);

    return () => {
      window.clearTimeout(retry);
      if (highlightTimer) clearTimeout(highlightTimer);
    };
  }, [focusCampaignId, campaigns, onHandled]);

  return highlightCampaignId;
}
