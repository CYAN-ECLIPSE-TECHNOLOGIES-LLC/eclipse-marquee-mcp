# Eclipse Marquee MCP

**Powered by Cyan Eclipse Technologies** — https://cetech.ai

**Eclipse Marquee — the live-events agent: it finds the event, watches the price, buys only inside your mandate, and keeps the receipt for every ticket. It does not scalp, bypass, or bet.**

## Why this exists

Event discovery is fragmented across marketplaces, prices move constantly, and fees often surface only after a headline price has done its work. Marquee F0 fixes the read-only half of that problem: one normalized event model that preserves section, row, and seat truth; fee components kept separate from face value; and a Price Watcher that compares only the all-in price against an owner's ceiling.

## Status — honest labels

v0.1.0, phase **F0 only (discovery + Price Watcher)**. **Read-only.** Local stdio transport, Python stdlib only. Data comes from shipped fixtures and a local stub feed shaped like Ticketmaster Discovery and SeatGeek Platform responses. **No live marketplace call exists in the code, no API keys are used, and no certification is claimed — bench pending.**

Explicitly NOT in v0.1, by spec and by design: purchase or checkout tools, transfer tools, resale tools, group coordination, entry credential handling, organizer-side tools, odds, and betting. Buying is phase F1 and stays behind owner/API-key gates.

## Tools (6)

| Tool | What it does |
|---|---|
| `event_search` | Search the local stub feed by artist, team, keyword, city, category, and date range. |
| `listing_read` | Read one listing, or an event and all its listings. Section, row, and seats remain nested and intact. Face value, each fee, total fees, and all-in price remain separate fields. |
| `watch_create` | Create a Price Watcher: event, section constraints, per-ticket all-in ceiling, quantity, and expiry. A successor watch may only tighten the prior watch. |
| `watch_list` | List watches and alert records, optionally by event. |
| `watch_evaluate` | Evaluate watches against the latest fixture price snapshot at or before `as_of`; stores first-party price history and receipts any alert. |
| `receipt_list` | List the append-only receipt chain and verify it. |

## Fee truth + the tightening rule

A watcher's ceiling is **per ticket, all-in**: face value plus service, facility, and processing fees. A listing below the ceiling before fees but above it after fees does **not** alert.

A successor watch created with `supersedes_watch_id` may only **tighten**: lower ceiling, narrower section set, no later expiry, same event and quantity. Any loosening is rejected as a **Marquee tightening rule** violation.

## Fixtures + stub feed

`fixtures/ticketmaster_feed.json` carries a concert and a theater production in a Ticketmaster Discovery-shaped envelope. `fixtures/seatgeek_feed.json` carries an NBA game in a SeatGeek Platform-shaped envelope. Every listing ships a four-point price-snapshot series. The concert's Section 112, Row F series moves all-in from 151 to 146 to 141 and finally to **136**, creating one dip under a 140 ceiling. Its Section 108 listing is the fee trap: the face value is under 140 while the all-in price is not.

## Receipts + watch exhaust

Watch creation, tightening, evaluations, and alerts append hash-chained receipts. Evaluations also store first-party price-history points with per-source provenance: source, feed file, source listing ID, and snapshot index. The shipped data is explicitly a local stub; no retention or live-source claim is made.

## Run it

```bash
python3 server.py            # MCP over stdio, stdlib only, no dependencies
python3 smoke.py             # end-to-end smoke over real stdio (temp state)
python3 -m unittest discover tests
python3 make_icon.py         # regenerate icon-512.png
```

State persists in `data/state.json` beside the server (override with `ECLIPSE_MARQUEE_STATE`). `data/` is gitignored.

## Roadmap (per spec)

- **F1** — buy-under-mandate through official checkout rails, only after owner/API-key gates and dogfood on CETech's own event workflow.
- **F2** — group logistics, chain-of-custody receipts, official transfers, entry-day readiness.
- **O** — organizer side only under signed partner terms.

## License / attribution

A Cyan Eclipse Technologies product. The "Powered by Cyan Eclipse Technologies" attribution travels with it.
