'use client';

import { useSearchParams } from 'next/navigation';
import { ControlRecordView } from '@/features/devices/components/control-record-view';

export default function DeviceControlRecordPage() {
  const searchParams = useSearchParams();
  const serial = searchParams.get('serial') ?? undefined;

  return (
    <div className='mx-auto max-w-6xl space-y-4 px-4 py-4'>
      <h1 className='text-xl font-semibold'>Điều khiển & ghi kịch bản</h1>
      <ControlRecordView initialSerial={serial} />
    </div>
  );
}
