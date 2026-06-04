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

  const upstream = await axios.request<ArrayBuffer>({
    url: upstreamUrl,
    method: req.method,
    headers: Object.fromEntries(headers),
    data: body,
    // Pass through raw bytes; axios default JSON parse + NextResponse(object)
    // coerces to the literal string "[object Object]".
    responseType: 'arraybuffer',
    // Always pass through status codes, don't throw on 4xx/5xx
    validateStatus: () => true
  });

  const resHeaders = new Headers();
  for (const [key, value] of Object.entries(upstream.headers)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const v of value) resHeaders.append(key, v);
    } else {
      resHeaders.set(key, String(value));
    }
  }
  // Next will manage compression itself
  resHeaders.delete('content-encoding');

  return new NextResponse(upstream.data, {
    status: upstream.status,
    headers: resHeaders
  });
}
