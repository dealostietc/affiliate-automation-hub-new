# Anti-Ban & System Resilience Architecture Guide

This document defines the production hardening, rate limiting, and anti-ban safeguards implemented across the Sasta Maal deal aggregation and broadcasting pipeline.

---

## 1. Telegram MTProto Userbot Listener (Engine A)

Telegram monitors user accounts for automated API abuse via behavioral heuristics and spam detection algorithms.

### Risks & Failure Modes
- `FloodWaitError`: Triggered when an account issues too many requests or resolves too many entity usernames in a short window.
- `UserDeactivatedBanError`: Complete account revocation if flagged by Telegram's automated spam filters.
- `SpamBot Mute`: Account restricted from messaging non-contacts or joining channels.

### Resilience Policies Implemented
1. **Event-Driven Listening Only**:
   - The userbot connects via `events.NewMessage` and **passively receives** incoming channel broadcasts.
   - It **does NOT poll** or flood `GetHistoryRequest` or `GetDialogsRequest`.
2. **Channel Entity Caching**:
   - Source channel usernames (`@deals_india`) are resolved once during startup and stored in-memory as entity IDs, eliminating repeated `ResolveUsernameRequest` calls.
3. **FloodWait Backoff Interceptor**:
   - The listener wraps all MTProto interactions in `try...except FloodWaitError as e:` and automatically sleeps for `e.seconds + 5` seconds before resuming.
4. **Session String Isolation**:
   - Store the `.session` file in a persistent volume. Avoid re-authenticating with SMS/OTP repeatedly, as frequent logins from changing IP addresses trigger immediate Telegram security bans.
5. **Session Safety Rule**:
   - Use a dedicated secondary phone number ("burner / operations SIM") for the userbot listener. Never use your personal primary Telegram account.

---

## 2. Web Scrapers & Proxy Rotation (Engine B)

E-commerce giants (Amazon, Flipkart, Myntra, Ajio) employ sophisticated bot-mitigation engines (Cloudflare, Akamai Bot Manager, Amazon WAF).

### Scraping Protections Implemented
1. **Rotating Residential Proxies**:
   - For listing pages and high-frequency checks, residential IPs with sticky 5–10 minute sessions are required.
   - Proxies must route through Indian gateways (`country=IN`) to access regional deals and Rupee (₹) pricing.
2. **Mobile App Header Spoofing**:
   - Mobile app endpoints have significantly higher rate thresholds than desktop web pages.
   - Mobile headers emulate official Android/iOS apps:
     ```python
     "User-Agent": "com.amazon.mShop.android.shopping/28.8.0.100 (Android 14; Mobile; en_IN)"
     "X-Platform": "android"
     ```
3. **Randomized Jitter & Backoff**:
   - Requests between scrape cycles are separated by randomized sleep intervals ($300s \pm 30s$).
   - HTTP status `429 Too Many Requests` or `503 Service Unavailable` triggers exponential backoff ($5s \rightarrow 15s \rightarrow 45s$).
4. **Passive Fallback Priority**:
   - Engine A (Telegram Userbot) acts as the primary real-time ingestion source.
   - Engine B (Scraper) acts as a supplemental discovery engine, keeping scraping request volume low and stealthy.

---

## 3. WhatsApp Distribution & Anti-Ban Architecture

WhatsApp enforces strict automated heuristics to detect bulk messaging and unapproved automation.

### Comparison: Baileys vs Meta Cloud API

| Metric | Baileys (Group / Community Mode) | Meta Cloud API (Channel Mode) |
| :--- | :--- | :--- |
| **Ban Risk** | Medium / High without precautions | **Zero Ban Risk** (Official API) |
| **Delivery Model** | WhatsApp Groups & Communities | WhatsApp Broadcast / Official Channel |
| **Pricing** | Free (self-hosted) | Free tier for first 1,000 conversations / mo |
| **Setup** | QR code scanning via microservice | Meta Developer App + Verified Business |

### Baileys Anti-Ban Guardrails (Implemented in `broadcaster/whatsapp/index.js`)

1. **Randomized Dispatch Jitter**:
   - **Never post synchronously** to multiple groups.
   - When a deal is broadcast to $N$ groups, the dispatcher pauses for a randomized duration between **8 to 25 seconds** between each group post:
     ```javascript
     const jitterDelay = Math.floor(Math.random() * (25 - 8 + 1) + 8) * 1000;
     await delay(jitterDelay);
     ```
2. **Simulated Human Typing Presence**:
   - Prior to sending a message or image, the bot dispatches an explicit typing presence update to the group:
     ```javascript
     await sock.sendPresenceUpdate('composing', jid);
     await delay(randomTypingDuration); // 2.5 - 5.0 seconds
     await sock.sendPresenceUpdate('paused', jid);
     ```
   - WhatsApp heuristics monitor whether messages arrive instantly without prior composing events.
3. **Batch Cooldown Period**:
   - After dispatching to **5 consecutive groups**, the queue worker triggers a mandatory cooldown of **45 to 90 seconds** before resuming.
4. **Number Warming Protocol (Crucial for New Numbers)**:
   - **Week 1**: Post only 3–5 deals per day to 1–2 test groups. Ensure real people chat in the group.
   - **Week 2**: Increase to 10–15 deals per day across 3–5 groups.
   - **Week 3+**: Full production broadcasting.
5. **Group Admin Privilege**:
   - Make the bot number an **Admin** in the target groups. WhatsApp heavily deprioritizes spam reports from groups where the sender is an administrator.
6. **Session Persistence**:
   - Auth credentials are stored in `broadcaster/whatsapp/session/` using multi-file auth state. Persist this folder across Docker restarts to avoid re-generating session tokens.

---

## 4. Deduplication & Anti-Spam Queue Policies

To prevent channel followers from muting or reporting your channels:
1. **6-Hour Sliding Deduplication Window**: Identical deals or flapping prices are silently dropped by `transformer/deduplicator.py`.
2. **Minimum 5% Price Drop Filter**: An item is only reposted within 6 hours if its price has dropped by at least 5% or reached an all-time low.
3. **Dead-Letter Queue (DLQ)**: Malformed payloads or unresolvable URLs are dumped to `deals:dead_letter` for post-mortem debugging without interrupting real-time processing.
