# Research Report: Web Crawling — Features, OSS Projects & New Tech (2025-2026)

> Generated: 2026-04-16

---

## Table of Contents

1. [Essential Features for Production Crawling](#1-essential-features)
2. [Major Open-Source Projects](#2-major-oss)
3. [AI/LLM-Native Crawlers (New Wave)](#3-ai-llm-crawlers)
4. [Anti-Bot & Stealth Tech](#4-anti-bot)
5. [Architecture Patterns](#5-architecture)
6. [Tech Stack Recommendations](#6-recommendations)
7. [Resources](#7-resources)

---

## 1. Essential Features for Production Crawling

### Core Features (Must Have)

| Feature | Description |
|---|---|
| **Rate Limiting** | Throttle requests per domain; jitter delays to mimic human |
| **robots.txt Compliance** | Parse & respect crawl-delay, disallow rules |
| **Deduplication** | URL fingerprint hash (SHA/Bloom filter); avoid re-crawling |
| **Retry & Error Handling** | Exponential backoff on 429/503; dead-letter queue |
| **Request Scheduling** | Priority queue; BFS vs DFS strategy; politeness per domain |
| **Storage Backend** | Structured (Postgres/MongoDB) + blob (S3/MinIO) for raw HTML |
| **Checkpointing** | Persist queue state to disk; resume after crash |
| **Link Extraction** | CSS/XPath selectors; canonical URL normalization |

### For JS-Heavy Sites

| Feature | Description |
|---|---|
| **Browser Automation** | Playwright/Puppeteer; headless Chromium |
| **Wait Strategies** | Wait for selector/network idle/custom signals |
| **Infinite Scroll Handling** | Trigger scroll events, detect pagination |
| **Shadow DOM** | Crawl4AI v0.8.5+ supports Shadow DOM flattening |
| **AJAX/SPA Support** | Intercept XHR/fetch; capture API responses directly |

### Scale & Reliability

| Feature | Description |
|---|---|
| **Distributed Crawling** | Multi-worker with shared queue (Redis/Kafka) |
| **Proxy Rotation** | Residential > Datacenter; per-domain pool |
| **Autoscaling** | Adjust concurrency based on CPU/memory/success rate |
| **Monitoring** | Request rate, error rate, queue depth, blocked % |
| **Sitemap Parsing** | `sitemap.xml` for seed URL discovery |
| **Screenshot / Capture** | Visual evidence; diff detection for change monitoring |

---

## 2. Major Open-Source Projects

### Python

#### Scrapy ⭐ ~52k GitHub stars
- **Lang**: Python | **License**: BSD
- Battle-tested since 2008; async via Twisted
- Native async/await in Scrapy 2.14+
- Playwright integration available via `scrapy-playwright`
- Huge middleware ecosystem: proxy, retry, cache, pipeline
- **Con**: No built-in JS rendering; distributed requires Scrapyd/Scrapy Cluster
- **Best for**: Large-scale structured data from static/semi-static sites

#### Crawl4AI ⭐ ~58k stars (trending #1 on GitHub 2024)
- **Lang**: Python | **License**: Apache 2.0
- LLM-native: outputs clean Markdown/JSON for RAG pipelines
- Playwright under hood; async-first
- BM25 filtering, chunking strategies, citation extraction
- Self-hosted, **completely free**
- Anti-bot in v0.8.5; Shadow DOM support; webhook job queues
- **Best for**: AI pipelines, RAG, autonomous agents

#### MechanicalSoup / httpx + Parsel
- Lightweight; good for simple static sites
- No JS; fast; used for microservices

### JavaScript / Node.js

#### Crawlee ⭐ ~17k stars (by Apify)
- **Lang**: TypeScript/Node.js + Python beta | **License**: Apache 2.0
- 3 crawler types: `CheerioCrawler` (static), `PuppeteerCrawler`, `PlaywrightCrawler`
- Built-in: fingerprint rotation, proxy pool, session management, autoscaling, disk-persistent queue
- Python v1.0 released Sept 2025
- **Best for**: Full-stack JS teams; anti-bot-heavy sites

#### Puppeteer ⭐ ~88k stars
- **Lang**: Node.js | **License**: Apache 2.0
- Google's official Chrome DevTools Protocol wrapper
- Headless Chrome control; screenshot, PDF, intercept network
- Less anti-bot than Playwright by default
- **Best for**: Chrome-specific automation; low-level control

#### Playwright ⭐ ~68k stars
- **Lang**: Multi (Node/Python/Java/.NET) | **License**: Apache 2.0
- Cross-browser: Chromium, WebKit, Firefox
- Network interception, multi-tab, storage state
- **Best for**: Browser automation; cross-browser testing + crawling

### Java

#### Apache Nutch ⭐ ~2.5k stars
- **Lang**: Java | **License**: Apache 2.0
- Hadoop/MapReduce integration; petabyte-scale
- Plugin system; Solr/Elasticsearch output
- Heavy ops overhead; enterprise use only
- **Best for**: Large-scale enterprise search indexing

#### Heritrix ⭐ ~3k stars
- **Lang**: Java | **License**: Apache 2.0
- Internet Archive's official crawler
- WARC output; web archiving standard
- **Best for**: Full web archiving; compliance/preservation

### Go

#### Colly ⭐ ~24k stars
- **Lang**: Go | **License**: Apache 2.0
- Fast, lightweight; async; robots.txt built-in
- No JS rendering (static only)
- **Best for**: High-performance static crawling; Go stacks

---

## 3. AI/LLM-Native Crawlers (New Wave 2024-2026)

### Crawl4AI (Python, OSS, free)
- #1 GitHub trending 2024; 58k+ stars
- Markdown output with fit/chunked/citation modes
- LLM extraction: any model (local or API)
- Adaptive crawling: learns reliable selectors over time
- Docker + webhook support for production

### Firecrawl (TypeScript, OSS + SaaS)
- 6 endpoints: scrape, crawl, search, map, agent, interact
- `/interact` endpoint: click/fill forms behind dynamic content
- FIRE-1 autonomous navigation agent (no manual selectors needed)
- **MCP Server**: Claude/Cursor/Codex can use it as tool
- Cloud: from $16/mo; OSS self-host available
- LangChain + LlamaIndex integrations out of box

### Spider (SaaS, fastest benchmark)
- Claims 50k+ pages/second
- Pay-per-page; 9 API endpoints
- Best for: bulk AI training data at scale

### ScrapeGraphAI
- Graph-based LLM scraping pipeline
- Define extract schema in natural language → AI extracts

### Comparison

| | Crawl4AI | Firecrawl | Spider |
|---|---|---|---|
| Cost | Free | $16+/mo | Pay-per-page |
| Self-host | Yes | Yes | No |
| JS Render | Playwright | Built-in | Built-in |
| LLM extract | Local + API | API | API |
| Anti-bot | 3-tier auto | Cloud proxy | Built-in |
| Best for | RAG, agents | Rapid dev | High volume |

---

## 4. Anti-Bot & Stealth Tech

### Detection Vectors Sites Use

```
IP reputation → TLS fingerprint (JA3) → HTTP headers → 
Browser fingerprint (canvas/WebGL/fonts) → Behavioral signals 
(mouse/scroll/timing) → Honeypot traps → CAPTCHA
```

### Bypass Techniques Stack

#### Proxy Tiers
- Residential > Mobile > Datacenter (by detectability)
- Rotate per domain; low concurrency per IP
- Jitter delay between requests

#### Browser Stealth
- `playwright-stealth` / `puppeteer-stealth` plugin — patches 200+ leaks
- Patch `navigator.webdriver = false`
- Match TLS fingerprint to real browser (JA3 spoofing)
- Rotate: User-Agent, Accept-Language, Accept, Referer headers

#### Fingerprint Evasion
- Canvas fingerprint randomization
- WebGL parameter spoofing
- Font list normalization
- Screen/timezone/locale consistency (must match!)

#### Behavioral Mimicry
- Random mouse movement + scroll speed
- Jitter click timing
- Session warming (browse homepage first)
- Avoid honeypot hidden links (check CSS `display:none`)

#### Platform-Specific
- **Cloudflare**: FlareSolverr (OSS proxy layer), Playwright + stealth, residential proxies
- **DataDome**: Mobile residential IPs, reuse cookies, gentle rate limit
- **CAPTCHA**: AI solver services (2captcha, CapMonster) as last resort — if you're seeing CAPTCHA, already flagged

### Key OSS Stealth Tools

| Tool | Purpose |
|---|---|
| FlareSolverr | Cloudflare bypass proxy (Docker) |
| undetected-chromedriver | Selenium with patched Chrome |
| playwright-stealth | Stealth patches for Playwright |
| Botasaurus | Python anti-bot framework |
| nodriver | UC Mode Chrome (no webdriver flag) |

---

## 5. Architecture Patterns

### Single Machine (small scale)
```
Seed URLs → Scheduler (in-memory queue) 
         → Workers (async) 
         → Parser 
         → Storage (SQLite/Postgres)
```

### Distributed (medium scale)
```
Seed URLs → Redis Queue → N Workers (Docker/K8s pods)
                        → Dedup Filter (Bloom)
                        → Parser Workers
                        → S3/MinIO (raw HTML)
                        → Postgres (structured)
         Monitoring: Prometheus + Grafana
```

### Cloud-Native / AI Pipeline
```
Trigger (cron/webhook) 
→ Crawl Worker (Crawl4AI/Firecrawl) 
→ Markdown/JSON output 
→ Chunker 
→ Embedding Model 
→ Vector DB (Qdrant/Weaviate/pgvector) 
→ RAG Query Layer
```

### Change Detection Pattern
```
Crawl → Hash content → Compare with prev hash → 
  If changed: store diff + trigger downstream pipeline
```

---

## 6. Tech Stack Recommendations

### For Android Device Farm Use Case (this project)
If crawling apps/social via device farm:
- **Appium + uiautomator2**: UI-based content extraction from apps
- Screenshot → Vision LLM (GPT-4V / Gemini) → structured data
- XML hierarchy parsing (already in use) for element detection
- Store captures in MinIO (already configured)

### For General Web Crawling

| Scenario | Recommended Stack |
|---|---|
| Static sites, Python team | Scrapy + httpx |
| JS-heavy, Node team | Crawlee + Playwright |
| AI/RAG pipeline | Crawl4AI (self-hosted) |
| Rapid prototyping | Firecrawl API |
| High volume AI data | Spider API |
| Go microservice | Colly |
| Web archiving | Heritrix + WARC |

### Infra Essentials
- **Queue**: Redis (simple) → Kafka (high scale)
- **Dedup**: Redis Bloom filter / HyperLogLog
- **Storage**: MinIO for raw; Postgres for structured
- **Monitoring**: Prometheus + Grafana; alert on error_rate > 5%
- **Proxy**: Brightdata / Oxylabs residential (paid) or ProxyMesh

---

## 7. Resources

### Official Docs
- [Scrapy docs](https://docs.scrapy.org/)
- [Crawlee docs](https://crawlee.dev/)
- [Playwright docs](https://playwright.dev/)
- [Crawl4AI docs](https://docs.crawl4ai.com/)
- [Firecrawl docs](https://docs.firecrawl.dev/)

### GitHub
- [Crawl4AI](https://github.com/unclecode/crawl4ai) — 58k⭐
- [Crawlee](https://github.com/apify/crawlee) — 17k⭐
- [Colly](https://github.com/gocolly/colly) — 24k⭐
- [Scrapy](https://github.com/scrapy/scrapy) — 52k⭐
- [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)

### Benchmarks
- [Firecrawl vs Crawl4AI vs Spider benchmark](https://spider.cloud/blog/firecrawl-vs-crawl4ai-vs-spider-honest-benchmark)
- [Scrapy vs Crawlee comparison](https://crawlee.dev/blog/scrapy-vs-crawlee)
- [Best OSS crawlers 2026 - Firecrawl blog](https://www.firecrawl.dev/blog/best-open-source-web-crawler)
- [Apify OSS crawler list](https://blog.apify.com/top-11-open-source-web-crawlers-and-one-powerful-web-scraper/)

### Anti-Bot
- [ScraperAPI bypass guide](https://www.scraperapi.com/web-scraping/how-to-bypass-bot-detection/)
- [ZenRows bot detection bypass](https://www.zenrows.com/blog/bypass-bot-detection)
- [WebAutomation anti-bot guide](https://webautomation.io/blog/ultimate-guide-to-web-scraping-antibot-and-blocking-systems-and-how-to-bypass-them/)

---

## Unresolved Questions
- CAPTCHA solving at scale: best cost/reliability tradeoff?
- Legal grey area: bypass ToS for public data in Vietnam jurisdiction?
- Crawl4AI vs Crawlee for Python teams wanting browser + anti-bot?
