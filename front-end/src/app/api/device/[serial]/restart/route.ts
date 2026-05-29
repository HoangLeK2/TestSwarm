import type { NextRequest } from 'next/server';
import { proxyDeviceFarm } from '../../../_device-farm/proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ serial: string }> }
) {
  const { serial } = await ctx.params;
  return proxyDeviceFarm(
    req,
    `/api/device/${encodeURIComponent(serial)}/restart`
  );
}
