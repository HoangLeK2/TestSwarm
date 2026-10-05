import { CampaignWorkspace } from '@/features/ai-device-lab/components/campaign-workspace';

export default async function AiDeviceLabWorkspacePage({
  params
}: {
  params: Promise<{ locale: string; campaignId: string }>;
}) {
  const { locale, campaignId } = await params;
  return (
    <CampaignWorkspace
      campaignId={campaignId}
      locale={locale === 'en' ? 'en' : 'vi'}
    />
  );
}
