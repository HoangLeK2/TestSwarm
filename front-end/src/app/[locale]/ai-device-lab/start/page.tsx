import { CampaignDraftForm } from '@/features/ai-device-lab/components/campaign-draft-form';

export default async function AiDeviceLabStartPage({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  return <CampaignDraftForm locale={locale === 'en' ? 'en' : 'vi'} />;
}
