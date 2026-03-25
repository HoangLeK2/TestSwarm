import type { Viewport } from 'next';
import { NextIntlClientProvider } from 'next-intl';
import { getMessages, getTranslations } from 'next-intl/server';
import ThemeProvider from '@/components/layout/ThemeToggle/theme-provider';
import './globals.css';
import './theme.css';
import Providers from '@/components/layout/providers';
import { cookies } from 'next/headers';
import React from 'react';
import KBar from '@/components/kbar';

const META_THEME_COLORS = {
  light: '#ffffff',
  dark: '#09090b'
};

export async function generateMetadata({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return {
    title: t('metadata.title'),
    description: t('metadata.description')
  };
}

export const viewport: Viewport = {
  themeColor: META_THEME_COLORS.light
};

export default async function LocaleLayout({
  children,
  params
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const messages = await getMessages();
  const cookieStore = await cookies();
  const activeTheme = cookieStore.get('active_theme')?.value || 'blue';

  return (
    <NextIntlClientProvider messages={messages} locale={locale}>
      <ThemeProvider
        attribute='class'
        defaultTheme='light'
        enableSystem
        disableTransitionOnChange
      >
        <KBar>
          <Providers activeThemeValue={activeTheme}>{children}</Providers>
        </KBar>
      </ThemeProvider>
    </NextIntlClientProvider>
  );
}
