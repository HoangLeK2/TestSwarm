#!/usr/bin/env node

import process from 'node:process';

const cdpBaseUrl =
  process.env.DEVICE_FARM_PROBE_CDP_URL ?? 'http://127.0.0.1:9222';
const dashboardUrl =
  process.env.DEVICE_FARM_PROBE_URL ??
  'http://127.0.0.1:3000/vi/dashboard/device-farm';
const apiBaseUrl =
  process.env.DEVICE_FARM_PROBE_API_BASE_URL ?? 'http://localhost:8081';
const probeDurationMs = Number(
  process.env.DEVICE_FARM_MEDIA_WS_PROBE_DURATION_MS ?? 10_000
);
const expectMediaWsMin = Number(
  process.env.DEVICE_FARM_PROBE_EXPECT_MEDIA_WS_MIN ?? 1
);
const expectBinaryMin = Number(
  process.env.DEVICE_FARM_PROBE_EXPECT_BINARY_MIN ?? 0
);
const email = process.env.DEVICE_FARM_PROBE_EMAIL ?? '';
const password = process.env.DEVICE_FARM_PROBE_PASSWORD ?? '';

let nextCommandId = 0;
const pendingCommands = new Map();
const eventListeners = new Map();

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function on(method, listener) {
  const listeners = eventListeners.get(method) ?? new Set();
  listeners.add(listener);
  eventListeners.set(method, listeners);
  return () => listeners.delete(listener);
}

async function getPageTarget() {
  const targets = await fetch(`${cdpBaseUrl}/json/list`).then((response) =>
    response.json()
  );
  const page = targets.find((target) => target.type === 'page');
  if (!page?.webSocketDebuggerUrl) {
    throw new Error('No debuggable Chrome page target found');
  }
  return page;
}

function createCdpClient(webSocketDebuggerUrl) {
  const socket = new WebSocket(webSocketDebuggerUrl);

  socket.addEventListener('message', (event) => {
    const message = JSON.parse(String(event.data));
    if (message.id) {
      const pending = pendingCommands.get(message.id);
      if (!pending) return;
      pendingCommands.delete(message.id);
      if (message.error) {
        pending.reject(new Error(message.error.message));
      } else {
        pending.resolve(message.result);
      }
      return;
    }

    for (const listener of eventListeners.get(message.method) ?? []) {
      listener(message.params);
    }
  });

  const opened = new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener(
      'error',
      () => reject(new Error('Unable to connect to Chrome DevTools')),
      { once: true }
    );
  });

  return {
    async send(method, params = {}) {
      await opened;
      const id = ++nextCommandId;
      const result = new Promise((resolve, reject) => {
        pendingCommands.set(id, { resolve, reject });
      });
      socket.send(JSON.stringify({ id, method, params }));
      return result;
    },
    close() {
      socket.close();
    }
  };
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text);
  }
  return result.result.value;
}

async function waitFor(client, expression, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await evaluate(client, expression)) return;
    await wait(100);
  }
  throw new Error(`Timed out waiting for: ${expression}`);
}

async function navigate(client, url) {
  const loaded = new Promise((resolve) => {
    const off = on('Page.loadEventFired', () => {
      off();
      resolve();
    });
  });
  await client.send('Page.navigate', { url });
  await Promise.race([loaded, wait(15_000)]);
}

function buildApiUrl(path) {
  const normalizedBase = apiBaseUrl.replace(/\/+$/, '');
  const apiBase = normalizedBase.endsWith('/api')
    ? normalizedBase
    : `${normalizedBase}/api`;
  return `${apiBase}${path}`;
}

