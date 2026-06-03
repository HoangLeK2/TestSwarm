/** DOM id for scroll/highlight when deep-linking to a campaign row. */
export function campaignRowAnchorId(campaignId: string): string {
  return `campaign-row-${campaignId}`;
}

export const campaignRowHighlightClass =
  'bg-primary/10 ring-2 ring-inset ring-primary/50 transition-colors duration-500';
