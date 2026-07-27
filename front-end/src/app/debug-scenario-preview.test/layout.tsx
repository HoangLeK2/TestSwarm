import { NextIntlClientProvider } from 'next-intl';
import messages from '../../../messages/vi.json';
import '../[locale]/globals.css';
import '../[locale]/theme.css';

export default function DebugScenarioPreviewLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <NextIntlClientProvider locale='vi' messages={messages}>
      {children}
    </NextIntlClientProvider>
  );
}
