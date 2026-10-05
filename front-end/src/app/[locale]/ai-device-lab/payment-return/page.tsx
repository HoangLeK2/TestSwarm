import { PaymentReturnStatus } from '@/features/ai-device-lab/components/payment-return-status';

export default async function AiDeviceLabPaymentReturnPage({
  params,
  searchParams
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ campaign_id?: string }>;
}) {
  const [{ locale }, query] = await Promise.all([params, searchParams]);
  return (
    <PaymentReturnStatus
      campaignId={query.campaign_id?.trim() || null}
      locale={locale === 'en' ? 'en' : 'vi'}
    />
  );
}
