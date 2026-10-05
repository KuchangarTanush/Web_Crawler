# DarkTrace Crawling Engine

A queue-driven, multi-source web crawling engine built with **Scrapy, Celery, and Redis**.

The project is designed for crawling **authorized sources only** and currently supports:

- Single-source Scrapy crawling
- Multi-source scheduling from `sources.yaml`
- Redis-backed Celery task queues
- Three queue lanes: `fast`, `standard`, and `bulk`
- Per-source crawl intervals
- Request-level rate limiting and AutoThrottle
- Request-level retries with exponential backoff and jitter
- Whole-job retries with exponential backoff
- Crawl timeouts
- Dead-letter logging after repeated job failures
- Redis-backed per-source crawl state
- Direct, Tor, and I2P routing based on the target hostname
- Raw HTML/evidence storage and JSONL crawl-result logging

> **Authorization:** This project is intended for sources that you are authorized to crawl. It is a read-only collection system; it does not provide authorization to access a target.

---

## 1. Architecture

The engine has two main layers.

### `Crawler/` — single-source crawling

The Scrapy layer is responsible for performing one crawl:

1. Accept one authorized seed URL.
2. Determine the network path from the hostname.
3. Route `.onion` traffic through Tor.
4. Route `.i2p` traffic through I2P.
5. Fetch and parse the page.
6. Store raw content and content metadata.
7. Write a crawl-result record to `crawl_output/crawl_results.jsonl`.

The spider intentionally does **not** perform scheduling or multi-source orchestration.

### `engine/` — scheduling and job orchestration

The engine layer turns the single-source spider into a scheduled multi-source system:

1. `sources.yaml` defines the authorized source registry.
2. Celery Beat periodically runs `check_and_schedule`.
3. The scheduler checks whether each enabled source is due.
4. A Celery task is queued using the source's configured priority.
5. `engine.tasks.crawl_source` starts a clean Scrapy subprocess.
6. The task verifies both the subprocess result and the crawl-result record.
7. Failed jobs are retried at the Celery job level.
8. Repeated job failures are written to the dead-letter log and Redis state.

---

## 2. Project Structure

```text
Web_Crawler/
├── Crawler/
│   ├── spiders/
│   │   └── single_source.py
│   ├── settings.py
│   ├── middlewares.py
│   ├── pipelines.py
│   └── items.py
│
├── engine/
│   ├── celery_app.py       # Celery application, queues and Beat schedule
│   ├── scheduler.py        # Finds due sources and queues jobs
│   ├── tasks.py            # Runs Scrapy jobs and handles job retries
│   ├── state.py            # Redis-backed source state
│   └── sources.py          # Loads sources.yaml
│
├── sources.yaml            # Authorized source registry
├── requirements.txt
├── scrapy.cfg
└── crawl_output/
    ├── raw/
    ├── crawl_results.jsonl
    └── dead_letter.jsonl
```

---

## 3. Requirements

- Python 3.10+ recommended
- Redis 5+
- Scrapy 2.11+
- Celery 5.3+
- A Tor daemon/gateway if `.onion` sources are enabled
- An I2P router/proxy if `.i2p` sources are enabled

Python dependencies are listed in `requirements.txt`.

---

## 4. Installation

### Windows — PowerShell

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install Python dependencies

```bash
pip install -r requirements.txt
```

The requirements include:

- Scrapy
- Celery with Redis support
- Redis Python client
- PyYAML
- PySocks

---

## 5. Redis Setup

Redis is used for both:

- Celery's task broker/result backend
- Persistent crawl state shared between workers

By default the application uses:

```text
redis://localhost:6379/0   Celery broker
redis://localhost:6379/1   Celery result backend
redis://localhost:6379/2   Crawl state
```

These can be changed with environment variables:

```text
CELERY_BROKER_URL
CELERY_RESULT_BACKEND
CRAWL_STATE_REDIS_URL
```

### Linux

