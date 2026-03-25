import type { NextRequest } from 'next/server';
import { proxyDeviceFarm } from '../../../_device-farm/proxy';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  return proxyDeviceFarm(req, '/api/devices/pair/bulk');
}
