import { ROUTES } from '@/config/routes';
import { redirect } from '@/i18n/navigation';

export default async function VerifyEmailPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  redirect({ href: ROUTES.DEVICES.ROOT, locale });
}
