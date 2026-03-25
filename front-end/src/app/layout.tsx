import { cookies } from 'next/headers';
import { Inter } from 'next/font/google';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter'
});

export default async function RootLayout({
  children,
  params
}: {
  children: React.ReactNode;
  params?: Promise<Record<string, unknown>>;
}) {
  const resolvedParams = (params ? await params : {}) as { locale?: string };
  const locale = resolvedParams.locale ?? 'vi';
  const cookieStore = await cookies();
  const activeTheme = cookieStore.get('active_theme')?.value || 'blue';

  return (
    <html lang={locale} suppressHydrationWarning>
      <body
        className={`${inter.className} theme-${activeTheme}`}
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