```bash
sudo apt install redis-server
sudo systemctl start redis-server
```

### macOS

```bash
brew install redis
brew services start redis
```

### Windows

Use Redis through WSL or Docker, for example:

```bash
docker run --name darktrace-redis -p 6379:6379 -d redis
```

Verify Redis:

```bash
redis-cli ping
```

Expected result:

```text
PONG
```

---

## 6. Proxy / Network Setup

### Tor

`.onion` requests are automatically routed through the configured Tor SOCKS5 proxy.

Default:

```text
socks5h://127.0.0.1:9050
```

The setting is:

```python
TOR_SOCKS_PROXY = "socks5h://127.0.0.1:9050"
```

If using Tor Browser, the SOCKS port may instead be `9150`; update the setting accordingly.

### I2P

`.i2p` requests are automatically routed through the configured I2P HTTP proxy.

Default:

```text
http://127.0.0.1:4444
```

The setting is:

```python
I2P_HTTP_PROXY = "http://127.0.0.1:4444"
```

Normal clearnet URLs are fetched directly without a proxy.

---

## 7. Running a Single Crawl

The single-source spider can be run without Celery.

### Normal site

```bash
scrapy crawl single_source \
  -a url="https://example.com" \
  -a source_type="normal"
```

### Onion site

```bash
scrapy crawl single_source \
  -a url="http://<authorized-address>.onion/" \
  -a source_type="onion_site"
```

### I2P site

```bash
scrapy crawl single_source \
  -a url="http://<authorized-address>.i2p/" \
  -a source_type="blog_news"
```

`source_name` is optional and defaults to `source_1`:

```bash
scrapy crawl single_source \
  -a url="https://example.com" \
  -a source_name="example_source" \
  -a source_type="normal"
```

The spider currently performs **single-seed crawling only**. It does not follow links recursively.

---

## 8. Source Registry

Edit `sources.yaml` to configure the sources managed by the queue-driven engine.

Example:

```yaml
sources:
  - name: news_source_1
    url: "https://example.com/"
    source_type: blog_news
    priority: standard
    interval_minutes: 30
    timeout_seconds: 120
    enabled: true
```

### Configuration fields

| Field | Description |
|---|---|
| `name` | Unique source identifier used in Redis and result logs |
| `url` | Authorized seed URL |
| `source_type` | Source category recorded in crawl metadata |
| `priority` | Celery queue: `fast`, `standard`, or `bulk` |
| `interval_minutes` | Minimum interval between completed crawl attempts |
| `timeout_seconds` | Maximum runtime of the Scrapy subprocess |
| `enabled` | Whether the scheduler should process the source |

### Queue priorities

| Queue | Intended use |
|---|---|
| `fast` | Short intervals / time-sensitive sources |
| `standard` | Normal crawling cadence |
| `bulk` | Slower, heavier, or lower-priority sources |

Set `enabled: false` to keep a source registered without scheduling it.

---

## 9. Scheduling

Celery Beat runs:

```text
engine.scheduler.check_and_schedule
```

The default scheduler interval is **30 seconds**.

It can be changed with:

```text
SCHEDULER_TICK_SECONDS
```

For example:

```bash
SCHEDULER_TICK_SECONDS=60
```

On each scheduler tick, enabled sources are evaluated:

1. Skip disabled sources.
2. Skip a source marked `in_progress`.
3. Check `interval_minutes` against the last crawl timestamp.
4. Queue a `crawl_source` task using the configured priority.

The scheduler therefore separates **when a source is due** from **how the actual crawl is executed**.

---

## 10. Celery Queues

The Celery application defines three queues:

```text
fast
standard
bulk
```

Jobs are explicitly routed using the source's `priority` value.

The application also uses:

```python
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1
app.conf.task_track_started = True
```

This means tasks are acknowledged late, workers prefetch only one job per worker slot, and Celery exposes task-started state.

### Start one worker for all queues

For development:

