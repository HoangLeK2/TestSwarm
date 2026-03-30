'use client';

import { DeviceGroupList } from '@/features/device-groups/components/device-group-list';

export default function DeviceGroupsPage() {
  return (
    <div className='container max-w-6xl py-6'>
      <DeviceGroupList />
    </div>
  );
}
