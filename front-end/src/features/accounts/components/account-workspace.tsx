import { useTranslations } from 'next-intl';
import { AccountList } from './account-list';

export function AccountWorkspace() {
  const t = useTranslations('accountsFeature.workspace');

  return (
    <div className='space-y-6'>
      <div className='space-y-1'>
        <h1 className='text-2xl font-semibold tracking-tight'>{t('title')}</h1>
        <p className='text-sm text-muted-foreground'>{t('description')}</p>
      </div>
      <AccountList />
    </div>
  );
}
