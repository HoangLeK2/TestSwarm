import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';
import axios from 'axios';

function joinUrl(base: string, path: string) {
  const b = base.endsWith('/') ? base.slice(0, -1) : base;
  const p = path.startsWith('/') ? path : `/${path}`;
  return `${b}${p}`;
}

export function getDeviceFarmBackendBaseUrl() {
  return (
    process.env.DEVICE_FARM_BACKEND_URL ||
    process.env.NEXT_PUBLIC_DEVICE_FARM_BACKEND_URL ||
    'http://localhost:8081'
  );
}

export async function proxyDeviceFarm(req: NextRequest, upstreamPath: string) {
  const base = getDeviceFarmBackendBaseUrl();
  const upstreamUrl = joinUrl(base, upstreamPath) + req.nextUrl.search;

  const headers = new Headers(req.headers);
  headers.delete('host');
  headers.delete('connection');
  headers.delete('upgrade');
  headers.delete('content-length');

  const body =
    req.method === 'GET' || req.method === 'HEAD'
      ? undefined
      : await req.text();

  const upstream = await axios.request({
    url: upstreamUrl,
    method: req.method,
    headers: Object.fromEntries(headers),
    data: body,
    // Always pass through status codes, don't throw on 4xx/5xx
    validateStatus: () => true
  });

  const resHeaders = new Headers(upstream.headers as any);
  // Next will manage compression itself
  resHeaders.delete('content-encoding');

  return new NextResponse(upstream.data, {
    status: upstream.status,
    headers: resHeaders
  });
}
