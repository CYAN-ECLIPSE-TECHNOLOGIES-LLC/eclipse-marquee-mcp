#!/usr/bin/env python3
"""End-to-end stdio smoke for Eclipse Marquee v0.1 (F0).

Uses a temporary state file. Drives initialize -> event_search ->
listing_read -> watch_create -> early evaluate (no alert) -> final
evaluate (all-in dip alert) -> receipt_list.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent


def rpc(proc, rid, method, params=None):
    req = {"jsonrpc": "2.0", "id": rid, "method": method,
           "params": params or {}}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def call(proc, rid, name, args):
    response = rpc(proc, rid, "tools/call", {"name": name, "arguments": args})
    return json.loads(response["result"]["content"][0]["text"])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env["ECLIPSE_MARQUEE_STATE"] = str(Path(tmp) / "state.json")
        proc = subprocess.Popen(
            [sys.executable, str(HERE / "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            cwd=str(HERE), env=env)
        try:
            init = rpc(proc, 1, "initialize",
                       {"protocolVersion": "2025-03-26"})
            assert init["result"]["serverInfo"]["name"] == "eclipse-marquee"
            print("initialize OK")

            search = call(proc, 2, "event_search",
                          {"query": "Denver Altitude", "city": "Denver"})
            assert search["count"] == 1, search
            assert search["events"][0]["listings"][0]["location"]["row"] == "J"
            print("event_search OK; row semantics preserved")

            listing = call(proc, 3, "listing_read",
                           {"listing_id": "tm-listing-112-f"})
            assert listing["listing"]["location"]["row"] == "F"
            assert listing["listing"]["current_price"]["all_in"] == 136.0
            print("listing_read OK; face/fees/all-in separate")

            watch = call(proc, 4, "watch_create", {
                "watch_id": "smoke-watch",
                "event_id": "tm-concert-lumen-20261114",
                "section_constraints": ["112"],
                "ceiling_all_in": 140,
                "quantity": 2,
                "expiry": "2026-10-31T23:59:59Z",
                "created_at": "2026-10-19T12:00:00Z",
            })
            assert watch["watch"]["watch_id"] == "smoke-watch"
            print("watch_create OK")

            early = call(proc, 5, "watch_evaluate", {
                "watch_id": "smoke-watch", "as_of": "2026-10-24T12:00:00Z"})
            assert early["new_alert_count"] == 0, early
            print("early evaluate OK; all-in 141 did not alert")

            final = call(proc, 6, "watch_evaluate", {
                "watch_id": "smoke-watch", "as_of": "2026-10-25T12:00:00Z"})
            assert final["new_alert_count"] == 1, final
            assert final["new_alerts"][0]["unit_all_in"] == 136.0
            print("final evaluate OK; all-in dip alert at 136")

            receipts = call(proc, 7, "receipt_list", {})
            assert receipts["chain_valid"] is True
            print("receipts OK; chain valid")
            print("SMOKE PASSED")
        finally:
            proc.stdin.close()
            proc.terminate()


if __name__ == "__main__":
    main()
