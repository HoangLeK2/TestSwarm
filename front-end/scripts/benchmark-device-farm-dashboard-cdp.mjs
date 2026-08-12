#!/usr/bin/env node

import process from 'node:process';

const cdpBaseUrl =
  process.env.DEVICE_FARM_DASHBOARD_BENCH_CDP_URL ?? 'http://127.0.0.1:9222';
const frontendUrl =
  process.env.DEVICE_FARM_DASHBOARD_BENCH_FRONTEND_URL ??
  'http://127.0.0.1:3002';
const apiUrl =
  process.env.DEVICE_FARM_DASHBOARD_BENCH_API_URL ?? 'http://127.0.0.1:8081';
const sampleMs = Number(
  process.env.DEVICE_FARM_DASHBOARD_BENCH_SAMPLE_MS ?? 20_000
);

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readCredentials() {
  if (
    process.env.DEVICE_FARM_BENCH_EMAIL &&
    process.env.DEVICE_FARM_BENCH_PASSWORD
  ) {
    return {
      email: process.env.DEVICE_FARM_BENCH_EMAIL,
      password: process.env.DEVICE_FARM_BENCH_PASSWORD
    };
  }
  if (process.stdin.isTTY) {
    throw new Error(
      'Provide credentials via stdin JSON: {"email":"...","password":"..."}'
    );
  }
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const parsed = JSON.parse(input || '{}');
  if (!parsed.email || !parsed.password) {
    throw new Error('stdin JSON must contain email and password');
  }
  return { email: String(parsed.email), password: String(parsed.password) };
}

async function cdpJson(path) {
  const response = await fetch(`${cdpBaseUrl}${path}`);
  if (!response.ok) {
    throw new Error(`CDP HTTP ${response.status} ${path}`);
  }
  return await response.json();
}

function createCdpClient(webSocketDebuggerUrl) {
  const socket = new WebSocket(webSocketDebuggerUrl);
  let nextCommandId = 0;
  const pendingCommands = new Map();
  const events = [];

  socket.addEventListener('message', (event) => {
    const message = JSON.parse(String(event.data));
    if (message.id && pendingCommands.has(message.id)) {
      const pending = pendingCommands.get(message.id);
      pendingCommands.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
      return;
    }
    if (message.method) events.push({ t: Date.now(), ...message });
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
    events,
    async send(method, params = {}) {
      await opened;
      const id = ++nextCommandId;
      const result = new Promise((resolve, reject) => {
        pendingCommands.set(id, { resolve, reject });
      });
      socket.send(JSON.stringify({ id, method, params }));
      return await result;
    },
    close() {
      socket.close();
    }
  };
}

function redactUrl(value) {
  const text = String(value || '');
  try {
    const url = new URL(text);
    if (url.searchParams.has('token')) {
      url.searchParams.set('token', '[REDACTED]');
    }
    return url.toString();
  } catch {
    return text.replace(/([?&]token=)[^&\\s]+/g, '$1[REDACTED]');
  }
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || 'Runtime exception');
  }
  return result.result.value;
}

