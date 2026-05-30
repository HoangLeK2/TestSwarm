import type { Metadata } from 'next';
import { getTranslations } from 'next-intl/server';

export async function generateMetadata({
  params
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({
    locale,
    namespace: 'organization.memberManagement'
  });
  return {
    title: `${t('title')} | Device Farm`,
    description: t('description')
  };
}

export default function OrganizationMembersLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return children;
}
