import type { NextRequest } from 'next/server';
import { proxyDeviceFarm } from '../../../_device-farm/proxy';

export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id } = await ctx.params;
  return proxyDeviceFarm(req, `/api/devices/pair/${encodeURIComponent(id)}`);
}
