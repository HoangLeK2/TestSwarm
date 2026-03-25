import type { NextRequest } from 'next/server';
import { proxyDeviceFarm } from '../../../_device-farm/proxy';

export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest, { params }: { params: { id: string } }) {
  return proxyDeviceFarm(req, `/api/devices/pair/${params.id}`);
}
