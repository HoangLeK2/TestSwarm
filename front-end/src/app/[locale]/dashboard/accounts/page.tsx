'use client';

import { AccountList } from '@/features/accounts/components/account-list';

export default function AccountsPage() {
  return (
    <div className='container max-w-6xl py-6'>
      <AccountList />
    </div>
  );
}
