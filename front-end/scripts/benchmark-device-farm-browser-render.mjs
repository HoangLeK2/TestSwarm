#!/usr/bin/env node

import process from 'node:process';

const cdpBaseUrl =
  process.env.DEVICE_FARM_BROWSER_BENCH_CDP_URL ?? 'http://127.0.0.1:9222';
const tiles = Number(process.env.DEVICE_FARM_BROWSER_BENCH_TILES ?? 100);
const visibleTiles = Number(
  process.env.DEVICE_FARM_BROWSER_BENCH_VISIBLE_TILES ?? tiles
);
const frames = Number(process.env.DEVICE_FARM_BROWSER_BENCH_FRAMES ?? 120);
const warmupFrames = Number(
  process.env.DEVICE_FARM_BROWSER_BENCH_WARMUP_FRAMES ?? 10
);
const width = Number(process.env.DEVICE_FARM_BROWSER_BENCH_WIDTH ?? 216);
const height = Number(process.env.DEVICE_FARM_BROWSER_BENCH_HEIGHT ?? 480);
const targetFps = Number(process.env.DEVICE_FARM_BROWSER_BENCH_FPS ?? 12);
const drawP95BudgetMs = Number(
  process.env.DEVICE_FARM_BROWSER_BENCH_DRAW_P95_MS ?? 16
);
const rafGapP95BudgetMs = Number(
  process.env.DEVICE_FARM_BROWSER_BENCH_RAF_GAP_P95_MS ?? 50
);
const longFrameBudget = Number(
  process.env.DEVICE_FARM_BROWSER_BENCH_LONG_FRAMES ?? 2
);

let nextCommandId = 0;
const pendingCommands = new Map();

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    if (!message.id) return;
    const pending = pendingCommands.get(message.id);
    if (!pending) return;
    pendingCommands.delete(message.id);
    if (message.error) {
      pending.reject(new Error(message.error.message));
    } else {
      pending.resolve(message.result);
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

async function navigateBlank(client) {
  await client.send('Page.navigate', {
    url:
      'data:text/html;charset=utf-8,' +
      encodeURIComponent(`<!doctype html>
<meta charset="utf-8">
<title>Device Farm Browser Render Benchmark</title>
<style>
  html, body { margin: 0; background: #050505; color: #fff; }
  #grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(${width}px, 1fr));
    gap: 4px;
    padding: 4px;
  }
  canvas { width: ${width}px; height: ${height}px; background: #111; }
</style>
<div id="grid"></div>`)
  });
  await wait(200);
}

function benchmarkExpression(options) {
  return `(() => {
    const options = ${JSON.stringify(options)};
    const percentile = (values, p) => {
      if (!values.length) return 0;
      const sorted = [...values].sort((a, b) => a - b);
      const pos = Math.max(0, Math.min(1, p)) * (sorted.length - 1);
      const idx = Math.floor(pos);
      const frac = pos - idx;
      if (idx >= sorted.length - 1) return sorted[sorted.length - 1];
      return sorted[idx] + (sorted[idx + 1] - sorted[idx]) * frac;
    };
    const grid = document.getElementById('grid');
    grid.textContent = '';
    const canvases = [];
    for (let index = 0; index < options.tiles; index += 1) {
      const canvas = document.createElement('canvas');
      canvas.width = options.width;
      canvas.height = options.height;
      canvas.dataset.serial = 'mock-phone-' + String(index).padStart(3, '0');
      if (index >= options.visibleTiles) {
        canvas.style.display = 'none';
      }
      grid.appendChild(canvas);
      canvases.push(canvas);
    }
    const active = canvases.slice(0, options.visibleTiles);
    const contexts = active.map((canvas) => canvas.getContext('2d', { alpha: false }));
    const frameIntervalMs = 1000 / Math.max(1, options.targetFps);
    const drawSamples = [];
    const rafGaps = [];
    let longFrames = 0;
    let renderedFrames = 0;
    let measuredFrames = 0;
    let lastRaf = performance.now();
    let measuredStartedAt = 0;

    return new Promise((resolve) => {
      const draw = (rafNow) => {
        const rafGap = rafNow - lastRaf;
        lastRaf = rafNow;
        const drawStarted = performance.now();
        const hue = renderedFrames % 255;
        for (let index = 0; index < contexts.length; index += 1) {
          const ctx = contexts[index];
          ctx.fillStyle = 'rgb(' + hue + ',' + ((index * 7) % 255) + ',32)';
          ctx.fillRect(0, 0, options.width, options.height);
          ctx.fillStyle = '#fff';
          ctx.fillRect((renderedFrames + index) % options.width, 0, 2, options.height);
        }
        const drawMs = performance.now() - drawStarted;
        if (renderedFrames >= options.warmupFrames) {
          if (measuredStartedAt === 0) measuredStartedAt = drawStarted;
          rafGaps.push(rafGap);
          drawSamples.push(drawMs);
          if (drawMs > 50 || rafGap > 100) longFrames += 1;
          measuredFrames += 1;
        }
        renderedFrames += 1;
        if (measuredFrames >= options.frames) {
          const elapsedMs = performance.now() - measuredStartedAt;
          resolve({
            kind: 'browser_canvas_render_mock',
            tiles: options.tiles,
            visibleTiles: options.visibleTiles,
            width: options.width,
            height: options.height,
            targetFps: options.targetFps,
            warmupFrames: options.warmupFrames,
            renderedFrames: measuredFrames,
            elapsedMs: Math.round(elapsedMs * 1000) / 1000,
            effectiveFps: Math.round((measuredFrames / elapsedMs) * 1000000) / 1000,
            drawP50Ms: Math.round(percentile(drawSamples, 0.50) * 1000) / 1000,
            drawP95Ms: Math.round(percentile(drawSamples, 0.95) * 1000) / 1000,
            drawMaxMs: Math.round(Math.max(...drawSamples) * 1000) / 1000,
            rafGapP95Ms: Math.round(percentile(rafGaps, 0.95) * 1000) / 1000,
            rafGapMaxMs: Math.round(Math.max(...rafGaps) * 1000) / 1000,
            longFrames
          });
          return;
        }
        setTimeout(() => requestAnimationFrame(draw), frameIntervalMs);
      };
      requestAnimationFrame(draw);
    });
  })()`;
}

async function run() {
  const pageTarget = await getPageTarget();
  const client = createCdpClient(pageTarget.webSocketDebuggerUrl);
  try {
    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await navigateBlank(client);
    const result = await evaluate(
      client,
      benchmarkExpression({
        tiles,
        visibleTiles,
        frames,
        warmupFrames,
        width,
        height,
        targetFps
      })
    );
    result.budgets = {
      drawP95Ms: drawP95BudgetMs,
      rafGapP95Ms: rafGapP95BudgetMs,
      longFrames: longFrameBudget
    };
    result.ok =
      result.drawP95Ms <= drawP95BudgetMs &&
      result.rafGapP95Ms <= rafGapP95BudgetMs &&
      result.longFrames <= longFrameBudget;
    console.log(JSON.stringify(result, null, 2));
    if (!result.ok) {
      throw new Error(
        `Browser render benchmark failed: drawP95=${result.drawP95Ms}ms, rafGapP95=${result.rafGapP95Ms}ms, longFrames=${result.longFrames}`
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
