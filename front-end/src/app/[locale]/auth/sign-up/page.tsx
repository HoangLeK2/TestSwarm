import { ROUTES } from '@/config/routes';
import { redirect } from '@/i18n/navigation';

export default async function SignUpPage({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  redirect({ href: ROUTES.AUTH.SIGN_IN, locale });
}
