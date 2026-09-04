# Sasta Maal (सस्ता माल) 🛍️⚡
### End-to-End Automated Deal Aggregator & Broadcast Pipeline

An enterprise-grade, distributed pipeline that ingests high-discount e-commerce deals from Indian platforms (**Amazon, Flipkart, Myntra, Ajio**), deduplicates against historical price drops, rewrites affiliate tags with user-defined tracking IDs, and broadcasts formatted alerts to **Telegram** channels and **WhatsApp** groups/channels.

---

## 🏛️ System Architecture

```
                    ┌─────────────────────────┐
                    │  Telegram Userbot       │
                    │  (Telethon MTProto)     │
                    └───────────┬─────────────┘
                                │ Real-time Posts & Media
                                ▼
┌─────────────────────────┐   ┌───────────────────────────┐
│ Target & API Scrapers   ├──►│    Deal Normalizer        │
│ (Playwright / HTTPX)    │   │ (Price, MRP, Discount %)  │
└─────────────────────────┘   └─────────────┬─────────────┘
                                            │
                                            ▼
                              ┌───────────────────────────┐
                              │  Redis Stream / Queue     │
                              │     (deals:incoming)      │
                              └─────────────┬─────────────┘
                                            │
                                            ▼
                              ┌───────────────────────────┐
                              │ 6h Deduplication & Lows   │
                              │ (Redis Sliding Window)    │
                              └─────────────┬─────────────┘
                                            │ Passed (< 5% drop / new)
                                            ▼
                              ┌───────────────────────────┐
                              │ Affiliate Transformation  │
                              │ • HTTP Redirect Resolver  │
                              │ • Amazon ASIN Tag Swapper │
                              │ • EarnKaro / Cuelinks API │
                              └─────────────┬─────────────┘
                                            │
                                            ▼
                              ┌───────────────────────────┐
                              │  Deal Formatter & Badges  │
                              │  (Telegram HTML / WA)     │
                              └─────────────┬─────────────┘
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    ▼                                               ▼
         ┌─────────────────────┐                         ┌─────────────────────┐
         │ Telegram Broadcaster│                         │ WhatsApp Broadcaster│
         │ (Bot API + Photo +  │                         │ (Node.js Baileys    │
         │  Inline Buy CTA)    │                         │  with Anti-Ban Jitter│
         └─────────────────────┘                         │  Queue 8-25s)       │
                                                         └─────────────────────┘
```

---

## 📂 Repository Structure

```
/sasta_maal
├── .env.example                  # Environment variable blueprint
├── docker-compose.yml            # Turnkey multi-container orchestration
├── Dockerfile                    # Production container for Python pipeline
├── requirements.txt              # Python runtime dependencies
├── config.py                     # Typed Pydantic configuration loader
│
├── ingestion/                    # Ingestion Layer
│   ├── normalizer.py             # Schema definition & regex parser for deals
│   ├── userbot_listener.py       # Engine A: Telethon MTProto channel listener
│   └── scraper_engine.py         # Engine B: Mobile API & flash deal scraper
│
├── transformer/                  # Processing & Enrichment Layer
│   ├── deduplicator.py           # 6h sliding window + price drop validation
│   ├── affiliate_engine.py       # URL unshortener, Amazon ASIN swapper, EarnKaro/Cuelinks
│   └── formatter.py              # Telegram HTML & WhatsApp formatters with badges
│
├── queue/                        # Distributed Queuing Layer
│   ├── redis_client.py           # Async Redis connection pool manager
│   ├── producer.py               # Deal enqueue producer
│   └── worker.py                 # Core consumer worker orchestrating pipeline
│
├── broadcaster/                  # Dispatch Layer
│   ├── telegram_broadcaster.py   # Telegram Bot API client (photo, caption, inline button)
│   ├── whatsapp_cloud.py         # Meta WhatsApp Business Cloud API (Option 1: Channel Mode)
│   └── whatsapp/                 # Option 2: Group / Community Mode
│       ├── package.json
│       ├── index.js              # Baileys service with human presence & jitter queue
│       └── Dockerfile
│
├── docs/
│   └── anti_ban_resilience.md    # Comprehensive Telegram MTProto, Proxy & WhatsApp anti-ban policies
│
└── tests/
    └── test_pipeline.py          # Pytest suite for normalizer, affiliate, dedup, and formatting
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- Docker & Docker Compose **or** Python 3.10+ & Node.js 20+ & Redis

### 2. Configuration
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

Key environment variables:
- `TELEGRAM_API_ID` & `TELEGRAM_API_HASH`: Get from [my.telegram.org](https://my.telegram.org)
- `TELEGRAM_BOT_TOKEN`: From [@BotFather](https://t.me/botfather)
- `TELEGRAM_BROADCAST_CHANNEL_ID`: Target channel (e.g., `@sasta_maal_deals`)
- `AMAZON_ASSOCIATE_TAG`: Your Amazon Associate tracking ID (`sastamaal-21`)
- `EARNKARO_API_KEY` or `CUELINKS_API_KEY`: For Flipkart/Myntra/Ajio monetization
- `WHATSAPP_GROUP_JIDS`: Comma-separated WhatsApp group IDs

### 3. Running with Docker Compose (Recommended)
```bash
docker-compose up -d --build
```
This automatically starts:
1. `redis`: Message broker and deduplication cache.
2. `whatsapp-service`: Baileys microservice on port 3001. Check logs to scan QR code:
   ```bash
   docker logs -f sasta_maal_whatsapp
   ```
3. `pipeline-worker`: Processes deals, rewrites links, and dispatches alerts.
4. `userbot-listener`: Listens to incoming master channels.
5. `scraper-engine`: Runs periodic scheduled scrapes for $\ge 70\%$ discount deals.

### 4. Running Manually for Development

#### Step A: Start Redis
```bash
redis-server
```

#### Step B: Install Python Dependencies & Run Tests
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
```

#### Step C: Start WhatsApp Microservice
```bash
cd broadcaster/whatsapp
npm install
node index.js
```
Scan the terminal QR code using WhatsApp on your phone (`Linked Devices`).

#### Step D: Start the Pipeline Worker
```bash
python queue/worker.py
```

#### Step E: Start Ingestion Engines
```bash
# Engine A: Telegram Userbot Listener
python ingestion/userbot_listener.py

# Engine B: Target Scrapers
python ingestion/scraper_engine.py
```

---

## 🛡️ Anti-Ban & Operational Safety

Read the detailed guide in [docs/anti_ban_resilience.md](file:///Users/shahidkhan/sasta_maal/docs/anti_ban_resilience.md).

Key protections implemented:
- **WhatsApp Anti-Ban Jitter**: Randomized 8–25 second delay between group posts + automated human typing presence simulation (`composing` state) + 45-90s cooldown every 5 groups.
- **Telegram MTProto FloodWait Shield**: Resolves channel entities once on startup and handles `FloodWaitError` gracefully.
- **Deduplication Window**: 6-hour sliding window suppressing flapping prices, allowing only genuine price drops ($> 5\%$) or all-time lows.
