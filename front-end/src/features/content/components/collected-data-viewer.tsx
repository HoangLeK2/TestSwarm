'use client';

import { ContentViewer } from './content-viewer';

export function CollectedDataViewer({
  defaultCampaignId,
  defaultExecutionId,
  defaultContentHash
}: {
  defaultCampaignId?: string;
  defaultExecutionId?: string;
  defaultContentHash?: string;
}) {
  return (
    <ContentViewer
      defaultCampaignId={defaultCampaignId}
      defaultExecutionId={defaultExecutionId}
      defaultContentHash={defaultContentHash}
    />
  );
}
