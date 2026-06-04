/**
 * Axios instance cho Device Farm backend API.
 * Tự động gắn JWT Bearer token và tự refresh khi hết hạn.
 */
import axios, { type AxiosRequestConfig } from 'axios';
import { tokenStorage } from './token-storage';

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `req-${Date.now().toString(36)}`;
}

/** Must match `OrganizationProvider` storage key. */
const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';

/** Origin of the Device Farm HTTP API (no `/api` suffix). */
function resolveDeviceFarmBackendBase(): string {
  const configured = (
    process.env.NEXT_PUBLIC_PRODUCT_API_URL || 'http://localhost:8081'
  ).replace(/\/+$/, '');

  if (typeof window === 'undefined') {
    return configured;
  }

  try {
    const configuredUrl = new URL(configured);
    const pageOrigin = window.location.origin.replace(/\/+$/, '');
    const pageHost = new URL(pageOrigin).host;
    if (configuredUrl.host === pageHost) {
      return configured;
    }

    const isDev =
      (process.env.NEXT_PUBLIC_ENVIRONMENT || '').trim().toLowerCase() ===
      'dev';
    const pointsAtNextDevServer =
      configuredUrl.port === '3000' ||
      configuredUrl.hostname === 'localhost' ||
      configuredUrl.hostname === '127.0.0.1';

    // `next.config` rewrites `/api/*` → DEVICE_FARM_BACKEND_URL on the Next host.
    // Use the tab origin when env still says localhost:3000 but the user opened via LAN IP.
    if (isDev || pointsAtNextDevServer) {
      return pageOrigin;
    }
  } catch {
    // keep configured
  }
  return configured;
}

export const deviceFarmBackendBase = resolveDeviceFarmBackendBase();
const backendBase = deviceFarmBackendBase;
const API_BASE_URL = `${backendBase}/api`;

/**
 * Base URL the *phone* must reach for `/device-agent` WS (QR pairing).
 *
 * Resolution priority:
 *   1. Host/port parsed from NEXT_PUBLIC_DEVICE_FARM_WS_URL — already pinned
 *      to the deploy LAN IP (or public domain) by operators, and the phone
 *      needs to reach the same backend. Ignored if that env points at
 *      localhost/127.0.0.1 (useless to the phone).
 *   2. Browser tab hostname + API port (e.g. opening the dashboard as
 *      http://192.168.x.x:3000 yields ws://192.168.x.x:8081/...).
 *   3. NEXT_PUBLIC_PRODUCT_API_URL as-is.
 */
