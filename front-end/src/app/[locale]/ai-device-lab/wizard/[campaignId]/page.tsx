import { ProductionWizard } from '@/features/ai-device-lab/components/production-wizard';

export default async function AiDeviceLabWizardPage({
  params
}: {
  params: Promise<{ locale: string; campaignId: string }>;
}) {
  const { locale, campaignId } = await params;
  return (
    <ProductionWizard
      campaignId={campaignId}
      locale={locale === 'en' ? 'en' : 'vi'}
    />
  );
}
