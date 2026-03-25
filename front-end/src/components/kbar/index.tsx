'use client';

import { KBarProvider } from 'kbar';
import { quickActions } from '../layout/app-sidebar';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';

export default function KBar({ children }: { children: React.ReactNode }) {
  const t = useTranslations('navigation');
  const router = useRouter();
  return (
    <KBarProvider
      actions={quickActions(t).map((item) => ({
        id: item.label,
        name: item.label,
        // shortcut: item.shortcut,
        perform: () => {
          router.push(item.link);
        }
      }))}
    >
      {children}
    </KBarProvider>
  );
}
