import { AiDeviceLabPrototype } from '@/features/ai-device-lab-prototype/ai-device-lab-prototype';

export default async function AiDeviceLabPage({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  return <AiDeviceLabPrototype locale={locale === 'en' ? 'en' : 'vi'} />;
}