async function main() {
  const credentials = await readCredentials();
  const targets = await cdpJson('/json/list');
  const page = targets.find((target) => target.type === 'page');
  if (!page?.webSocketDebuggerUrl) {
    throw new Error('No debuggable Chrome page target found');
  }
  const client = createCdpClient(page.webSocketDebuggerUrl);
  try {
    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await client.send('Network.enable');
    await client.send('Page.addScriptToEvaluateOnNewDocument', {
      source: `
        window.__dfPerf = { longTasks: [], startedAt: performance.now() };
        try {
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              window.__dfPerf.longTasks.push({
                startTime: entry.startTime,
                duration: entry.duration,
                name: entry.name
              });
            }
          }).observe({ type: 'longtask', buffered: true });
        } catch (_) {}
      `
    });

    await client.send('Page.navigate', {
      url: `${frontendUrl}/vi/auth/sign-in`
    });
    await wait(1500);

    const loginResult = await evaluate(
      client,
      `(async () => {
        const login = await fetch(${JSON.stringify(`${apiUrl}/api/auth/login`)}, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(${JSON.stringify(credentials)})
        });
        if (!login.ok) return { ok: false, status: login.status };
        const data = await login.json();
        localStorage.setItem('auth_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);
        localStorage.setItem('token_expires', String(Date.now() + (data.expires_in || 3600) * 1000));
        document.cookie = 'auth_token=' + encodeURIComponent(data.access_token) + '; path=/; max-age=2592000; samesite=strict';
        const me = await fetch(${JSON.stringify(`${apiUrl}/api/auth/me`)}, {
          headers: { authorization: 'Bearer ' + data.access_token }
        });
        if (me.ok) {
          const user = await me.json();
          localStorage.setItem('user', JSON.stringify({
            id: user.id,
            email: user.email,
            givenName: user.name,
            role: user.role,
            orgRole: user.orgRole ?? null,
            defaultOrgId: user.defaultOrgId ?? null
          }));
          if (user.defaultOrgId) {
            localStorage.setItem('device-farm:current-organization-id', user.defaultOrgId);
          }
        }
        return { ok: true };
      })()`
    );
    if (!loginResult?.ok) {
      throw new Error(
        `Login failed status=${loginResult?.status ?? 'unknown'}`
      );
    }

    client.events.length = 0;
    const navStartedAt = Date.now();
    await client.send('Page.navigate', {
      url: `${frontendUrl}/vi/dashboard/device-farm`
    });
    await wait(sampleMs);

    const domStats = await evaluate(
      client,
      `(() => {
        const resources = performance.getEntriesByType('resource').map((r) => ({
          name: ${redactUrl.toString()}(r.name),
          initiatorType: r.initiatorType,
          startTime: Math.round(r.startTime),
          duration: Math.round(r.duration),
          transferSize: r.transferSize || 0,
          encodedBodySize: r.encodedBodySize || 0
        }));
        const canvases = [...document.querySelectorAll('canvas')].map((c) => ({
          w: c.width,
          h: c.height,
          cssW: Math.round(c.getBoundingClientRect().width),
          cssH: Math.round(c.getBoundingClientRect().height)
        }));
        const text = document.body.innerText || '';
        return {
          title: document.title,
          url: location.href,
          bodyLen: text.length,
          bodyPrefix: text.slice(0, 500),
          canvasCount: canvases.length,
          readyCanvasCount: canvases.filter((c) => c.w > 1 && c.h > 1).length,
          canvases: canvases.slice(0, 40),
          imageCount: document.querySelectorAll('img').length,
          workerResources: resources.filter((r) => r.name.includes('h264-worker')),
          apiResources: resources.filter((r) => /\\/api\\//.test(r.name)).slice(-120),
          screenshotResources: resources.filter((r) => r.name.includes('/screenshot')).length,
          scrcpyAttachResources: resources.filter((r) => r.name.includes('/scrcpy/attach')).length,
          scrcpyDetachResources: resources.filter((r) => r.name.includes('/scrcpy/detach')).length,
          devicesLiveResources: resources.filter((r) => r.name.includes('/devices/live')).length,
          longTasks: (window.__dfPerf?.longTasks || []).map((x) => ({
            startTime: Math.round(x.startTime),
            duration: Math.round(x.duration)
          })),
          now: Math.round(performance.now())
        };
      })()`
    );

    const requests = client.events
      .filter((event) => event.method === 'Network.requestWillBeSent')
      .map((event) => event.params?.request?.url || '');
    const responses = client.events
      .filter((event) => event.method === 'Network.responseReceived')
      .map((event) => ({
        url: redactUrl(event.params?.response?.url || ''),
        status: event.params?.response?.status || 0,
        mime: event.params?.response?.mimeType || ''
      }));
    const summary = {
      sampleMs,
      navElapsedMs: Date.now() - navStartedAt,
      domStats,
      networkSummary: {
        requestCount: requests.length,
        responseCount: responses.length,
        failedCount: client.events.filter(
          (event) => event.method === 'Network.loadingFailed'
        ).length,
        apiRequests: requests
          .filter((url) => url.includes('/api/'))
          .slice(-120)
          .map(redactUrl),
        statusCounts: responses.reduce((acc, response) => {
          acc[response.status] = (acc[response.status] || 0) + 1;
          return acc;
        }, {}),
        wsCreated: client.events
          .filter((event) => event.method === 'Network.webSocketCreated')
          .map((event) => redactUrl(event.params?.url || '')),
        wsFramesReceived: client.events.filter(
          (event) => event.method === 'Network.webSocketFrameReceived'
        ).length,
        wsFramesSent: client.events.filter(
          (event) => event.method === 'Network.webSocketFrameSent'
        ).length
      }
    };
    console.log(JSON.stringify(summary, null, 2));
  } finally {
    client.close();
  }
}

main().catch((error) => {
  console.error(error?.stack ?? String(error));
  process.exitCode = 1;
});
