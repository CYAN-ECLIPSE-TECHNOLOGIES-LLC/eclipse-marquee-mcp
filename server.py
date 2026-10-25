#!/usr/bin/env python3
"""Eclipse Marquee MCP — v0.1.0, phase F0 (discovery + Price Watcher).

Powered by Cyan Eclipse Technologies (cetech.ai).

Eclipse Marquee — the live-events agent: it finds the event, watches
the price, buys only inside your mandate, and keeps the receipt for
every ticket. It does not scalp, bypass, or bet.

F0 SCOPE — READ-ONLY:
  * Unified discovery over a LOCAL STUB FEED whose records are shaped
    like Ticketmaster Discovery and SeatGeek Platform responses.
  * Listing reads that preserve section, row, and seat semantics.
  * Price watches evaluated against shipped fixture snapshots.
  * Hash-chained receipts and first-party watch-price history.

NO LIVE MARKETPLACE CALL EXISTS IN THIS FILE. There are no API keys,
no checkout path, no purchase tool, no resale tool, and no transfer
tool. Buying is phase F1 and remains behind owner/API-key gates.

Fee truth is a hard rule: face value and every fee component remain
separate fields, and watcher ceilings compare the ALL-IN unit price
(face value + all fees), never the pre-fee price alone.

Transport: MCP over stdio (newline-delimited JSON-RPC 2.0), stdlib only.
State: $ECLIPSE_MARQUEE_STATE or ./data/state.json beside this file.
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
STATE_PATH = Path(os.environ.get(
    "ECLIPSE_MARQUEE_STATE", HERE / "data" / "state.json"))


class ToolError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value):
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 10:  # date-only means the start of that UTC day
        text += "T00:00:00+00:00"
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def money(value) -> float:
    return round(float(value), 2)


# --------------------------------------------------------------------- state
def empty_state() -> dict:
    return {"watches": {}, "alerts": [], "price_history": [],
            "receipts": []}


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return empty_state()


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


# ------------------------------------------------------------------ receipts
def emit_receipt(state: dict, rtype: str, detail: dict) -> dict:
    """Append-only, hash-chained (house pattern)."""
    prev = state["receipts"][-1]["hash"] if state["receipts"] else "GENESIS"
    entry = {"seq": len(state["receipts"]) + 1, "ts": int(time.time()),
             "type": rtype, "prev_hash": prev, "detail": detail}
    entry["hash"] = sha(prev + canon(
        {k: v for k, v in entry.items() if k != "hash"}))
    state["receipts"].append(entry)
    return entry


def verify_receipt_chain(receipts) -> bool:
    prev = "GENESIS"
    for entry in receipts:
        if entry.get("prev_hash") != prev:
            return False
        expected = sha(prev + canon(
            {k: v for k, v in entry.items() if k != "hash"}))
        if entry.get("hash") != expected:
            return False
        prev = entry["hash"]
    return True


# ------------------------------------------------------------- normalization
def price_from_snapshot(snapshot: dict, face_key: str) -> dict:
    """Return face value, each fee, total fees, and all-in separately."""
    raw_fees = snapshot.get("fees", {})
    fees = {
        "service": money(raw_fees.get("service", 0)),
        "facility": money(raw_fees.get("facility", 0)),
        "processing": money(raw_fees.get("processing", 0)),
    }
    fees["total"] = money(sum(fees.values()))
    face = money(snapshot[face_key])
    return {"face_value": face, "fees": fees,
            "all_in": money(face + fees["total"])}


def normalize_snapshots(raw_snapshots, face_key, source, feed_file,
                        source_listing_id):
    snapshots = []
    for index, raw in enumerate(raw_snapshots):
        price = price_from_snapshot(raw, face_key)
        snapshots.append({
            "observed_at": raw["observed_at"],
            **price,
            "provenance": {
                "source": source,
                "feed_file": feed_file,
                "source_listing_id": source_listing_id,
                "snapshot_index": index,
                "basis": "local stub feed; no live marketplace call",
            },
        })
    snapshots.sort(key=lambda item: parse_time(item["observed_at"]))
    return snapshots


def normalize_ticketmaster_event(event: dict):
    venue = event.get("_embedded", {}).get("venues", [{}])[0]
    classifications = event.get("classifications", [{}])
    category = classifications[0].get("segment", {}).get("name", "Event")
    listings = []
    raw_listings = event.get("ticketing_extension", {}).get("listings", [])
    for raw in raw_listings:
        snapshots = normalize_snapshots(
            raw.get("price_snapshots", []), "face_value", "ticketmaster",
            "ticketmaster_feed.json", raw["id"])
        current = snapshots[-1] if snapshots else None
        listings.append({
            "listing_id": raw["id"],
            "source": "ticketmaster",
            "source_listing_id": raw["id"],
            "delivery_basis": raw.get("delivery_basis"),
            # Location remains nested: section/row/seat truth is never
            # flattened into a generic ticket label.
            "location": {
                "section": str(raw["section"]),
                "row": str(raw["row"]),
                "seats": [str(seat) for seat in raw.get("seats", [])],
            },
            "available_quantity": int(raw.get("available_quantity", 0)),
            "current_price": current,
            "price_snapshots": snapshots,
        })
    performers = [p.get("name") for p in event.get("performers", [])]
    return {
        "event_id": event["id"],
        "source": "ticketmaster",
        "source_event_id": event["id"],
        "name": event["name"],
        "category": category,
        "genre": classifications[0].get("genre", {}).get("name"),
        "performers_or_teams": performers,
        "date": event.get("dates", {}).get("start", {}).get("localDate"),
        "time": event.get("dates", {}).get("start", {}).get("localTime"),
        "venue": {
            "name": venue.get("name"),
            "city": venue.get("city", {}).get("name"),
            "state": venue.get("state", {}).get("stateCode"),
        },
        "feed_provenance": {
            "source": "ticketmaster",
            "feed_file": "ticketmaster_feed.json",
            "shape": "Ticketmaster Discovery-shaped local stub",
        },
        "listings": listings,
    }


def normalize_seatgeek_event(event: dict):
    venue = event.get("venue", {})
    listings = []
    raw_listings = event.get("listing_extension", {}).get("listings", [])
    for raw in raw_listings:
        snapshots = normalize_snapshots(
            raw.get("price_snapshot_history", []), "list_price", "seatgeek",
            "seatgeek_feed.json", raw["id"])
        current = snapshots[-1] if snapshots else None
        listings.append({
            "listing_id": raw["id"],
            "source": "seatgeek",
            "source_listing_id": raw["id"],
            "delivery_basis": raw.get("sale_type"),
            "location": {
                "section": str(raw["section"]),
                "row": str(raw["row"]),
                "seats": [str(seat) for seat in raw.get("seat_numbers", [])],
            },
            "available_quantity": int(raw.get("quantity_available", 0)),
            "current_price": current,
            "price_snapshots": snapshots,
        })
    date_text, _, time_text = str(event.get("datetime_local", "")).partition("T")
    return {
        "event_id": str(event["id"]),
        "source": "seatgeek",
        "source_event_id": str(event["id"]),
        "name": event["title"],
        "category": str(event.get("type", "Event")).upper(),
        "genre": event.get("type"),
        "performers_or_teams": [
            p.get("name") for p in event.get("performers", [])],
        "date": date_text,
        "time": time_text,
        "venue": {
            "name": venue.get("name"),
            "city": venue.get("city"),
            "state": venue.get("state"),
        },
        "feed_provenance": {
            "source": "seatgeek",
            "feed_file": "seatgeek_feed.json",
            "shape": "SeatGeek Platform-shaped local stub",
        },
        "listings": listings,
    }


def load_events():
    tm = json.loads((FIXTURES / "ticketmaster_feed.json").read_text())
    sg = json.loads((FIXTURES / "seatgeek_feed.json").read_text())
    events = [normalize_ticketmaster_event(event)
              for event in tm.get("_embedded", {}).get("events", [])]
    events += [normalize_seatgeek_event(event)
               for event in sg.get("events", [])]
    return events


def event_index():
    return {event["event_id"]: event for event in load_events()}


def public_event(event, include_snapshots=False):
    copied = json.loads(json.dumps(event))
    if not include_snapshots:
        for listing in copied["listings"]:
            listing.pop("price_snapshots", None)
    return copied


def find_listing(listing_id):
    for event in load_events():
        for listing in event["listings"]:
            if listing["listing_id"] == listing_id:
                return event, listing
    raise ToolError(f"unknown listing: {listing_id}")


# --------------------------------------------------------------------- tools
def t_event_search(state, args):
    query = str(args.get("query", "")).lower().strip()
    city = str(args.get("city", "")).lower().strip()
    category = str(args.get("category", "")).lower().strip()
    date_from = str(args.get("date_from", "")).strip()
    date_to = str(args.get("date_to", "")).strip()
    results = []
    for event in load_events():
        haystack = " ".join([
            event["name"], event["category"], event.get("genre") or "",
            event["venue"].get("name") or "",
            event["venue"].get("city") or "",
            " ".join(event.get("performers_or_teams") or []),
        ]).lower()
        if query and query not in haystack:
            continue
        if city and city != str(event["venue"].get("city", "")).lower():
            continue
        if category and category not in event["category"].lower():
            continue
        if date_from and event["date"] < date_from:
            continue
        if date_to and event["date"] > date_to:
            continue
        results.append(public_event(event))
    return {"events": results, "count": len(results),
            "feed_mode": "local_stub_only",
            "note": "F0 discovery is read-only and uses shipped fixtures; "
                    "no live marketplace was contacted."}


def t_listing_read(state, args):
    listing_id = args.get("listing_id")
    event_id = args.get("event_id")
    if bool(listing_id) == bool(event_id):
        raise ToolError("provide exactly one of listing_id or event_id")
    if listing_id:
        event, listing = find_listing(str(listing_id))
        return {"event": public_event(event), "listing": listing,
                "semantics_preserved": True}
    event = event_index().get(str(event_id))
    if not event:
        raise ToolError(f"unknown event: {event_id}")
    return {"event": public_event(event, include_snapshots=True),
            "listings": event["listings"],
            "semantics_preserved": True}


def normalize_sections(values):
    if values is None:
        return None
    if not isinstance(values, list) or not values:
        raise ToolError("section_constraints must be a non-empty list")
    return sorted({str(value).strip().upper() for value in values})


def section_matches(listing, constraints):
    if not constraints:
        return True
    return listing["location"]["section"].strip().upper() in constraints


def validate_tightening(old, new):
    """A successor watch may only tighten: ceiling down, sections
    narrower, and expiry no later. Every loosening is rejected by name."""
    loosened = []
    if new["ceiling_all_in"] > old["ceiling_all_in"]:
        loosened.append(
            f"ceiling_all_in: {old['ceiling_all_in']} -> "
            f"{new['ceiling_all_in']}")
    old_sections = set(old.get("section_constraints") or [])
    new_sections = set(new.get("section_constraints") or [])
    if old_sections and (not new_sections or not new_sections.issubset(old_sections)):
        loosened.append("section_constraints widened")
    if parse_time(new["expiry"]) > parse_time(old["expiry"]):
        loosened.append("expiry extended")
    if loosened:
        raise ToolError(
            "Marquee tightening rule: a watch may only be tightened "
            "(ceiling down, sections narrower, expiry no later), never "
            "loosened. Rejected: " + "; ".join(loosened))


def t_watch_create(state, args):
    supersedes_id = args.get("supersedes_watch_id")
    old = None
    if supersedes_id:
        old = state["watches"].get(str(supersedes_id))
        if not old:
            raise ToolError(f"unknown watch to supersede: {supersedes_id}")
        if old.get("status") == "superseded":
            raise ToolError(f"watch already superseded: {supersedes_id}")

    event_id = str(args.get("event_id") or (old or {}).get("event_id") or "")
    event = event_index().get(event_id)
    if not event:
        raise ToolError(f"unknown event: {event_id}")
    if old and event_id != old["event_id"]:
        raise ToolError("a successor watch cannot change events")

    sections = normalize_sections(
        args.get("section_constraints",
                 (old or {}).get("section_constraints")))
    ceiling = args.get("ceiling_all_in",
                       (old or {}).get("ceiling_all_in"))
    if ceiling is None:
        raise ToolError("ceiling_all_in is required")
    ceiling = money(ceiling)
    if ceiling <= 0:
        raise ToolError("ceiling_all_in must be positive")
    quantity = int(args.get("quantity", (old or {}).get("quantity", 1)))
    if quantity <= 0:
        raise ToolError("quantity must be positive")
    if old and quantity != old["quantity"]:
        raise ToolError("a successor watch cannot change quantity")

    created_at = str(args.get("created_at") or now_iso())
    expiry = str(args.get("expiry") or (old or {}).get("expiry") or "")
    if not expiry:
        raise ToolError("expiry is required")
    if parse_time(expiry) <= parse_time(created_at):
        raise ToolError("expiry must be after created_at")

    known_sections = {
        listing["location"]["section"].strip().upper()
        for listing in event["listings"]}
    if sections and not set(sections).issubset(known_sections):
        unknown = sorted(set(sections) - known_sections)
        raise ToolError(
            f"section constraints not present for this event: {unknown}")

    watch = {
        "event_id": event_id,
        "section_constraints": sections,
        "ceiling_all_in": ceiling,
        "ceiling_basis": "per-ticket face value + all fees",
        "quantity": quantity,
        "expiry": expiry,
        "created_at": created_at,
        "status": "active",
        "supersedes_watch_id": str(supersedes_id) if supersedes_id else None,
    }
    if old:
        validate_tightening(old, watch)

    watch_id = str(args.get("watch_id") or "")
    if not watch_id:
        seed = canon(watch) + f"|{len(state['receipts'])}|{len(state['watches'])}"
        watch_id = "watch_" + sha(seed)[:12]
    if watch_id in state["watches"]:
        raise ToolError(f"watch already exists: {watch_id}")
    watch["watch_id"] = watch_id

    if old:
        old["status"] = "superseded"
        old["superseded_by"] = watch_id
    state["watches"][watch_id] = watch
    receipt = emit_receipt(
        state, "watch_tightened" if old else "watch_created",
        {"watch_id": watch_id, "event_id": event_id,
         "ceiling_all_in": ceiling, "section_constraints": sections,
         "quantity": quantity, "expiry": expiry,
         "supersedes_watch_id": watch["supersedes_watch_id"]})
    return {"watch": watch, "receipt_seq": receipt["seq"]}


def t_watch_list(state, args):
    event_id = args.get("event_id")
    watches = [watch for watch in state["watches"].values()
               if not event_id or watch["event_id"] == str(event_id)]
    watches.sort(key=lambda item: item["created_at"])
    alerts = [alert for alert in state["alerts"]
              if not event_id or alert["event_id"] == str(event_id)]
    return {"watches": watches, "count": len(watches), "alerts": alerts,
            "alert_count": len(alerts)}


def latest_snapshot_at_or_before(listing, as_of):
    eligible = [snapshot for snapshot in listing["price_snapshots"]
                if parse_time(snapshot["observed_at"]) <= as_of]
    return eligible[-1] if eligible else None


def history_key(entry):
    return (entry["watch_id"], entry["listing_id"], entry["observed_at"])


def t_watch_evaluate(state, args):
    as_of_text = str(args.get("as_of") or now_iso())
    as_of = parse_time(as_of_text)
    requested = args.get("watch_id")
    watches = []
    if requested:
        watch = state["watches"].get(str(requested))
        if not watch:
            raise ToolError(f"unknown watch: {requested}")
        watches = [watch]
    else:
        watches = [watch for watch in state["watches"].values()
                   if watch.get("status") == "active"]

    evaluations, new_alerts = [], []
    known_history = {history_key(entry) for entry in state["price_history"]}
    known_alerts = {
        (alert["watch_id"], alert["listing_id"], alert["observed_at"])
        for alert in state["alerts"]}

    for watch in watches:
        if watch.get("status") == "superseded":
            evaluations.append({"watch_id": watch["watch_id"],
                                "status": "superseded", "alerts": []})
            continue
        event = event_index()[watch["event_id"]]
        expired = as_of > parse_time(watch["expiry"])
        if expired:
            watch["status"] = "expired"
        watch_alerts = []
        evaluated_listings = []

        if not expired:
            for listing in event["listings"]:
                if not section_matches(listing, watch["section_constraints"]):
                    continue
                snapshot = latest_snapshot_at_or_before(listing, as_of)
                if not snapshot:
                    continue
                history_entry = {
                    "watch_id": watch["watch_id"],
                    "event_id": watch["event_id"],
                    "listing_id": listing["listing_id"],
                    "source": listing["source"],
                    "observed_at": snapshot["observed_at"],
                    "face_value": snapshot["face_value"],
                    "fees": snapshot["fees"],
                    "all_in": snapshot["all_in"],
                    "provenance": snapshot["provenance"],
                }
                if history_key(history_entry) not in known_history:
                    state["price_history"].append(history_entry)
                    known_history.add(history_key(history_entry))
                evaluated_listings.append({
                    "listing_id": listing["listing_id"],
                    "observed_at": snapshot["observed_at"],
                    "face_value": snapshot["face_value"],
                    "fees": snapshot["fees"],
                    "all_in": snapshot["all_in"],
                    "available_quantity": listing["available_quantity"],
                })
                enough = (listing["available_quantity"] >= watch["quantity"])
                under = snapshot["all_in"] <= watch["ceiling_all_in"]
                if enough and under:
                    alert_key = (watch["watch_id"], listing["listing_id"],
                                 snapshot["observed_at"])
                    if alert_key not in known_alerts:
                        alert = {
                            "alert_id": "alert_" + sha(canon({
                                "watch_id": watch["watch_id"],
                                "listing_id": listing["listing_id"],
                                "observed_at": snapshot["observed_at"],
                            }))[:12],
                            "watch_id": watch["watch_id"],
                            "event_id": watch["event_id"],
                            "listing_id": listing["listing_id"],
                            "source": listing["source"],
                            "observed_at": snapshot["observed_at"],
                            "location": listing["location"],
                            "face_value": snapshot["face_value"],
                            "fees": snapshot["fees"],
                            "unit_all_in": snapshot["all_in"],
                            "quantity": watch["quantity"],
                            "group_all_in": money(
                                snapshot["all_in"] * watch["quantity"]),
                            "ceiling_all_in": watch["ceiling_all_in"],
                        }
                        state["alerts"].append(alert)
                        known_alerts.add(alert_key)
                        watch_alerts.append(alert)
                        new_alerts.append(alert)
        evaluation = {
            "watch_id": watch["watch_id"],
            "status": "expired" if expired else watch["status"],
            "as_of": as_of_text,
            "evaluated_listings": evaluated_listings,
            "alerts": watch_alerts,
        }
        evaluations.append(evaluation)
        emit_receipt(state, "watch_evaluated", {
            "watch_id": watch["watch_id"], "as_of": as_of_text,
            "status": evaluation["status"],
            "listings_evaluated": len(evaluated_listings),
            "new_alerts": len(watch_alerts)})

    for alert in new_alerts:
        emit_receipt(state, "alert_created", {
            "alert_id": alert["alert_id"], "watch_id": alert["watch_id"],
            "listing_id": alert["listing_id"],
            "observed_at": alert["observed_at"],
            "unit_all_in": alert["unit_all_in"]})

    return {"evaluations": evaluations, "evaluation_count": len(evaluations),
            "new_alerts": new_alerts, "new_alert_count": len(new_alerts),
            "price_history_count": len(state["price_history"])}


def t_receipt_list(state, args):
    limit = args.get("limit")
    receipts = state["receipts"]
    if limit is not None:
        receipts = receipts[-int(limit):]
    return {"receipts": receipts, "count": len(receipts),
            "chain_valid": verify_receipt_chain(state["receipts"])}


TOOLS = {
    "event_search": (
        t_event_search,
        "Search the LOCAL stub event feed by artist, team, keyword, city, "
        "category, and date range. Read-only; no live marketplace call.",
        {"query": {"type": "string"}, "city": {"type": "string"},
         "category": {"type": "string"}, "date_from": {"type": "string"},
         "date_to": {"type": "string"}}, []),
    "listing_read": (
        t_listing_read,
        "Read one listing by listing_id, or an event and all listings by "
        "event_id. Section, row, and seat data remain nested and intact; "
        "face value and each fee remain separate, with all-in shown.",
        {"listing_id": {"type": "string"}, "event_id": {"type": "string"}},
        []),
    "watch_create": (
        t_watch_create,
        "Create a Price Watcher. ceiling_all_in is PER TICKET and includes "
        "all fees. Optional supersedes_watch_id creates a successor only "
        "if it tightens the prior watch; loosening is rejected by name.",
        {"watch_id": {"type": "string"}, "event_id": {"type": "string"},
         "section_constraints": {"type": "array",
                                 "items": {"type": "string"}},
         "ceiling_all_in": {"type": "number"},
         "quantity": {"type": "integer"}, "expiry": {"type": "string"},
         "created_at": {"type": "string"},
         "supersedes_watch_id": {"type": "string"}}, []),
    "watch_list": (
        t_watch_list,
        "List watches and their alert records, optionally for one event.",
        {"event_id": {"type": "string"}}, []),
    "watch_evaluate": (
        t_watch_evaluate,
        "Evaluate one watch (or all active watches) against the latest "
        "fixture snapshot at or before as_of. Stores new price-history "
        "points and receipts any alert. Expired watches do not alert.",
        {"watch_id": {"type": "string"}, "as_of": {"type": "string"}}, []),
    "receipt_list": (
        t_receipt_list,
        "List the append-only, hash-chained Marquee receipts and verify "
        "the chain.",
        {"limit": {"type": "integer"}}, []),
}

# Capability denylist, stated in code: F0 has no transaction surface.
FORBIDDEN_TOOL_NAMES = {
    "mandate_buy", "buy_prep", "purchase", "checkout", "transfer",
    "group_coord", "own_ticket_resale", "resale", "entry_readiness",
}


def tool_list():
    return [{"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": props,
                             "required": required}}
            for name, (_, description, props, required) in TOOLS.items()]


def handle(req: dict):
    method, rid = req.get("method", ""), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get(
                "protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eclipse-marquee", "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"tools": tool_list()}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        if name in FORBIDDEN_TOOL_NAMES or name not in TOOLS:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602, "message": f"unknown or F0-forbidden tool {name}"}}
        state = load_state()
        try:
            out = TOOLS[name][0](state, args)
            save_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(out, indent=1)}]}}
        except ToolError as exc:
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(exc)})}],
                "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except Exception as exc:  # never crash the transport
            response = {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32603, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