```bash
celery -A engine.celery_app worker \
  -Q fast,standard,bulk \
  --concurrency=4 \
  --loglevel=INFO
```

### Recommended separate workers

For stronger queue isolation, run separate processes:

```bash
celery -A engine.celery_app worker -Q fast --concurrency=4 --loglevel=INFO
```

```bash
celery -A engine.celery_app worker -Q standard --concurrency=2 --loglevel=INFO
```

```bash
celery -A engine.celery_app worker -Q bulk --concurrency=1 --loglevel=INFO
```

Separate workers prevent a large number of bulk jobs from consuming all worker capacity intended for fast jobs.

---

## 11. Start the Scheduler

Run Celery Beat separately:

```bash
celery -A engine.celery_app beat --loglevel=INFO
```

The normal deployment therefore has:

```text
Redis
  │
  ├── Celery Beat
  │      │
  │      └── scheduler tick
  │              │
  │              └── crawl_source task
  │
  └── Celery Workers
         ├── fast
         ├── standard
         └── bulk
                 │
                 └── Scrapy subprocess
```

For testing, one scheduling pass can also be triggered manually:

```bash
python -c "from engine.scheduler import check_and_schedule; print(check_and_schedule.apply())"
```

---

## 12. Rate Limiting and Throttling

Rate limiting is implemented in Scrapy.

Global settings include:

```python
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True
```

AutoThrottle is enabled:

```python
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
```

The `single_source` spider additionally sets:

```python
CONCURRENT_REQUESTS_PER_DOMAIN = 1
```

because a single-source job is intended to remain polite to the target host.

---

## 13. Timeouts

There are two timeout layers.

### HTTP request timeout

Scrapy uses:

```python
DOWNLOAD_TIMEOUT = 60
```

This prevents an individual HTTP request from hanging indefinitely.

### Whole crawl-job timeout

The Celery task starts Scrapy as a subprocess and applies the source-specific value from `sources.yaml`:

```yaml
timeout_seconds: 120
```

If the subprocess exceeds this limit, Python raises `subprocess.TimeoutExpired`, which is handled as a job failure and can be retried.

---

## 14. Retry and Failure Handling

There are two separate retry layers.

### Layer 1 — Scrapy request retries

Individual requests use `BackoffRetryMiddleware`.

Retryable HTTP statuses include:

```text
500, 502, 503, 504, 522, 524, 408, 429
```

The configured maximum is:

```python
RETRY_TIMES = 3
```

The custom middleware applies exponential backoff with jitter. The default base delay is `2` seconds, so delays are approximately:

```text
2s + jitter
4s + jitter
8s + jitter
```

After request retries are exhausted, a failed crawl-result record is written to `crawl_results.jsonl`.

### Layer 2 — Celery whole-job retries

`engine.tasks.crawl_source` separately retries the entire Scrapy subprocess when the job fails because of:

- subprocess timeout
- non-zero Scrapy exit code
- missing crawl-result record
- crawl-result status of `failed`
- another exception while executing the job

The job-level retry delay is:

```text
10s
20s
40s
```

The maximum is configured with:

```python
MAX_JOB_RETRIES = 3
```

After the job-level retry limit is exhausted, the source is recorded in:

```text
crawl_output/dead_letter.jsonl
```

and its Redis state is marked as `dead_letter`.

---

## 15. Crawl State

Redis stores one hash per source:

```text
crawlstate:<source_name>
```

Example:

```bash
redis-cli hgetall crawlstate:news_source_1
```

The state contains information such as:

- `last_crawled_ts`
- `last_success_ts`
- `last_status`
- `consecutive_failures`
- `total_success`
- `total_failed`
- `in_progress`
- `last_error` when applicable

This allows scheduling and worker processes to share source state safely across processes.

---

## 16. Output Files

### Raw content

```text
crawl_output/raw/<sha256>.html
```

Original fetched HTML is preserved by the evidence-storage pipeline.

### Crawl result log