function getDeviceBackendBase(): string {
  let api: URL;
  try {
    api = new URL(deviceFarmBackendBase);
  } catch {
    return backendBase.replace(/\/+$/, '');
  }
  const scheme = api.protocol;
  const port = api.port || (api.protocol === 'https:' ? '443' : '80');
  const portPart =
    (scheme === 'http:' && port === '80') ||
    (scheme === 'https:' && port === '443')
      ? ''
      : `:${port}`;

  // Reuse the already-configured farm WS URL so operators don't need a second
  // env var. The agent WS lives on the same host:port, just a different path.
  const farmWsRaw = (process.env.NEXT_PUBLIC_DEVICE_FARM_WS_URL || '').trim();
  if (farmWsRaw) {
    try {
      const farmUrl = new URL(
        farmWsRaw
          .replace(/^ws:\/\//i, 'http://')
          .replace(/^wss:\/\//i, 'https://')
      );
      const h = farmUrl.hostname;
      if (h && h !== 'localhost' && h !== '127.0.0.1') {
        const outScheme = farmUrl.protocol === 'https:' ? 'https:' : 'http:';
        return `${outScheme}//${farmUrl.host}`.replace(/\/+$/, '');
      }
    } catch {
      // fall through
    }
  }

  if (typeof window !== 'undefined' && window.location?.hostname) {
    const host = window.location.hostname;
    return `${scheme}//${host}${portPart}`.replace(/\/+$/, '');
  }
  return backendBase.replace(/\/+$/, '');
}

// Chỉ dùng cho các API call từ frontend (axios baseURL đã đúng). getRuntimeBase giữ cho tương thích nếu có chỗ dùng.
function getRuntimeBase(): string {
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin.replace(/\/+$/, '');
  }
  return backendBase;
}

export function getStfApkDownloadUrl(): string {
  return `${API_BASE_URL}/devices/stf-apk`;
}

/** WS origin (scheme + host[:port]) — same base used for QR / link in connect dialogs. */
export function getDeviceAgentWsBase(): string {
  return getDeviceBackendBase()
    .replace(/^http:\/\//i, 'ws://')
    .replace(/^https:\/\//i, 'wss://')
    .replace(/\/+$/, '');
}

/** WebSocket URL for device-agent (Pair device QR). */
export function getDeviceAgentWsUrl(query = ''): string {
  const suffix = query.startsWith('?') ? query : query ? `?${query}` : '';
  return `${getDeviceAgentWsBase()}/device-agent${suffix}`;
}

/** URL for connect-by-QR (ADB): app on phone POSTs its IP here after scanning QR.
 *  Uses the frontend origin (window.location.origin) so that the phone can always
 *  reach it — the same host:port the user opened the dashboard on — and Next.js
 *  proxies the request onward to the backend.
 */
export function getConnectRegisterUrl(): string {
  return `${getRuntimeBase()}/api/connect/register`;
}

export const farmApi = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' }
});

const MAX_429_RETRIES = 3;
const BASE_429_DELAY_MS = 1_000;
const MAX_429_DELAY_MS = 30_000;

type FarmApiRequestConfig = AxiosRequestConfig & {
  _retry?: boolean;
  /** Number of 429 retries already attempted for this request. */
  _429RetryCount?: number;
  /** Opt out of automatic 429 backoff (e.g. login form handles errors inline). */
  _skip429Retry?: boolean;
};

function parseRetryAfterMs(header: string | undefined): number | null {
  if (!header?.trim()) return null;
  const trimmed = header.trim();
  const seconds = Number(trimmed);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(seconds * 1000, MAX_429_DELAY_MS);
  }
  const until = Date.parse(trimmed);
  if (!Number.isNaN(until)) {
    return Math.min(Math.max(0, until - Date.now()), MAX_429_DELAY_MS);
  }
  return null;
}

function backoff429DelayMs(
  attempt: number,
  retryAfterHeader: string | undefined
): number {
  const fromHeader = parseRetryAfterMs(retryAfterHeader);
  if (fromHeader != null) return fromHeader;
  const exp = BASE_429_DELAY_MS * 2 ** attempt;
  const capped = Math.min(exp, MAX_429_DELAY_MS);
  // 75–100% jitter to avoid thundering herd on shared rate-limit windows.
  return Math.round(capped * (0.75 + Math.random() * 0.25));
}

function sleep429(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function retryAfter429(
  err: { response?: { headers?: Record<string, string | undefined> } },
  original: FarmApiRequestConfig
) {
  const attempt = original._429RetryCount ?? 0;
  if (attempt >= MAX_429_RETRIES) return null;

  original._429RetryCount = attempt + 1;
  const retryAfter =
    err.response?.headers?.['retry-after'] ??
    err.response?.headers?.['Retry-After'];
  const delay = backoff429DelayMs(attempt, retryAfter);
  await sleep429(delay);
  return farmApi(original);
}

// Attach access token and ngrok-skip header when using ngrok
farmApi.interceptors.request.use((config) => {
  config.headers = config.headers ?? {};
  if (!config.headers['X-Request-Id']) {
    config.headers['X-Request-Id'] = newRequestId();
  }
  const token = tokenStorage.getAuthToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  if (typeof window !== 'undefined') {
    const orgId = localStorage.getItem(CURRENT_ORG_STORAGE_KEY)?.trim();
    if (orgId) {
      config.headers['X-Organization-Id'] = orgId;
    }
  }
  if (backendBase.includes('ngrok')) {
    config.headers['ngrok-skip-browser-warning'] = '1';
  }
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    // Let the browser set multipart boundary (manual Content-Type breaks uploads).
    delete config.headers['Content-Type'];
  }
  return config;
});