async function seedAuthIfConfigured(client) {
  if (!email || !password) return false;

  const loginResponse = await fetch(buildApiUrl('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
  if (!loginResponse.ok) {
    throw new Error(
      `Auth seed failed: POST /auth/login returned ${loginResponse.status}`
    );
  }

  const tokenData = await loginResponse.json();
  const accessToken = String(tokenData.access_token ?? '');
  const refreshToken = String(tokenData.refresh_token ?? '');
  if (!accessToken || !refreshToken) {
    throw new Error('Auth seed failed: login response did not include tokens');
  }

  let user = null;
  const meResponse = await fetch(buildApiUrl('/auth/me'), {
    headers: { Authorization: `Bearer ${accessToken}` }
  });
  if (meResponse.ok) {
    user = await meResponse.json();
  }

  const expiresAt =
    Date.now() + Number(tokenData.expires_in ?? 3600) * 1000;
  await evaluate(
    client,
    `(() => {
      localStorage.setItem('auth_token', ${JSON.stringify(accessToken)});
      localStorage.setItem('refresh_token', ${JSON.stringify(refreshToken)});
      localStorage.setItem('token_expires', ${JSON.stringify(String(expiresAt))});
      if (${JSON.stringify(user)} !== null) {
        localStorage.setItem('user', ${JSON.stringify(JSON.stringify(user))});
      }
      document.cookie =
        'auth_token=' +
        encodeURIComponent(${JSON.stringify(accessToken)}) +
        '; path=/; max-age=' +
        String(30 * 24 * 60 * 60) +
        '; samesite=strict';
      return true;
    })()`
  );
  return true;
}

async function signInIfNeeded(client) {
  let loginState = null;
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    loginState = await evaluate(
      client,
      `({
        url: location.href,
        isDashboard: location.pathname.includes('/dashboard/device-farm'),
        hasPassword: Boolean(document.querySelector('input[type="password"]')),
        hasEmail: Boolean(document.querySelector('input[type="email"], input[name="email"], input[autocomplete="username"], input[type="text"]'))
      })`
    );
    if (loginState.isDashboard) return false;
    if (loginState.hasPassword) break;
    await wait(100);
  }
  if (!loginState?.hasPassword) return false;
  if (!email || !password) {
    throw new Error(
      `Authentication required at ${loginState.url}; set DEVICE_FARM_PROBE_EMAIL and DEVICE_FARM_PROBE_PASSWORD`
    );
  }

  await evaluate(
    client,
    `(() => {
      const setValue = (input, value) => {
        const setter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          'value'
        ).set;
        setter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      };
      const emailInput = document.querySelector(
        'input[type="email"], input[name="email"], input[autocomplete="username"], input[type="text"]'
      );
      const passwordInput = document.querySelector('input[type="password"]');
      if (!emailInput || !passwordInput) return false;
      setValue(emailInput, ${JSON.stringify(email)});
      setValue(passwordInput, ${JSON.stringify(password)});
      const form = passwordInput.closest('form');
      const submit = form?.querySelector(
        'button[type="submit"], input[type="submit"]'
      );
      if (submit) submit.click();
      else form?.requestSubmit();
      return true;
    })()`
  );
  await waitFor(
    client,
    `location.pathname.includes('/dashboard/device-farm')`,
    15_000
  );
  return true;
}

async function installWsProbe(client) {
  await client.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      (() => {
        const NativeWebSocket = window.WebSocket;
        const probe = {
          createdAt: performance.now(),
          nextId: 0,
          sockets: [],
          sent: [],
          received: [],
          timeline: {
            probeInstalledAtMs: 0,
            domContentLoadedAtMs: null,
            windowLoadAtMs: null,
            firstWsCreatedAtMs: null,
            firstRelayWsOpenAtMs: null,
            firstMediaWsOpenAtMs: null,
            firstWatchSerialSentAtMs: null,
            firstRequestIdrSentAtMs: null,
            firstBinaryAtMs: null,
            firstVisibleCanvasAtMs: null
          }
        };
        const mark = (key, now = performance.now()) => {
          if (probe.timeline[key] === null) {
            probe.timeline[key] = Math.round(now - probe.createdAt);
          }
        };
        const isRelayWsUrl = (rawUrl) => {
          try {
            return new URL(String(rawUrl), location.href).pathname === '/ws';
          } catch {
            return false;
          }
        };
        const isCanvasVisible = () =>
          [...document.querySelectorAll('canvas')].some((canvas) => {
            const rect = canvas.getBoundingClientRect();
            const style = getComputedStyle(canvas);
            return (
              rect.bottom > 0 &&
              rect.right > 0 &&
              rect.top < innerHeight &&
              rect.left < innerWidth &&
              style.display !== 'none' &&
              style.visibility !== 'hidden'
            );
          });
        if (document.readyState === 'loading') {
          document.addEventListener(
            'DOMContentLoaded',
            () => mark('domContentLoadedAtMs'),
            { once: true }
          );
        } else {
          mark('domContentLoadedAtMs');
        }
        if (document.readyState === 'complete') {
          mark('windowLoadAtMs');
        } else {
          window.addEventListener('load', () => mark('windowLoadAtMs'), {
            once: true
          });
        }
        const visibleCanvasTimer = window.setInterval(() => {
          if (!isCanvasVisible()) return;
          mark('firstVisibleCanvasAtMs');
          window.clearInterval(visibleCanvasTimer);
        }, 50);
        function recordSocket(socket, url) {
          const id = ++probe.nextId;
          mark('firstWsCreatedAtMs');
          const entry = {
            id,
            url: String(url),
            openedAt: performance.now(),
            openAt: null,
            closeAt: null,
            sentText: 0,
            sentWatchSerial: [],
            sentUnwatchSerial: [],
            sentRequestIdr: [],
            receivedText: 0,
            receivedBinary: 0,
            firstBinaryMs: null,
            lastBinaryMs: null
          };
          probe.sockets.push(entry);
          socket.addEventListener('open', () => {
            entry.openAt = performance.now();
            if (isRelayWsUrl(url)) {
              mark('firstRelayWsOpenAtMs', entry.openAt);
            }
          });
          socket.addEventListener('close', () => {
            entry.closeAt = performance.now();
          });
          socket.addEventListener('message', (event) => {
            if (typeof event.data === 'string') {
              entry.receivedText += 1;
              return;
            }
            entry.receivedBinary += 1;
            const now = performance.now();
            if (entry.firstBinaryMs === null) {
              entry.firstBinaryMs = now - probe.createdAt;
            }
            mark('firstBinaryAtMs', now);
            entry.lastBinaryMs = now - probe.createdAt;
          });
          const originalSend = socket.send.bind(socket);
          socket.send = (data) => {
            if (typeof data === 'string') {
              entry.sentText += 1;
              try {
                const parsed = JSON.parse(data);
                if (parsed?.type === 'watch_serial') {
                  entry.sentWatchSerial.push(String(parsed.serial ?? ''));
                  mark('firstWatchSerialSentAtMs');
                  if (entry.openAt !== null) {
                    mark('firstMediaWsOpenAtMs', entry.openAt);
                  }
                } else if (parsed?.type === 'unwatch_serial') {
                  entry.sentUnwatchSerial.push(String(parsed.serial ?? ''));
                } else if (parsed?.type === 'request_idr') {
                  entry.sentRequestIdr.push(String(parsed.serial ?? ''));
                  mark('firstRequestIdrSentAtMs');
                }
              } catch {
                // ignore non-json text frames
              }
            }
            return originalSend(data);
          };
          return socket;
        }
        function ProbedWebSocket(url, protocols) {
          const socket =
            protocols === undefined
              ? new NativeWebSocket(url)
              : new NativeWebSocket(url, protocols);
          return recordSocket(socket, url);
        }
        ProbedWebSocket.prototype = NativeWebSocket.prototype;
        Object.assign(ProbedWebSocket, NativeWebSocket);
        Object.defineProperty(window, 'WebSocket', {
          configurable: true,
          writable: true,
          value: ProbedWebSocket
        });
        window.__deviceFarmMediaWsProbe = probe;
      })();
    `
  });
}

async function collectProbeState(client) {
  return evaluate(
    client,
    `(async () => {
      const truncate = (values, limit = 5) => ({
        values: [...values].slice(0, limit),
        truncated: Math.max(0, values.length - limit)
      });
      const sanitizeUrl = (raw) => {
        try {
          const url = new URL(String(raw));
          if (url.searchParams.has('token')) {
            url.searchParams.set('token', '[redacted]');
          }
          return url.toString();
        } catch {
          return String(raw).replace(/([?&]token=)[^&]+/g, '$1[redacted]');
        }
      };
      const probe = window.__deviceFarmMediaWsProbe;
      const sockets = probe?.sockets ?? [];
      const timeline = probe?.timeline ?? null;
      const timelineDelta = (startKey, endKey) => {
        if (!timeline) return null;
        const start = timeline[startKey];
        const end = timeline[endKey];
        return typeof start === 'number' && typeof end === 'number'
          ? end - start
          : null;
      };
      let relayStatus = null;
      let relayStatusError = null;
      const relaySocket = sockets.find((socket) => {
        try {
          return new URL(socket.url).pathname === '/ws';
        } catch {
          return false;
        }
      });
      if (relaySocket) {
        try {
          const socketUrl = new URL(relaySocket.url);
          const relayOrigin = socketUrl.origin.replace(/^ws/, 'http');
          const token = localStorage.getItem('auth_token') || '';
          const response = await fetch(relayOrigin + '/api/relay/status', {
            headers: token ? { Authorization: 'Bearer ' + token } : {}
          });
          const json = await response.json();
          const wsStreams = json?.websocket_streams ?? null;
          const telemetry = json?.stream_telemetry ?? null;
          relayStatus = {
            httpStatus: response.status,
            streamGuardrail: json?.stream_guardrail ?? null,
            websocketStreams: wsStreams
              ? {
                  connections: wsStreams.connections,
                  media_ws_active: wsStreams.media_ws_active,
                  media_streams_active: wsStreams.media_streams_active,
                  max_media_streams_per_connection:
                    wsStreams.max_media_streams_per_connection,
                  shared_media_ws_connections:
                    wsStreams.shared_media_ws_connections,
                  dedicated_media_ws_ok: wsStreams.dedicated_media_ws_ok,
                  sender_started_total: wsStreams.sender_started_total,
                  sender_stopped_total: wsStreams.sender_stopped_total,
                  sender_sent_total: wsStreams.sender_sent_total,
                  sender_dropped_total: wsStreams.sender_dropped_total,
                  top_dropped_serials: wsStreams.top_dropped_serials ?? []
                }
              : null,
            streamTelemetry: telemetry
              ? {
                  ws_sent: telemetry.ws_sent,
                  ws_dropped: telemetry.ws_dropped,
                  ws_send_wait_p95_ms: telemetry.ws_send_wait_p95_ms,
                  ws_send_p95_ms: telemetry.ws_send_p95_ms,
                  fanout_frames: telemetry.fanout_frames,
                  fanout_no_subscriber: telemetry.fanout_no_subscriber,
                  grpc_video_frames: telemetry.grpc_video_frames
                }
              : null
          };
        } catch (error) {
          relayStatusError = String(error?.message ?? error);
        }
      }
      const mediaSockets = sockets.filter((socket) => socket.sentWatchSerial.length > 0);
      const receivedBinaryTotal = mediaSockets.reduce(
        (total, socket) => total + socket.receivedBinary,
        0
      );
      const mediaSocketSummaries = mediaSockets.map((socket) => {
        const uniqueWatchSerials = [...new Set(socket.sentWatchSerial)];
        return {
          id: socket.id,
          url: sanitizeUrl(socket.url),
          openAtMs: socket.openAt === null ? null : Math.round(socket.openAt - probe.createdAt),
          closeAtMs: socket.closeAt === null ? null : Math.round(socket.closeAt - probe.createdAt),
          uniqueWatchSerialCount: uniqueWatchSerials.length,
          watchSerials: truncate(uniqueWatchSerials),
          requestIdrSerials: truncate([...new Set(socket.sentRequestIdr)]),
          receivedBinary: socket.receivedBinary,
          firstBinaryMs: socket.firstBinaryMs === null ? null : Math.round(socket.firstBinaryMs),
          lastBinaryMs: socket.lastBinaryMs === null ? null : Math.round(socket.lastBinaryMs)
        };
      });
      const maxWatchSerialsPerSocket = Math.max(
        0,
        ...mediaSocketSummaries.map((socket) => socket.uniqueWatchSerialCount)
      );
      const canvases = [...document.querySelectorAll('canvas')].map((canvas) => {
        const rect = canvas.getBoundingClientRect();
        return {
          width: canvas.width,
          height: canvas.height,
          cssWidth: Math.round(rect.width),
          cssHeight: Math.round(rect.height),
          visible:
            rect.bottom > 0 &&
            rect.right > 0 &&
            rect.top < innerHeight &&
            rect.left < innerWidth &&
            getComputedStyle(canvas).display !== 'none' &&
            getComputedStyle(canvas).visibility !== 'hidden'
        };
      });
      return {
        url: location.href,
        durationMs: probe ? Math.round(performance.now() - probe.createdAt) : null,
        sockets: sockets.map((socket) => ({
          id: socket.id,
          url: sanitizeUrl(socket.url),
          openAtMs: socket.openAt === null ? null : Math.round(socket.openAt - probe.createdAt),
          closeAtMs: socket.closeAt === null ? null : Math.round(socket.closeAt - probe.createdAt),
          sentText: socket.sentText,
          watchSerials: socket.sentWatchSerial,
          requestIdrSerials: socket.sentRequestIdr,
          receivedText: socket.receivedText,
          receivedBinary: socket.receivedBinary,
          firstBinaryMs: socket.firstBinaryMs === null ? null : Math.round(socket.firstBinaryMs),
          lastBinaryMs: socket.lastBinaryMs === null ? null : Math.round(socket.lastBinaryMs)
        })),
        summary: {
          dedicatedMediaWsOk: mediaSockets.length === 0 || maxWatchSerialsPerSocket <= 1,
          mediaSocketCount: mediaSockets.length,
          sharedMediaSocketCount: mediaSocketSummaries.filter((socket) => socket.uniqueWatchSerialCount > 1).length,
          maxWatchSerialsPerSocket,
          visibleCanvasCount: canvases.filter((canvas) => canvas.visible).length,
          receivedBinaryTotal,
          timeline,
          derivedLatency: {
            installToRelayWsOpenMs: timeline?.firstRelayWsOpenAtMs ?? null,
            installToMediaWsOpenMs: timeline?.firstMediaWsOpenAtMs ?? null,
            mediaWsOpenToWatchSerialMs: timelineDelta(
              'firstMediaWsOpenAtMs',
              'firstWatchSerialSentAtMs'
            ),
            watchSerialToFirstBinaryMs: timelineDelta(
              'firstWatchSerialSentAtMs',
              'firstBinaryAtMs'
            ),
            mediaWsOpenToFirstBinaryMs: timelineDelta(
              'firstMediaWsOpenAtMs',
              'firstBinaryAtMs'
            ),
            firstBinaryToVisibleCanvasMs: timelineDelta(
              'firstBinaryAtMs',
              'firstVisibleCanvasAtMs'
            ),
            installToVisibleCanvasMs: timeline?.firstVisibleCanvasAtMs ?? null
          },
          mediaSocketSummaries
        },
        mediaSocketCount: mediaSockets.length,
        maxWatchSerialsPerSocket,
        visibleCanvasCount: canvases.filter((canvas) => canvas.visible).length,
        relayStatus,
        relayStatusError,
        canvases
      };
    })()`
  );
}

async function run() {
  const pageTarget = await getPageTarget();
  const client = createCdpClient(pageTarget.webSocketDebuggerUrl);
  try {
    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await installWsProbe(client);
    await navigate(client, dashboardUrl);
    const seededAuth = await seedAuthIfConfigured(client);
    if (seededAuth) {
      await navigate(client, dashboardUrl);
      await waitFor(
        client,
        `location.pathname.includes('/dashboard/device-farm')`,
        15_000
      );
    } else {
      await signInIfNeeded(client);
    }
    await wait(probeDurationMs);
    const state = await collectProbeState(client);
    console.log(JSON.stringify(state, null, 2));

    if (state.mediaSocketCount < expectMediaWsMin) {
      throw new Error(
        `Expected at least ${expectMediaWsMin} media WS, got ${state.mediaSocketCount}`
      );
    }
    if (state.maxWatchSerialsPerSocket > 1) {
      throw new Error(
        `Expected isolated media sockets, max watch_serials per socket=${state.maxWatchSerialsPerSocket}`
      );
    }
    if (state.summary.receivedBinaryTotal < expectBinaryMin) {
      throw new Error(
        `Expected at least ${expectBinaryMin} binary media frames, got ${state.summary.receivedBinaryTotal}`
      );
    }
  } finally {
    client.close();
  }
}

run().catch((error) => {
  console.error(error?.stack ?? String(error));
  process.exitCode = 1;
});