```text
crawl_output/crawl_results.jsonl
```

Each crawl attempt produces a JSON Lines record containing information such as:

- source name
- source type
- URL
- network used
- timestamp
- crawler build
- status
- HTTP status
- title
- content hash
- evidence path
- error information when applicable

### Dead-letter log

```text
crawl_output/dead_letter.jsonl
```

This records jobs that exhausted the **whole-job Celery retry layer** and require operator review.

---

## 17. End-to-End Startup

A simple development setup can be started in this order.

### Terminal 1 — Redis

```bash
redis-server
```

or start Redis using your OS/Docker setup.

### Terminal 2 — Celery worker

```bash
celery -A engine.celery_app worker -Q fast,standard,bulk --concurrency=4 --loglevel=INFO
```

### Terminal 3 — Celery Beat

```bash
celery -A engine.celery_app beat --loglevel=INFO
```

The scheduler will then inspect `sources.yaml` every 30 seconds by default and queue due sources.

---

## 18. Verifying the System

### Check Redis

```bash
redis-cli ping
```

Expected:

```text
PONG
```

### Check registered queues

Start a worker with:

```bash
celery -A engine.celery_app worker -Q fast,standard,bulk --loglevel=INFO
```

The worker should report the queues it is consuming.

### Check the scheduler

Start Beat:

```bash
celery -A engine.celery_app beat --loglevel=INFO
```

You should see periodic execution of:

```text
engine.scheduler.check_and_schedule
```

### Check source state

```bash
redis-cli hgetall crawlstate:news_source_1
```

### Check crawl results

```bash
cat crawl_output/crawl_results.jsonl
```

### Check dead letters

```bash
cat crawl_output/dead_letter.jsonl
```

---

## 19. Current Limitations / Next Steps

The following features are intentionally not implemented yet:

- Recursive link following
- Crawl depth/scope management
- Incremental crawling using ETag / Last-Modified
- Forum/thread cursor tracking
- Automatic requeueing of dead-letter jobs
- Persistent queue/dashboard monitoring
- Dynamic per-source rate-limit configuration
- Dedicated production worker processes managed by a process supervisor

### Scheduler locking hardening

The current scheduler uses the Redis `in_progress` flag to avoid scheduling a source that is already running. The check and the enqueue operation are currently separate operations.

For production-grade duplicate protection, the next improvement should be an **atomic Redis claim/lock** acquired before `apply_async()`, with safe lock release and recovery from worker crashes. This prevents two scheduler ticks or multiple scheduler instances from claiming the same source simultaneously.

The current implementation should therefore be treated as a solid project/development implementation, with atomic scheduling locks as a recommended hardening step before running multiple scheduler instances or relying on strict duplicate-free scheduling.

---

## 20. Summary of Implemented Requirements

| Requirement | Status | Implementation |
|---|---|---|
| Scheduling | Implemented | Celery Beat + `interval_minutes` |
| Queue management | Implemented | Redis/Celery `fast`, `standard`, `bulk` queues |
| Rate limiting | Implemented | Scrapy delay, domain concurrency, AutoThrottle |
| Request timeout | Implemented | `DOWNLOAD_TIMEOUT = 60` |
| Crawl/job timeout | Implemented | `timeout_seconds` + subprocess timeout |
| Request retries | Implemented | Scrapy retry middleware, max 3 retries |
| Job retries | Implemented | Celery retries with 10/20/40s backoff |
| Dead-letter handling | Implemented | `dead_letter.jsonl` + Redis state |
| Crawl state | Implemented | Redis `crawlstate:<source>` hashes |
| Tor routing | Implemented | `.onion` → Tor SOCKS5 |
| I2P routing | Implemented | `.i2p` → I2P HTTP proxy |
| Raw evidence storage | Implemented | SHA-256 HTML files |
| Link following | Not implemented | Single seed only |
| Atomic scheduler lock | Recommended next step | Not yet implemented |
