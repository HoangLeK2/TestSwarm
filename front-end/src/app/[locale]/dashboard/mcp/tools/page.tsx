import { redirect } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';

type PageProps = {
  params: Promise<{ locale: string }>;
};

export default async function LegacyMcpToolsRedirectPage({ params }: PageProps) {
  const { locale } = await params;
  redirect({ href: ROUTES.MCP.ROOT, locale });
}
