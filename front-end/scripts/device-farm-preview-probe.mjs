#!/usr/bin/env node

import process from 'node:process';

const cdpBaseUrl =
  process.env.DEVICE_FARM_PROBE_CDP_URL ?? 'http://127.0.0.1:9222';
const dashboardUrl =
  process.env.DEVICE_FARM_PROBE_URL ??
  'http://127.0.0.1:3000/vi/dashboard/device-farm';
const email = process.env.DEVICE_FARM_PROBE_EMAIL ?? '';
const password = process.env.DEVICE_FARM_PROBE_PASSWORD ?? '';
const maxFirstFrameMs = Number(
  process.env.DEVICE_FARM_PROBE_MAX_FIRST_FRAME_MS ?? 2_500
);

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

async function signInIfNeeded(client) {
  const loginState = await evaluate(
    client,
    `({
      url: location.href,
      hasPassword: Boolean(document.querySelector('input[type="password"]')),
      hasEmail: Boolean(document.querySelector('input[type="email"], input[name="email"]'))
    })`
  );
  if (!loginState.hasPassword) return false;
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
        'input[type="email"], input[name="email"]'
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

function summarizeRequests(requests) {
  return requests.map(
    ({
      serial,
      kind,
      method,
      atMs,
      responseAtMs,
      finishedAtMs,
      status,
      url
    }) => ({
      serial,
      kind,
      method,
      atMs: Math.round(atMs),
      responseMs:
        responseAtMs === undefined ? null : Math.round(responseAtMs - atMs),
      durationMs:
        finishedAtMs === undefined ? null : Math.round(finishedAtMs - atMs),
      status: status ?? null,
      path: new URL(url).pathname
    })
  );
}

async function collectPageState(client) {
  return evaluate(
    client,
    `(() => {
      const tiles = [...document.querySelectorAll('[data-serial]')];
      const margin = 0;
      return {
        url: location.href,
        viewport: { width: innerWidth, height: innerHeight },
        scrollY,
        documentHeight: document.documentElement.scrollHeight,
        totalLabel: document.querySelector('#stat-total')?.textContent?.trim() ?? null,
        renderedTiles: tiles.map((tile) => {
          const preview = tile.querySelector('.bg-zinc-950');
          const rect = preview?.getBoundingClientRect();
          const canvas = preview?.querySelector('canvas');
          const image = preview?.querySelector('img');
          return {
            serial: tile.getAttribute('data-serial'),
            top: rect ? Math.round(rect.top) : null,
            bottom: rect ? Math.round(rect.bottom) : null,
            withinWarmMargin: rect
              ? rect.bottom > -margin && rect.top < innerHeight + margin
              : false,
            hasVisibleFrame: Boolean(
              (canvas && getComputedStyle(canvas).opacity === '1') ||
                (image && getComputedStyle(image).opacity === '1')
            ),
            text: preview?.innerText?.trim() ?? ''
          };
        })
      };
    })()`
  );
}

async function run() {
  const pageTarget = await getPageTarget();
  const client = createCdpClient(pageTarget.webSocketDebuggerUrl);
  const requests = [];
  const requestsById = new Map();
  const webSocketFrames = [];
  let measurementStartedAt = 0;

  on('Network.requestWillBeSent', ({ requestId, request, timestamp }) => {
    const attach = request.url.match(/\/devices\/([^/]+)\/scrcpy\/attach/);
    const screenshot = request.url.match(/\/screenshot\/([^/?]+)/);
    const devicesApi =
      !attach &&
      !screenshot &&
      /\/api\/devices(?:\/live)?(?:[/?]|$)/.test(request.url);
    if (!attach && !screenshot && !devicesApi) return;
    const entry = {
      requestId,
      serial:
        attach || screenshot
          ? decodeURIComponent((attach ?? screenshot)[1])
          : null,
      kind: attach ? 'attach' : screenshot ? 'screenshot' : 'devices',
      method: request.method,
      atMs: timestamp * 1000 - measurementStartedAt,
      url: request.url
    };
    requests.push(entry);
    requestsById.set(requestId, entry);
  });
  on('Network.responseReceived', ({ requestId, response, timestamp }) => {
    const entry = requestsById.get(requestId);
    if (!entry) return;
    entry.status = response.status;
    entry.responseAtMs = timestamp * 1000 - measurementStartedAt;
  });
  on('Network.loadingFinished', ({ requestId, timestamp }) => {
    const entry = requestsById.get(requestId);
    if (!entry) return;
    entry.finishedAtMs = timestamp * 1000 - measurementStartedAt;
  });
  on('Network.webSocketFrameReceived', ({ response, timestamp }) => {
    if (response.opcode !== 2 || !response.payloadData) return;
    const frame = Buffer.from(response.payloadData, 'base64');
    if (frame.length < 3) return;
    const type = frame[0];
    const serialLength = frame[1];
    if (serialLength <= 0 || frame.length < 2 + serialLength) return;
    webSocketFrames.push({
      type,
      serial: frame.subarray(2, 2 + serialLength).toString('utf8'),
      atMs: timestamp * 1000 - measurementStartedAt,
      bytes: frame.length,
      isKey:
        type === 0x11 && frame.length >= 2 + serialLength + 5
          ? frame[2 + serialLength + 4] !== 0
          : null
    });
  });

  await Promise.all([
    client.send('Page.enable'),
    client.send('Runtime.enable'),
    client.send('Network.enable'),
    client.send('Performance.enable'),
    client.send('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false
    })
  ]);

  await navigate(client, dashboardUrl);
  await wait(800);
  const signedIn = await signInIfNeeded(client);
  if (signedIn) {
    await navigate(client, dashboardUrl);
    await wait(800);
  }

  requests.length = 0;
  webSocketFrames.length = 0;
  const metrics = await client.send('Performance.getMetrics');
  measurementStartedAt =
    (metrics.metrics.find((metric) => metric.name === 'Timestamp')?.value ??
      0) * 1000;

  await navigate(client, dashboardUrl);
  try {
    await waitFor(
      client,
      `document.querySelectorAll('[data-serial]').length > 0`
    );
  } catch (error) {
    const diagnostic = await evaluate(
      client,
      `({
        url: location.href,
        title: document.title,
        body: document.body?.innerText?.slice(0, 2000) ?? '',
        tileCount: document.querySelectorAll('[data-serial]').length
      })`
    );
    throw new Error(
      `${error instanceof Error ? error.message : error}\n${JSON.stringify(
        diagnostic,
        null,
        2
      )}`
    );
  }

  let firstFrameMs = null;
  const frameDeadline = Date.now() + 12_000;
  while (Date.now() < frameDeadline) {
    const state = await collectPageState(client);
    if (state.renderedTiles[0]?.hasVisibleFrame) {
      firstFrameMs = Math.round(await evaluate(client, 'performance.now()'));
      break;
    }
    await wait(100);
  }

  await wait(2_000);
  const beforeScroll = await collectPageState(client);
  const beforeScrollRequests = [...requests];

  await evaluate(
    client,
    `(() => {
      const grid = document.querySelector('[data-serial]')?.closest('section');
      let scroller = grid?.parentElement;
      while (scroller) {
        const overflowY = getComputedStyle(scroller).overflowY;
        if (overflowY === 'auto' || overflowY === 'scroll') break;
        scroller = scroller.parentElement;
      }
      const target = scroller ?? document.scrollingElement;
      target.scrollTop = target.scrollHeight;
      return { scrollTop: target.scrollTop, scrollHeight: target.scrollHeight };
    })()`
  );
  await wait(2_500);
  const afterScroll = await collectPageState(client);
  const allRequests = [...requests];

  const warmSerials = new Set(
    beforeScroll.renderedTiles
      .filter((tile) => tile.withinWarmMargin)
      .map((tile) => tile.serial)
  );
  const initialOffscreenRequests = beforeScrollRequests.filter(
    (request) =>
      request.serial !== null &&
      (request.kind === 'attach' || request.kind === 'screenshot') &&
      !warmSerials.has(request.serial)
  );
  const firstSerial = beforeScroll.renderedTiles[0]?.serial ?? null;
  const firstAttach = beforeScrollRequests.find(
    (request) =>
      request.kind === 'attach' &&
      request.method === 'POST' &&
      request.serial === firstSerial &&
      request.responseAtMs !== undefined
  );
  const firstAttachCompletedMs = firstAttach?.responseAtMs;
  const attachToFirstFrameMs =
    firstFrameMs !== null && firstAttachCompletedMs !== undefined
      ? Math.round(firstFrameMs - firstAttachCompletedMs)
      : null;
  const firstConfigFrame = webSocketFrames.find(
    (frame) => frame.serial === firstSerial && frame.type === 0x10
  );
  const firstVideoFrame = webSocketFrames.find(
    (frame) => frame.serial === firstSerial && frame.type === 0x11
  );
  const firstKeyFrame = webSocketFrames.find(
    (frame) =>
      frame.serial === firstSerial &&
      frame.type === 0x11 &&
      frame.isKey === true
  );

  const result = {
    signedIn,
    firstFrameMs,
    firstAttachCompletedMs:
      firstAttachCompletedMs === undefined
        ? null
        : Math.round(firstAttachCompletedMs),
    attachToFirstFrameMs,
    firstConfigFrameMs:
      firstConfigFrame === undefined ? null : Math.round(firstConfigFrame.atMs),
    firstVideoFrameMs:
      firstVideoFrame === undefined ? null : Math.round(firstVideoFrame.atMs),
    firstKeyFrameMs:
      firstKeyFrame === undefined ? null : Math.round(firstKeyFrame.atMs),
    videoPacketToFirstFrameMs:
      firstFrameMs !== null && firstVideoFrame !== undefined
        ? Math.round(firstFrameMs - firstVideoFrame.atMs)
        : null,
    beforeScroll,
    beforeScrollRequests: summarizeRequests(beforeScrollRequests),
    afterScroll,
    newRequestsAfterScroll: summarizeRequests(
      allRequests.slice(beforeScrollRequests.length)
    ),
    assertions: {
      firstFrameWithinBudget:
        firstFrameMs !== null &&
        Number.isFinite(maxFirstFrameMs) &&
        firstFrameMs <= maxFirstFrameMs,
      maxFirstFrameMs,
      noOffscreenPreviewBeforeScroll: initialOffscreenRequests.length === 0,
      initialOffscreenRequests: summarizeRequests(initialOffscreenRequests)
    }
  };

  console.log(JSON.stringify(result, null, 2));
  client.close();

  if (
    !result.assertions.noOffscreenPreviewBeforeScroll ||
    !result.assertions.firstFrameWithinBudget
  ) {
    process.exitCode = 1;
  }
}

run().catch((error) => {
  console.error(error instanceof Error ? error.stack : error);
  process.exitCode = 1;
});
