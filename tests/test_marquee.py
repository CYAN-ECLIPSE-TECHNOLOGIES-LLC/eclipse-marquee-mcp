#!/usr/bin/env python3
"""Eclipse Marquee v0.1 (F0) tests. Run: python3 -m unittest discover tests"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import server as S  # noqa: E402

CONCERT = "tm-concert-lumen-20261114"
CREATED = "2026-10-19T12:00:00Z"


def create_watch(state, **overrides):
    args = {
        "watch_id": "watch-main",
        "event_id": CONCERT,
        "section_constraints": ["112"],
        "ceiling_all_in": 140,
        "quantity": 2,
        "expiry": "2026-10-31T23:59:59Z",
        "created_at": CREATED,
    }
    args.update(overrides)
    return S.t_watch_create(state, args)


class TestNormalization(unittest.TestCase):
    def test_fixture_catalog_has_three_event_kinds(self):
        events = S.load_events()
        self.assertEqual(len(events), 3)
        self.assertEqual({event["category"] for event in events},
                         {"Music", "NBA", "Arts & Theatre"})
        self.assertEqual({event["source"] for event in events},
                         {"ticketmaster", "seatgeek"})

    def test_search_and_row_semantics_survive(self):
        state = S.empty_state()
        out = S.t_event_search(state, {"query": "Lumen Skyline"})
        self.assertEqual(out["count"], 1)
        listing = out["events"][0]["listings"][0]
        self.assertEqual(listing["location"]["section"], "112")
        self.assertEqual(listing["location"]["row"], "F")
        self.assertEqual(listing["location"]["seats"], ["9", "10", "11", "12"])

        read = S.t_listing_read(state, {"listing_id": listing["listing_id"]})
        self.assertTrue(read["semantics_preserved"])
        self.assertEqual(read["listing"]["location"]["row"], "F")
        self.assertEqual(read["listing"]["location"]["section"], "112")

    def test_fee_fields_are_separate_and_sum_to_all_in(self):
        _, listing = S.find_listing("tm-listing-112-f")
        price = listing["current_price"]
        self.assertEqual(price["face_value"], 111.0)
        self.assertEqual(price["fees"]["service"], 18.0)
        self.assertEqual(price["fees"]["facility"], 7.0)
        self.assertEqual(price["fees"]["processing"], 0.0)
        self.assertEqual(price["fees"]["total"], 25.0)
        self.assertEqual(price["all_in"], 136.0)


class TestWatcher(unittest.TestCase):
    def test_all_in_dip_detection_uses_snapshot_series(self):
        state = S.empty_state()
        create_watch(state)
        early = S.t_watch_evaluate(
            state, {"watch_id": "watch-main", "as_of": "2026-10-24T12:00:00Z"})
        self.assertEqual(early["new_alert_count"], 0)
        self.assertEqual(
            early["evaluations"][0]["evaluated_listings"][0]["all_in"], 141.0)

        final = S.t_watch_evaluate(
            state, {"watch_id": "watch-main", "as_of": "2026-10-25T12:00:00Z"})
        self.assertEqual(final["new_alert_count"], 1)
        alert = final["new_alerts"][0]
        self.assertEqual(alert["listing_id"], "tm-listing-112-f")
        self.assertEqual(alert["face_value"], 111.0)
        self.assertEqual(alert["fees"]["total"], 25.0)
        self.assertEqual(alert["unit_all_in"], 136.0)
        self.assertEqual(alert["group_all_in"], 272.0)

    def test_pre_fee_under_ceiling_but_all_in_over_does_not_alert(self):
        state = S.empty_state()
        create_watch(state, watch_id="watch-trap",
                     section_constraints=["108"])
        out = S.t_watch_evaluate(
            state, {"watch_id": "watch-trap", "as_of": "2026-10-25T12:00:00Z"})
        listing = out["evaluations"][0]["evaluated_listings"][0]
        self.assertLess(listing["face_value"], 140)
        self.assertGreater(listing["all_in"], 140)
        self.assertEqual(out["new_alert_count"], 0)

    def test_watch_expiry_blocks_alert(self):
        state = S.empty_state()
        create_watch(state, watch_id="watch-expired",
                     expiry="2026-10-23T23:59:59Z")
        out = S.t_watch_evaluate(
            state, {"watch_id": "watch-expired",
                    "as_of": "2026-10-25T12:00:00Z"})
        self.assertEqual(out["evaluations"][0]["status"], "expired")
        self.assertEqual(out["new_alert_count"], 0)
        self.assertEqual(state["watches"]["watch-expired"]["status"], "expired")

    def test_history_is_first_party_and_provenanced(self):
        state = S.empty_state()
        create_watch(state)
        S.t_watch_evaluate(
            state, {"watch_id": "watch-main", "as_of": "2026-10-25T12:00:00Z"})
        self.assertEqual(len(state["price_history"]), 1)
        entry = state["price_history"][0]
        self.assertEqual(entry["source"], "ticketmaster")
        self.assertEqual(entry["provenance"]["feed_file"],
                         "ticketmaster_feed.json")
        self.assertEqual(entry["provenance"]["source_listing_id"],
                         "tm-listing-112-f")


class TestTighteningRule(unittest.TestCase):
    def setUp(self):
        self.state = S.empty_state()
        create_watch(self.state, section_constraints=["112", "201"])

    def test_tightening_successor_accepted(self):
        out = S.t_watch_create(self.state, {
            "watch_id": "watch-tight",
            "supersedes_watch_id": "watch-main",
            "section_constraints": ["112"],
            "ceiling_all_in": 130,
            "created_at": "2026-10-20T12:00:00Z",
        })
        self.assertEqual(out["watch"]["ceiling_all_in"], 130.0)
        self.assertEqual(self.state["watches"]["watch-main"]["status"],
                         "superseded")

    def test_ceiling_loosening_rejected_by_name(self):
        with self.assertRaises(S.ToolError) as ctx:
            S.t_watch_create(self.state, {
                "watch_id": "watch-loose-ceiling",
                "supersedes_watch_id": "watch-main",
                "ceiling_all_in": 150,
                "created_at": "2026-10-20T12:00:00Z",
            })
        self.assertIn("Marquee tightening rule", str(ctx.exception))
        self.assertIn("never loosened", str(ctx.exception))

    def test_section_loosening_rejected_by_name(self):
        with self.assertRaises(S.ToolError) as ctx:
            S.t_watch_create(self.state, {
                "watch_id": "watch-loose-sections",
                "supersedes_watch_id": "watch-main",
                "section_constraints": ["112", "108"],
                "created_at": "2026-10-20T12:00:00Z",
            })
        self.assertIn("Marquee tightening rule", str(ctx.exception))
        self.assertIn("section_constraints widened", str(ctx.exception))


class TestLineAndReceipts(unittest.TestCase):
    EXPECTED = {"event_search", "listing_read", "watch_create", "watch_list",
                "watch_evaluate", "receipt_list"}

    def test_capability_denylist(self):
        names = {tool["name"] for tool in S.tool_list()}
        self.assertEqual(names, self.EXPECTED)
        self.assertTrue(names.isdisjoint(S.FORBIDDEN_TOOL_NAMES))
        for forbidden in ("mandate_buy", "purchase", "checkout", "transfer",
                          "own_ticket_resale"):
            self.assertNotIn(forbidden, names)
        response = S.handle({
            "jsonrpc": "2.0", "id": 99, "method": "tools/call",
            "params": {"name": "purchase", "arguments": {}}})
        self.assertIn("F0-forbidden", response["error"]["message"])

    def test_receipt_chain_and_tamper_detection(self):
        state = S.empty_state()
        create_watch(state)
        S.t_watch_evaluate(
            state, {"watch_id": "watch-main", "as_of": "2026-10-25T12:00:00Z"})
        out = S.t_receipt_list(state, {})
        self.assertTrue(out["chain_valid"])
        self.assertTrue(S.verify_receipt_chain(state["receipts"]))
        copied = copy.deepcopy(state["receipts"])
        copied[0]["detail"]["ceiling_all_in"] = 1
        self.assertFalse(S.verify_receipt_chain(copied))

    def test_transport(self):
        response = S.handle({"jsonrpc": "2.0", "id": 1,
                             "method": "initialize",
                             "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(response["result"]["serverInfo"]["name"],
                         "eclipse-marquee")
        response = S.handle({"jsonrpc": "2.0", "id": 2,
                             "method": "tools/list"})
        self.assertEqual({tool["name"] for tool in response["result"]["tools"]},
                         self.EXPECTED)


if __name__ == "__main__":
    unittest.main()