// --- Proactive refresh (60s before expiry) ---
let _refreshTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleProactiveRefresh(expiresInSec: number | undefined) {
  if (typeof window === 'undefined') return;
  if (_refreshTimer) {
    clearTimeout(_refreshTimer);
    _refreshTimer = null;
  }
  const ttlMs = Math.max(60, Number(expiresInSec || 3600)) * 1000;
  const delay = Math.max(5_000, ttlMs - 60_000);
  _refreshTimer = setTimeout(async () => {
    const refreshToken = tokenStorage.getRefreshToken();
    if (!refreshToken) return;
    try {
      const { data } = await axios.post<{
        access_token: string;
        refresh_token: string;
        expires_in?: number;
      }>(`${API_BASE_URL}/auth/refresh`, { refresh_token: refreshToken });
      tokenStorage.setTokens({
        idToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresAt: Date.now() + (data.expires_in ?? 3600) * 1000
      });
      scheduleProactiveRefresh(data.expires_in);
    } catch {
      /* reactive interceptor handles hard failure */
    }
  }, delay);
}

export function armAuthRefreshTimer(expiresInSec?: number) {
  scheduleProactiveRefresh(expiresInSec);
}

// --- Refresh logic ---
let _isRefreshing = false;
let _waitQueue: Array<{
  resolve: (v: string) => void;
  reject: (e: unknown) => void;
}> = [];

function _processQueue(error: unknown, token: string | null) {
  _waitQueue.forEach((p) => (token ? p.resolve(token) : p.reject(error)));
  _waitQueue = [];
}

farmApi.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config as FarmApiRequestConfig | undefined;
    if (!original) return Promise.reject(err);

    if (err.response?.status === 429 && !original._skip429Retry) {
      const retried = await retryAfter429(err, original);
      if (retried) return retried;
    }

    if (err.response?.status === 401 && !original._retry) {
      const pathname =
        typeof window !== 'undefined' ? window.location.pathname : '';
      const isAuthPage =
        /\/auth\/(sign-in|sign-up|forgot-password|reset-password|verify-email)/i.test(
          pathname
        );
      if (isAuthPage) {
        return Promise.reject(err);
      }

      const refreshToken = tokenStorage.getRefreshToken();

      if (!refreshToken) {
        tokenStorage.clearTokens();
        const locale =
          pathname.split('/')[1] && /^[a-z]{2}$/i.test(pathname.split('/')[1])
            ? pathname.split('/')[1]
            : 'vi';
        window.location.href = `/${locale}/auth/sign-in`;
        return Promise.reject(err);
      }

      if (_isRefreshing) {
        return new Promise((resolve, reject) => {
          _waitQueue.push({ resolve, reject });
        }).then((token) => {
          original.headers = {
            ...original.headers,
            Authorization: `Bearer ${token}`
          };
          return farmApi(original);
        });
      }

      original._retry = true;
      _isRefreshing = true;

      try {
        const { data } = await axios.post<{
          access_token: string;
          refresh_token: string;
        }>(`${API_BASE_URL}/auth/refresh`, { refresh_token: refreshToken });
        tokenStorage.setTokens({
          idToken: data.access_token,
          refreshToken: data.refresh_token,
          expiresAt: Date.now() + (data.expires_in ?? 3600) * 1000
        });
        scheduleProactiveRefresh(data.expires_in);
        _processQueue(null, data.access_token);
        original.headers = {
          ...original.headers,
          Authorization: `Bearer ${data.access_token}`
        };
        return farmApi(original);
      } catch (refreshErr) {
        _processQueue(refreshErr, null);
        tokenStorage.clearTokens();
        const pathname =
          typeof window !== 'undefined' ? window.location.pathname : '';
        const locale =
          pathname.split('/')[1] && /^[a-z]{2}$/i.test(pathname.split('/')[1])
            ? pathname.split('/')[1]
            : 'vi';
        window.location.href = `/${locale}/auth/sign-in`;
        return Promise.reject(refreshErr);
      } finally {
        _isRefreshing = false;
      }
    }

    return Promise.reject(err);
  }
);
