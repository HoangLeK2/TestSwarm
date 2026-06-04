import { redirect } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';

type PageProps = {
  params: Promise<{ locale: string }>;
};

export default async function LegacyMcpAuditRedirectPage({
  params
}: PageProps) {
  const { locale } = await params;
  redirect({ href: ROUTES.MCP.AUDIT, locale });
}
