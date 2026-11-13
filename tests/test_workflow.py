import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from lfe.config import neo4j_environment
from lfe.model import ManualAdapter
from lfe.neo4j_repo import (ConfigurationError, DatabaseOperationError, DuplicateTitleError, GraphSchemaError,
                            Neo4jRepository, REQUIRED_CONSTRAINTS, REQUIRED_RELATIONSHIP_CONSTRAINTS)
from lfe.samples import samples
from lfe.schema import FIELDS, QUESTIONS, display_name, graph_mapping, normalize_answers
from lfe.server import handler_for
from lfe.store import Store


class FakeRepository:
    def __init__(self):
        self.graphs = []
        self.queries = []

    def write(self, graph):
        self.graphs.append(graph)

    def search(self, question):
        self.queries.append(question)
        return [{"id": "case-1", "title": "Pump", "activity": "Stopped"}]

    def status(self):
        return {"configured": False, "message": "Neo4j is not configured."}

    def check_connection(self):
        raise ConfigurationError("Neo4j is not configured.")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "drafts.db")
        self.repo = FakeRepository()
        self.adapter = ManualAdapter()
        self.item = self.store.create("ปั๊มหยุด pump stopped", self.adapter.extract("ปั๊มหยุด pump stopped"))

    def update_case(self, case_id, answers, evidence=None):
        return self.store.update(case_id, answers, evidence or {}, self.store.get(case_id)["revision"])

    def submit_case(self, case_id):
        return self.store.submit(case_id, self.store.get(case_id)["revision"])

    def approve_case(self, case_id):
        self.submit_case(case_id)
        return self.store.approve(case_id, self.store.get(case_id)["revision"])

    def test_manual_extraction_unknown_and_excluded(self):
        self.assertTrue(all(value is None for value in self.item["answers"].values()))
        self.assertEqual(self.item["evidence"], {})
        self.assertNotIn("q10", FIELDS)
        with self.assertRaises(ValueError):
            normalize_answers({"q10": "not included"})

    def test_questionnaire_groups_all_included_fields_in_order(self):
        self.assertEqual(len(QUESTIONS), 18)
        self.assertEqual([key for _, keys in QUESTIONS for key in keys], list(FIELDS))
        self.assertEqual(QUESTIONS[2], ("Date & Time", ("occurred_at",)))
        self.assertEqual(QUESTIONS[3][1], ("safety_impacted", "safety_details", "quality_impacted", "quality_details"))
        self.assertEqual(QUESTIONS[-1][1], ("attachment", "attachment_description"))

    def test_prepared_samples_preserve_missing_values_and_details(self):
        first, second = samples()
        a, b = first["answers"], second["answers"]
        self.assertEqual(a["downtime_minutes"], 120)
        self.assertEqual(a["defect_count"], 500)
        self.assertIn("Approximately", a["product_run_context"])
        self.assertIsNone(a["occurred_at"])
        self.assertIsNone(a["safety_impacted"])
        self.assertIsNone(a["stop_count"])
        self.assertIsNone(a["attachment"])
        self.assertIn("RCA", a["attachment_description"])
        self.assertEqual(b["downtime_minutes"], 960)
        for key in ("product", "supplier", "product_run", "defect_count", "stop_count",
                    "action_effective", "verification", "attachment", "cause_confirmed"):
            self.assertIsNone(b[key], key)
        self.assertIn("non-commercial", b["product_run_context"])
        self.assertIn("25 mm", b["cause"])

    def test_sample_draft_is_marked_and_cannot_write_to_graph(self):
        draft = self.store.create("", {"answers": samples()[0]["answers"], "evidence": {}}, is_sample=True)
        self.assertTrue(draft["is_sample"])
        self.assertEqual(draft["status"], "draft")
        self.approve_case(draft["id"])
        with self.assertRaisesRegex(ValueError, "Mock uploads are disabled"):
            self.store.save(draft["id"], self.store.get(draft["id"])["revision"], self.repo)
        self.assertEqual(self.repo.graphs, [])

    def test_explicit_test_mode_allows_approved_mock_upload_and_marks_graph(self):
        draft = self.store.create("", {"answers": samples()[0]["answers"], "evidence": {}}, is_sample=True)
        self.approve_case(draft["id"])
        queue = self.store.pending_upload()
        self.assertEqual(queue[0]["id"], draft["id"])
        self.assertTrue(queue[0]["is_sample"])
        self.assertIn("quality_details", queue[0]["answers"])
        self.assertNotIn("transcript", queue[0])
        enabled = Store(self.store.path, allow_mock_uploads=True)
        result = enabled.save(draft["id"], enabled.get(draft["id"])["revision"], self.repo)
        self.assertEqual(result["status"], "saved")
        self.assertTrue(self.repo.graphs[0]["case"]["is_mock"])
        self.assertEqual(enabled.audit()[0]["action"], "upload_completed")
        self.assertEqual(enabled.pending_upload(), [])

    def test_review_approval_and_write_with_evidence(self):
        with self.assertRaises(ValueError):
            self.store.save(self.item["id"], self.item["revision"], self.repo)
        with self.assertRaises(ValueError):
            self.store.approve(self.item["id"], self.item["revision"])
        answers = {"title": "Pump stop", "activity": "Pump stopped", "downtime_incurred": False,
                   "stop_count": 0, "cause": "Seal", "cause_confirmed": True}
        self.update_case(self.item["id"], answers, {"activity": "pump stopped"})
        self.approve_case(self.item["id"])
        saved = self.store.save(self.item["id"], self.store.get(self.item["id"])["revision"], self.repo)
        self.assertEqual(saved["status"], "saved")
        self.assertEqual(saved["graph_schema_version"], 2)
        self.assertEqual(len(self.repo.graphs), 1)
        graph = self.repo.graphs[0]
        self.assertEqual(graph["case"]["stop_count"], 0)
        self.assertFalse(graph["case"]["downtime_incurred"])
        self.assertNotIn("quality_impacted", graph["case"])
        self.assertIn("ConfirmedCause", [node["label"] for node in graph["nodes"]])
        self.assertTrue(any(node["properties"].get("text") == "pump stopped" for node in graph["nodes"]))
        with self.assertRaises(ValueError):
            self.store.update(self.item["id"], answers, {}, saved["revision"])
        with self.assertRaises(ValueError):
            self.store.save(self.item["id"], saved["revision"], self.repo)

    def test_edits_invalidate_approval_and_failure_allows_retry(self):
        case_id = self.item["id"]
        self.update_case(case_id, {"title": "Test"})
        self.approve_case(case_id)
        self.update_case(case_id, {"title": "Changed"})
        with self.assertRaises(ValueError):
            self.store.save(case_id, self.store.get(case_id)["revision"], self.repo)
        self.approve_case(case_id)
        class Failing:
            def write(self, graph):
                raise RuntimeError("failure")
        with self.assertRaises(RuntimeError):
            self.store.save(case_id, self.store.get(case_id)["revision"], Failing())
        self.assertEqual(self.store.get(case_id)["status"], "upload_failed")
        self.assertEqual(self.store.audit()[0]["action"], "upload_failed")
        self.assertEqual(self.store.history()[0]["status"], "upload_failed")
        self.assertEqual(self.store.save(case_id, self.store.get(case_id)["revision"], self.repo)["status"], "saved")

    def test_pending_history_audit_and_restart(self):
        case_id = self.item["id"]
        self.update_case(case_id, {"title": "Case", "activity": "private transcript excerpt"})
        pending = self.submit_case(case_id)
        self.assertEqual([x["id"] for x in self.store.pending()], [case_id])
        approved = self.store.approve(case_id, pending["revision"])
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.history()[0]["status"], "approved")
        changed = self.store.update(case_id, {"title": "Revised"}, {}, approved["revision"])
        self.assertEqual(changed["status"], "draft")
        self.assertEqual(self.store.history()[0]["status"], "draft")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.approve(case_id, pending["revision"])
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.update(case_id, {"title": "Stale edit"}, {}, approved["revision"])
        reopened = Store(self.store.path)
        self.assertEqual(reopened.history()[0]["status"], "draft")
        audit = reopened.audit()
        self.assertEqual([e["action"] for e in reversed(audit)],
                         ["draft_created", "review_updated", "submitted", "approved", "approval_invalidated"])
        self.assertTrue(all(e["occurred_at"].endswith("Z") and e["actor"] is None for e in audit))
        self.assertNotIn("private transcript excerpt", json.dumps(audit))

    def test_audit_and_transition_are_atomic(self):
        case_id = self.item["id"]
        draft = self.update_case(case_id, {"title": "Atomic"})
        with self.store.connect() as db:
            db.execute("""CREATE TRIGGER block_submission BEFORE INSERT ON audit_events
                          WHEN NEW.action='submitted' BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.submit(case_id, draft["revision"])
        self.assertEqual(self.store.get(case_id)["status"], "draft")
        self.assertEqual(self.store.get(case_id)["revision"], draft["revision"])

    def test_interrupted_upload_is_recorded_and_edit_blocked(self):
        case_id = self.item["id"]
        self.update_case(case_id, {"title": "Recovery"})
        self.approve_case(case_id)
        with self.store.connect() as db:
            db.execute("UPDATE drafts SET status='writing' WHERE id=?", (case_id,))
        reopened = Store(self.store.path)
        item = reopened.get(case_id)
        self.assertEqual(item["status"], "upload_failed")
        self.assertEqual(reopened.audit()[0]["action"], "upload_interrupted")
        with self.assertRaises(ValueError):
            reopened.update(case_id, {"title": "Changed"}, {}, item["revision"])

    def test_legacy_saved_case_is_preserved_in_history(self):
        path = Path(self.temp.name) / "legacy.db"
        case_id = str(uuid.uuid4())
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute("CREATE TABLE drafts (id TEXT PRIMARY KEY, transcript TEXT NOT NULL, answers TEXT NOT NULL, evidence TEXT NOT NULL, status TEXT NOT NULL)")
                db.execute("INSERT INTO drafts VALUES (?, ?, ?, ?, ?)",
                           (case_id, "legacy transcript", json.dumps({"title": "Existing"}), "{}", "saved"))
        store = Store(path)
        self.assertEqual(store.history()[0]["title"], "Existing")
        self.assertEqual(store.get(case_id)["status"], "saved")
        self.assertIsNone(store.history()[0]["graph_schema_version"])
        self.assertEqual(store.audit()[0]["action"], "legacy_imported")
        self.assertNotIn("legacy transcript", json.dumps(store.audit()))

    def test_titles_are_unique_across_local_cases_and_revisions(self):
        self.update_case(self.item["id"], {"title": "  Ｐｕｍｐ   Stop "})
        second = self.store.create("", {"answers": {}, "evidence": {}})
        with self.assertRaisesRegex(ValueError, "already has this title"):
            self.store.update(second["id"], {"title": "pump stop"}, {}, second["revision"])
        with self.assertRaisesRegex(ValueError, "already has this title"):
            self.store.create("", {"answers": {"title": "PUMP STOP"}, "evidence": {}})
        self.assertEqual(self.store.get(second["id"])["answers"]["title"], None)
        self.update_case(self.item["id"], {"title": "pump stop"})

    def test_concurrent_local_duplicate_titles_are_serialized(self):
        barrier = threading.Barrier(2)
        results = []
        def create():
            barrier.wait()
            try:
                self.store.create("", {"answers": {"title": "Concurrent"}, "evidence": {}})
                results.append("created")
            except ValueError:
                results.append("duplicate")
        threads = [threading.Thread(target=create) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(results, ["created", "duplicate"])

    def test_remote_duplicate_invalidates_approval_but_preserves_review(self):
        case_id = self.item["id"]
        self.update_case(case_id, {"title": "Conflict"})
        self.approve_case(case_id)
        class DuplicateRepository:
            def write(self, graph):
                raise DuplicateTitleError("Another LFE case already has this title.")
        with self.assertRaises(DuplicateTitleError):
            self.store.save(case_id, self.store.get(case_id)["revision"], DuplicateRepository())
        item = self.store.get(case_id)
        self.assertEqual(item["status"], "draft")
        self.assertEqual(item["answers"]["title"], "Conflict")
        self.assertEqual(self.store.audit()[0]["action"], "duplicate_title_rejected")
        self.update_case(case_id, {"title": "Unique"})

    def test_reset_marks_old_uploads_unverified_without_deleting_history(self):
        case_id = self.item["id"]
        self.update_case(case_id, {"title": "Old case"})
        self.approve_case(case_id)
        self.store.save(case_id, self.store.get(case_id)["revision"], self.repo)
        with self.assertRaisesRegex(ValueError, "history changed"):
            self.store.record_target_reset("test-db", {"another-case"})
        self.assertEqual(self.store.get(case_id)["status"], "saved")
        self.assertEqual(self.store.record_target_reset("test-db", {case_id}), 1)
        self.assertEqual(self.store.get(case_id)["status"], "upload_unverified")
        self.assertEqual(self.store.history()[0]["id"], case_id)
        self.assertEqual(self.store.audit()[0]["case_id"], "database:test-db")
        replacement = self.store.create("", {"answers": {"title": "Old case"}, "evidence": {}})
        self.assertEqual(replacement["status"], "draft")

    def test_graph_shared_names_scoping_and_relationship_details(self):
        first = graph_mapping(str(uuid.uuid4()), {
            "title": "One", "project": "Project A", "line": "B7", "machine": "Capper",
            "material": "Pump Cap", "supplier": "YMP", "product": "Bottle",
            "product_context": "Case one details", "component": "Chute",
        }, {})
        second = graph_mapping(str(uuid.uuid4()), {
            "title": "Two", "project": " project a ", "line": "b7", "machine": "CAPPER",
            "material": "Ｐｕｍｐ   Ｃａｐ", "supplier": "ymp", "product": "bottle",
            "product_context": "Case two details", "component": "Chute",
        }, {})
        a = {node["label"]: node for node in first["nodes"]}
        b = {node["label"]: node for node in second["nodes"]}
        for label in ("Project", "ProductionLine", "Machine", "Material", "Supplier", "Product"):
            self.assertEqual(a[label]["identity_key"], b[label]["identity_key"], label)
        self.assertEqual(a["MachineComponent"]["identity_key"], b["MachineComponent"]["identity_key"])
        self.assertEqual(a["MachineComponent"]["machine_ref"]["identity_key"], a["Machine"]["identity_key"])
        self.assertNotIn("details", a["Product"]["properties"])
        self.assertEqual(a["Product"]["relationship_properties"]["details"], "Case one details")
        self.assertEqual(b["Product"]["relationship_properties"]["details"], "Case two details")
        different = graph_mapping(str(uuid.uuid4()), {"title": "Three", "line": "B8", "machine": "Capper"}, {})
        isolated = graph_mapping(str(uuid.uuid4()), {"title": "Four", "machine": "Capper"}, {})
        self.assertNotEqual(a["Machine"]["identity_key"], next(n for n in different["nodes"] if n["label"] == "Machine")["identity_key"])
        self.assertNotIn("identity_key", next(n for n in isolated["nodes"] if n["label"] == "Machine"))

    def test_unknown_cause_not_promoted_and_numeric_validation(self):
        graph = graph_mapping(str(uuid.uuid4()), {"title": "Case", "cause": "Possible seal"}, {})
        self.assertNotIn("ConfirmedCause", [node["label"] for node in graph["nodes"]])
        for invalid in (-1, 1.5, True, float("nan")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_answers({"stop_count": invalid})

    def test_no_connection_without_credentials(self):
        with self.assertRaises(ConfigurationError):
            Neo4jRepository({}).driver()

    def test_blank_database_uses_default(self):
        repo = Neo4jRepository({"NEO4J_DATABASE": ""})
        self.assertEqual(repo.database, "neo4j")

    def test_explicit_env_file_and_process_precedence(self):
        path = Path(self.temp.name) / ".env_dev"
        path.write_text("NEO4J_URI='neo4j+s://example.invalid'\nNEO4J_USERNAME='local-user'\n"
                        "NEO4J_PASSWORD='dummy$#value'\nNEO4J_DATABASE='local-db'\n", encoding="utf-8")
        self.assertEqual(neo4j_environment(False, {}, self.temp.name), {})
        config = neo4j_environment(True, {"NEO4J_USERNAME": "process-user"}, self.temp.name)
        self.assertEqual(config["NEO4J_PASSWORD"], "dummy$#value")
        self.assertEqual(config["NEO4J_USERNAME"], "process-user")
        self.assertEqual(config["NEO4J_DATABASE"], "local-db")
        path.write_text("invalid setting with dummy-secret\n", encoding="utf-8")
        with self.assertRaises(ValueError) as error:
            neo4j_environment(True, {}, self.temp.name)
        self.assertNotIn("dummy-secret", str(error.exception))

    def test_mocked_driver_read_check_and_approved_write(self):
        repo = Neo4jRepository({"NEO4J_URI": "neo4j+s://example.invalid",
                                "NEO4J_USERNAME": "user", "NEO4J_PASSWORD": "dummy-secret"})
        driver, session, tx = MagicMock(), MagicMock(), MagicMock()
        driver.__enter__.return_value = driver
        driver.session.return_value.__enter__.return_value = session
        tx.run.return_value.single.return_value = {"ok": 1}
        session.execute_read.side_effect = lambda operation: operation(tx)
        with patch("neo4j.GraphDatabase.driver", return_value=driver) as factory:
            self.assertTrue(repo.check_connection()["connected"])
            factory.assert_called_with("neo4j+s://example.invalid", auth=("user", "dummy-secret"))
            tx.run.assert_called_once_with("RETURN 1 AS ok")
            driver.verify_connectivity.assert_called_once()
            driver.session.assert_called_with(database="neo4j", default_access_mode="READ")
            self.update_case(self.item["id"], {"title": "Review"})
            self.approve_case(self.item["id"])
            self.store.save(self.item["id"], self.store.get(self.item["id"])["revision"], repo)
            session.execute_write.assert_called_once()
        with patch("neo4j.GraphDatabase.driver", side_effect=ValueError("dummy-secret")):
            with self.assertRaises(DatabaseOperationError) as error:
                repo.check_connection()
        self.assertNotIn("dummy-secret", str(error.exception))

    def test_backend_queries_are_fixed_and_parameterized(self):
        class Result:
            def __init__(self, rows=(), single=None):
                self.rows, self.record = rows, single
            def consume(self): pass
            def single(self): return self.record
            def __iter__(self): return iter(self.rows)
        class Tx:
            def __init__(self): self.calls = []
            def run(self, query, **params):
                self.calls.append((query, params))
                if query.startswith("SHOW CONSTRAINTS"):
                    return Result([{"entityType": "NODE", "type": "NODE_PROPERTY_UNIQUENESS",
                                    "labelsOrTypes": [label], "properties": [prop]}
                                   for _, label, prop in REQUIRED_CONSTRAINTS] +
                                  [{"entityType": "RELATIONSHIP", "type": "RELATIONSHIP_PROPERTY_UNIQUENESS",
                                    "labelsOrTypes": [relation], "properties": [prop]}
                                   for _, relation, prop in REQUIRED_RELATIONSHIP_CONSTRAINTS])
                if "count(c)" in query:
                    return Result(single={"count": 0})
                if "title_key: $title_key" in query:
                    return Result()
                return Result() if "RETURN" not in query else []
        tx = Tx()
        graph = graph_mapping(str(uuid.uuid4()), {"title": "Case", "activity": "x' MATCH (n) DETACH DELETE n"}, {})
        Neo4jRepository._write_transaction(tx, graph)
        self.assertNotIn("DETACH DELETE", " ".join(query for query, _ in tx.calls))
        tx = Tx()
        Neo4jRepository._search_transaction(tx, "MATCH (n) DELETE n")
        self.assertNotIn("DELETE", tx.calls[0][0])
        self.assertEqual(tx.calls[0][1]["terms"], ["match", "(n)", "delete"])

    def test_missing_graph_constraints_fail_closed(self):
        tx = MagicMock()
        tx.run.return_value = []
        graph = graph_mapping(str(uuid.uuid4()), {"title": "Case"}, {})
        with self.assertRaisesRegex(DatabaseOperationError, "constraints are missing"):
            Neo4jRepository._write_transaction(tx, graph)
        self.assertEqual(tx.run.call_count, 1)
        node_constraints = [{"entityType": "NODE", "type": "NODE_PROPERTY_UNIQUENESS",
                             "labelsOrTypes": [label], "properties": [prop]}
                            for _, label, prop in REQUIRED_CONSTRAINTS]
        tx = MagicMock()
        tx.run.return_value.__iter__.return_value = node_constraints
        with self.assertRaisesRegex(GraphSchemaError, "constraints are missing"):
            Neo4jRepository._write_transaction(tx, graph)
        self.assertEqual(tx.run.call_count, 1)

    def test_shared_merge_keeps_case_specific_relationship_properties(self):
        first = graph_mapping(str(uuid.uuid4()), {"title": "First", "product": "Bottle",
                                                 "product_context": "First context"}, {})
        second = graph_mapping(str(uuid.uuid4()), {"title": "Second", "product": "bottle",
                                                  "product_context": "Second context"}, {})
        tx = MagicMock()
        tx.run.return_value.single.return_value = {"count": 0}
        with patch.object(Neo4jRepository, "_require_constraints"), \
             patch.object(Neo4jRepository, "_duplicate_title", return_value=False):
            Neo4jRepository._write_transaction(tx, first)
            Neo4jRepository._write_transaction(tx, second)
        calls = [call for call in tx.run.call_args_list if "MERGE (n:Product" in call.args[0]]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs["identity_key"], calls[1].kwargs["identity_key"])
        self.assertIn("ON CREATE SET n", calls[0].args[0])
        self.assertEqual(calls[0].kwargs["relation_props"], {"details": "First context"})
        self.assertEqual(calls[1].kwargs["relation_props"], {"details": "Second context"})

    def test_components_split_and_share_only_with_machine_and_line(self):
        first = samples()[0]["answers"]
        graph = graph_mapping(str(uuid.uuid4()), first, {"component": "Chute, inner guide, air rejector"})
        components = [n for n in graph["nodes"] if n["label"] == "MachineComponent"]
        self.assertEqual([n["properties"]["name"] for n in components], ["Chute", "Inner Guide", "Air Rejector"])
        self.assertEqual(graph["case"]["component"], first["component"])
        self.assertTrue(any(n["properties"].get("text") == first["component"] for n in graph["nodes"]))
        machine = next(n for n in graph["nodes"] if n["label"] == "Machine")
        self.assertTrue(all(n["machine_ref"]["identity_key"] == machine["identity_key"] for n in components))
        another = graph_mapping(str(uuid.uuid4()), {"title": "Another", "line": "b7",
                                "machine": "capping machine", "component": "INNER GUIDE"}, {})
        self.assertEqual(components[1]["identity_key"],
                         next(n for n in another["nodes"] if n["label"] == "MachineComponent")["identity_key"])
        different = graph_mapping(str(uuid.uuid4()), {"title": "Different", "line": "B7",
                                  "machine": "Labeler", "component": "inner guide"}, {})
        self.assertNotEqual(components[1]["identity_key"],
                            next(n for n in different["nodes"] if n["label"] == "MachineComponent")["identity_key"])
        ambiguous = graph_mapping(str(uuid.uuid4()), {"title": "Ambiguous", "line": "B7",
                                  "machine": "Capper; Labeler", "component": "chute"}, {})
        component = next(n for n in ambiguous["nodes"] if n["label"] == "MachineComponent")
        self.assertNotIn("identity_key", component)
        self.assertNotIn("machine_ref", component)
        no_line = graph_mapping(str(uuid.uuid4()), {"title": "Unscoped", "machine": "Capper", "component": "chute"}, {})
        component = next(n for n in no_line["nodes"] if n["label"] == "MachineComponent")
        self.assertNotIn("identity_key", component)
        self.assertIn("item", component["machine_ref"])
        second = graph_mapping(str(uuid.uuid4()), samples()[1]["answers"], {})
        self.assertEqual([n["properties"]["name"] for n in second["nodes"] if n["label"] == "MachineComponent"],
                         ["Seal Jaw", "Film-Feeding Mechanism"])

    def test_samples_split_actions_and_attachment_names_without_inventing_links(self):
        first = samples()[0]["answers"]
        graph = graph_mapping(str(uuid.uuid4()), first, {})
        actions = [n["properties"] for n in graph["nodes"] if n["label"] == "Action"]
        evidence = [n["properties"] for n in graph["nodes"] if n["label"] == "Evidence"]
        self.assertEqual(len(actions), 3)
        self.assertTrue(all("effective" not in action for action in actions))
        self.assertTrue(graph["case"]["action_effective"])
        self.assertEqual([e["name"] for e in evidence], ["Supplier Quality Investigation Report", "RCA", "EO Sample Comparison Records"])
        self.assertTrue(all("attachment" not in e for e in evidence))
        self.assertEqual(graph["case"]["attachment_description"], first["attachment_description"])
        graph = graph_mapping(str(uuid.uuid4()), {"title": "Example", "attachment": "https://example.invalid",
                              "attachment_description": "Photo A, Photo B"}, {})
        evidence = [n["properties"] for n in graph["nodes"] if n["label"] == "Evidence"]
        self.assertEqual(sum("attachment" in e for e in evidence), 1)
        self.assertTrue(any(e == {"attachment": "https://example.invalid"} for e in evidence))

    def test_explicit_entity_lists_and_quoted_names(self):
        graph = graph_mapping(str(uuid.uuid4()), {"title": "Lists", "project": "First; Second",
                              "material": '"Pump; Assembly"; Label', "line": "B7",
                              "machine": "Capper", "component": '"Guide and Chute"; air REJECTOR',
                              "supplier": "Procter and Gamble", "activity": "Noise, and then a stop."}, {})
        names = lambda label: [n["properties"]["name"] for n in graph["nodes"] if n["label"] == label]
        self.assertEqual(names("Project"), ["First", "Second"])
        self.assertEqual(names("Material"), ["Pump; Assembly", "Label"])
        self.assertEqual(names("MachineComponent"), ["Guide And Chute", "Air Rejector"])
        self.assertEqual(names("Supplier"), ["Procter And Gamble"])
        self.assertEqual(len([n for n in graph["nodes"] if n["label"] == "Issue"]), 1)
        with self.assertRaisesRegex(ValueError, "quoted item"):
            graph_mapping(str(uuid.uuid4()), {"title": "Bad", "component": '"unclosed'}, {})

    def test_display_names_preserve_recognized_acronyms_and_original_answers(self):
        self.assertEqual(display_name("PUMP CAPPER plc rca eo sku CTMZ-HU VAT NPI"),
                         "Pump Capper PLC RCA EO SKU CTMZ-HU VAT NPI")
        graph = graph_mapping(str(uuid.uuid4()), {"title": "A test with PLC",
                              "machine": "PUMP CAPPER PLC"}, {})
        self.assertEqual(graph["case"]["title"], "A test with PLC")
        self.assertEqual(graph["case"]["display_name"], "A Test With PLC")
        self.assertEqual(next(n for n in graph["nodes"] if n["label"] == "Machine")["properties"]["name"],
                         "Pump Capper PLC")

    def test_graph_writer_merges_scoped_components_and_machine_edges(self):
        graph = graph_mapping(str(uuid.uuid4()), samples()[0]["answers"], {})
        other = graph_mapping(str(uuid.uuid4()), {"title": "Another", "line": "B7",
                              "machine": "Capping Machine", "component": "Inner Guide"}, {})
        tx = MagicMock()
        tx.run.return_value.single.return_value = {"count": 0}
        with patch.object(Neo4jRepository, "_require_constraints"), \
             patch.object(Neo4jRepository, "_duplicate_title", return_value=False):
            Neo4jRepository._write_transaction(tx, graph)
            Neo4jRepository._write_transaction(tx, graph)
            Neo4jRepository._write_transaction(tx, other)
        components = [c for c in tx.run.call_args_list if "MERGE (n:MachineComponent" in c.args[0]]
        edges = [c for c in tx.run.call_args_list if "MERGE (m)-[:HAS_COMPONENT {identity_key: $edge_key}]->(n)" in c.args[0]]
        self.assertEqual(len(components), 7)
        self.assertEqual(len(edges), 7)
        self.assertEqual([c.kwargs["identity_key"] for c in components[:3]],
                         [c.kwargs["identity_key"] for c in components[3:6]])
        self.assertTrue(all("machine_key" in c.kwargs and "component_key" in c.kwargs for c in edges))
        self.assertEqual([c.kwargs["edge_key"] for c in edges[:3]], [c.kwargs["edge_key"] for c in edges[3:6]])
        self.assertEqual(edges[1].kwargs["edge_key"], edges[6].kwargs["edge_key"])
        self.assertNotEqual(edges[1].kwargs["id"], edges[6].kwargs["id"])

    def test_graph_writer_links_unscoped_component_only_to_case_machine(self):
        graph = graph_mapping(str(uuid.uuid4()), {"title": "Unscoped", "machine": "Capper",
                              "component": "Chute"}, {})
        tx = MagicMock()
        tx.run.return_value.single.return_value = {"count": 0}
        with patch.object(Neo4jRepository, "_require_constraints"), \
             patch.object(Neo4jRepository, "_duplicate_title", return_value=False):
            Neo4jRepository._write_transaction(tx, graph)
        edge = next(c for c in tx.run.call_args_list if "MERGE (m)-[:HAS_COMPONENT {identity_key: $edge_key}]" in c.args[0])
        self.assertIn("machine_item", edge.kwargs)
        self.assertIn("item", edge.kwargs)
        self.assertNotIn("machine_key", edge.kwargs)
        self.assertTrue(edge.kwargs["edge_key"].startswith("machine:"))

    def test_legacy_mapping_rejected_before_graph_mutation_and_approval_preserved(self):
        case_id = self.item["id"]
        self.update_case(case_id, {"title": "Legacy guard"})
        approved = self.approve_case(case_id)
        class OldSchemaRepository:
            def write(self, graph):
                raise GraphSchemaError("Review and migrate the old graph.")
        with self.assertRaises(GraphSchemaError):
            self.store.save(case_id, approved["revision"], OldSchemaRepository())
        self.assertEqual(self.store.get(case_id)["status"], "approved")
        self.assertEqual(self.store.audit()[0]["action"], "upload_rejected_schema")
        tx = MagicMock()
        tx.run.return_value.single.return_value = {"count": 2}
        with patch.object(Neo4jRepository, "_require_constraints"):
            with self.assertRaisesRegex(GraphSchemaError, "earlier graph mapping"):
                Neo4jRepository._write_transaction(tx, graph_mapping(case_id, {"title": "Legacy guard"}, {}))
        self.assertEqual(tx.run.call_count, 1)
        self.assertNotIn("MERGE", tx.run.call_args.args[0])

    def test_same_case_retry_and_remote_title_collision(self):
        graph = graph_mapping(str(uuid.uuid4()), {"title": "Case"}, {})
        tx = MagicMock()
        constraints = [{"entityType": "NODE", "type": "NODE_PROPERTY_UNIQUENESS", "labelsOrTypes": [label],
                        "properties": [prop]} for _, label, prop in REQUIRED_CONSTRAINTS] + [
                       {"entityType": "RELATIONSHIP", "type": "RELATIONSHIP_PROPERTY_UNIQUENESS",
                        "labelsOrTypes": [relation], "properties": [prop]}
                       for _, relation, prop in REQUIRED_RELATIONSHIP_CONSTRAINTS]
        def run(query, **params):
            result = MagicMock()
            if query.startswith("SHOW CONSTRAINTS"):
                result.__iter__.return_value = constraints
            elif "count(c)" in query:
                result.single.return_value = {"count": 0}
            elif "title_key: $title_key" in query:
                result.single.return_value = None
            return result
        tx.run.side_effect = run
        Neo4jRepository._write_transaction(tx, graph)
        Neo4jRepository._write_transaction(tx, graph)
        self.assertEqual(sum("MERGE (c:LFECase" in c.args[0] for c in tx.run.call_args_list), 2)
        def duplicate_run(query, **params):
            result = run(query, **params)
            if "title_key: $title_key" in query:
                result.single.return_value = {"id": "different-case"}
            return result
        tx.run.side_effect = duplicate_run
        with self.assertRaises(DuplicateTitleError):
            Neo4jRepository._write_transaction(tx, graph)

    def test_http_workflow_and_origin_restriction(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.store, self.repo, self.adapter))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        def post(path, payload, origin="http://localhost:8000"):
            request = urllib.request.Request(url + path, data=json.dumps(payload).encode(),
                headers={"Host": "localhost:8000", "Content-Type": "application/json", "Origin": origin})
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        with self.store.connect() as db:
            before = db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
        request = urllib.request.Request(url + "/api/samples", headers={"Host": "localhost:8000"})
        with urllib.request.urlopen(request) as response:
            sample = json.load(response)["samples"][0]
        request = urllib.request.Request(url + "/api/connection", headers={"Host": "localhost:8000"})
        with urllib.request.urlopen(request) as response:
            self.assertFalse(json.load(response)["configured"])
        with self.assertRaises(urllib.error.HTTPError) as check_error:
            post("/api/connection/check", {})
        self.assertEqual(check_error.exception.code, 503)
        self.assertNotIn("dummy-secret", check_error.exception.read().decode())
        check_error.exception.close()
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0], before)
        sample_draft = post("/api/sample-drafts", {"answers": sample["answers"], "evidence": {}})
        self.assertTrue(sample_draft["is_sample"])
        request = urllib.request.Request(url + f"/api/drafts/{sample_draft['id']}/graph-preview",
                                         headers={"Host": "localhost:8000"})
        with urllib.request.urlopen(request) as response:
            preview = json.load(response)
            self.assertEqual(preview["revision"], sample_draft["revision"])
            self.assertEqual([x["name"] for x in preview["entries"] if x["label"] == "MachineComponent"],
                             ["Chute", "Inner Guide", "Air Rejector"])
            self.assertTrue(all(x["machine_linked"] for x in preview["entries"]
                                if x["label"] == "MachineComponent"))
        sample_draft = post(f"/api/drafts/{sample_draft['id']}/submit", {"revision": sample_draft["revision"]})
        sample_draft = post(f"/api/drafts/{sample_draft['id']}/approve", {"revision": sample_draft["revision"]})
        with self.assertRaises(urllib.error.HTTPError) as sample_error:
            post(f"/api/drafts/{sample_draft['id']}/save", {"revision": sample_draft["revision"]})
        self.assertEqual(sample_error.exception.code, 400)
        sample_error.exception.close()
        self.assertEqual(self.repo.graphs, [])
        created = post("/api/drafts", {"transcript": "pump stopped"})
        case_id = created["draft"]["id"]
        draft = post(f"/api/drafts/{case_id}/update", {"answers": {"title": "Pump"}, "evidence": {}, "revision": created["draft"]["revision"]})
        draft = post(f"/api/drafts/{case_id}/submit", {"revision": draft["revision"]})
        request = urllib.request.Request(url + "/api/pending", headers={"Host": "localhost:8000"})
        with urllib.request.urlopen(request) as response:
            self.assertIn(case_id, [item["id"] for item in json.load(response)["cases"]])
        draft = post(f"/api/drafts/{case_id}/approve", {"revision": draft["revision"]})
        request = urllib.request.Request(url + "/api/pending-upload", headers={"Host": "localhost:8000"})
        with urllib.request.urlopen(request) as response:
            queue = json.load(response)["cases"]
            self.assertTrue(any(item["id"] == case_id and item["answers"]["title"] == "Pump" for item in queue))
        self.assertEqual(post(f"/api/drafts/{case_id}/save", {"revision": draft["revision"]})["status"], "saved")
        request = urllib.request.Request(url + "/api/history", headers={"Host": "localhost:8000"})
        with urllib.request.urlopen(request) as response:
            history = json.load(response)["cases"]
            self.assertTrue(any(item["id"] == case_id and item["status"] == "saved" for item in history))
        request = urllib.request.Request(url + "/api/audit", headers={"Host": "localhost:8000"})
        with urllib.request.urlopen(request) as response:
            events = json.load(response)["events"]
            self.assertTrue(any(event["case_id"] == case_id and event["action"] == "upload_completed" for event in events))
        self.assertIn("[case case-1]", post("/api/qa", {"question": "pump"})["answer"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            post("/api/qa", {"question": "pump"}, origin="https://attacker.example")
        self.assertEqual(error.exception.code, 403)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
