import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .neo4j_repo import DuplicateTitleError, GraphSchemaError
from .schema import (graph_mapping, normalize_answers, normalize_evidence,
                     normalize_graph_entity_mapping, normalized_name, preview_graph)


class Store:
    def __init__(self, path, allow_mock_uploads=False, owner=None):
        self.path = str(path)
        self.allow_mock_uploads = allow_mock_uploads
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, transcript TEXT NOT NULL, answers TEXT NOT NULL, evidence TEXT NOT NULL, status TEXT NOT NULL)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(drafts)")}
            if "is_sample" not in columns:
                db.execute("ALTER TABLE drafts ADD COLUMN is_sample INTEGER NOT NULL DEFAULT 0")
            if "revision" not in columns:
                db.execute("ALTER TABLE drafts ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            if "graph_schema_version" not in columns:
                db.execute("ALTER TABLE drafts ADD COLUMN graph_schema_version INTEGER")
            if "upload_graph" not in columns:
                db.execute("ALTER TABLE drafts ADD COLUMN upload_graph TEXT")
            if "graph_mapping_proposal" not in columns:
                db.execute("ALTER TABLE drafts ADD COLUMN graph_mapping_proposal TEXT")
            if "graph_mapping_approved" not in columns:
                db.execute("ALTER TABLE drafts ADD COLUMN graph_mapping_approved INTEGER NOT NULL DEFAULT 0")
            existing_audit = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_events'").fetchone()
            db.execute("""CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                action TEXT NOT NULL, outcome TEXT NOT NULL, from_status TEXT,
                to_status TEXT, actor TEXT)""")
            if not existing_audit:
                db.execute("""INSERT INTO audit_events (case_id, action, outcome, to_status)
                              SELECT id, 'legacy_imported', 'recorded', status FROM drafts""")
        if owner is not None:
            self.recover_interrupted(owner)

    def recover_interrupted(self, owner):
        owner.require(self.path)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            interrupted = db.execute("SELECT id FROM drafts WHERE status='writing'").fetchall()
            for row in interrupted:
                db.execute("UPDATE drafts SET status='upload_failed', revision=revision+1 WHERE id=?", (row["id"],))
                self._audit(db, row["id"], "upload_interrupted", "unknown", "writing", "upload_failed")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _audit(db, case_id, action, outcome, from_status=None, to_status=None):
        # Local mode has no authenticated identity; do not claim an actor.
        db.execute("""INSERT INTO audit_events (case_id, action, outcome, from_status, to_status)
                      VALUES (?, ?, ?, ?, ?)""",
                   (case_id, action, outcome, from_status, to_status))

    @staticmethod
    def decode(row):
        if row is None:
            raise ValueError("Draft not found.")
        item = dict(row)
        item["answers"] = normalize_answers(json.loads(item["answers"]))
        item["evidence"] = json.loads(item["evidence"])
        item["graph_mapping_proposal"] = (
            json.loads(item["graph_mapping_proposal"]) if item.get("graph_mapping_proposal") else None
        )
        item["graph_mapping_approved"] = bool(item.get("graph_mapping_approved", 0))
        item["is_sample"] = bool(item["is_sample"])
        item.pop("upload_graph", None)
        return item

    @staticmethod
    def _current(db, case_id, revision):
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("A valid draft revision is required. Reload the case.")
        item = Store.decode(db.execute("SELECT * FROM drafts WHERE id=?", (case_id,)).fetchone())
        if item["revision"] != revision:
            raise ValueError("This case changed. Reload it before continuing.")
        return item

    @staticmethod
    def _check_title(db, title, case_id=None):
        if not title:
            return
        key = normalized_name(title)
        for row in db.execute("SELECT id, answers FROM drafts WHERE status <> 'upload_unverified'"):
            existing = json.loads(row["answers"]).get("title")
            if row["id"] != case_id and existing and normalized_name(existing) == key:
                raise ValueError("An LFE case already has this title. Choose a unique title.")

    def create(self, transcript, extraction, is_sample=False):
        if not isinstance(transcript, str):
            raise ValueError("Transcript must be text.")
        case_id = str(uuid.uuid4())
        answers = normalize_answers(extraction["answers"])
        evidence = normalize_evidence(extraction["evidence"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_title(db, answers["title"])
            db.execute("INSERT INTO drafts (id, transcript, answers, evidence, status, is_sample) VALUES (?, ?, ?, ?, 'draft', ?)",
                       (case_id, transcript, json.dumps(answers), json.dumps(evidence), int(is_sample)))
            self._audit(db, case_id, "draft_created", "succeeded", None, "draft")
        return self.get(case_id)

    def get(self, case_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM drafts WHERE id=?", (case_id,)).fetchone())

    def graph_preview(self, case_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM drafts WHERE id=?", (case_id,)).fetchone()
            item = self.decode(row)
            frozen = item["status"] in ("writing", "upload_failed", "saved")
            snapshot = row["upload_graph"] if frozen else None
            if frozen and not snapshot:
                raise GraphSchemaError("This older upload has no frozen preview. Reconcile its graph mapping before retrying.")
            proposal = item["graph_mapping_proposal"]
            graph = (json.loads(snapshot) if snapshot else
                     graph_mapping(case_id, item["answers"], item["evidence"], proposal))
        return {**preview_graph(graph), "revision": item["revision"],
                "source": "frozen_upload" if snapshot else
                "copilot_proposal" if proposal else "current_mapper",
                "unresolved": proposal["unresolved"] if proposal else [],
                "mapping_approved": item["graph_mapping_approved"]}

    def graph_mapping_source(self, case_id, revision):
        with self.connect() as db:
            db.execute("BEGIN")
            item = self._current(db, case_id, revision)
            if item["status"] != "approved":
                raise ValueError("Only an approved questionnaire can be mapped for upload.")
            return {"answers": item["answers"], "revision": item["revision"]}

    def propose_graph_mapping(self, case_id, revision, proposal):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            item = self._current(db, case_id, revision)
            if item["status"] != "approved":
                raise ValueError("Only an approved questionnaire can be mapped for upload.")
            proposal = normalize_graph_entity_mapping(item["answers"], proposal)
            graph_mapping(case_id, item["answers"], item["evidence"], proposal)
            db.execute("""UPDATE drafts SET graph_mapping_proposal=?, graph_mapping_approved=0,
                          revision=revision+1
                          WHERE id=? AND revision=?""",
                       (json.dumps(proposal, ensure_ascii=False), case_id, revision))
            outcome = "needs_review" if proposal["unresolved"] else "ready_for_review"
            self._audit(db, case_id, "graph_mapping_proposed", outcome, "approved", "approved")
        return self.get(case_id)

    def confirm_graph_mapping(self, case_id, revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            item = self._current(db, case_id, revision)
            proposal = item["graph_mapping_proposal"]
            if item["status"] != "approved":
                raise ValueError("Only an approved questionnaire can have its graph mapping confirmed.")
            if not proposal:
                raise ValueError("Generate a graph mapping proposal before confirming it.")
            if proposal["unresolved"]:
                raise ValueError("Resolve the flagged graph entities in the questionnaire, then resubmit and reapprove it.")
            graph_mapping(case_id, item["answers"], item["evidence"], proposal)
            db.execute("""UPDATE drafts SET graph_mapping_approved=1, revision=revision+1
                          WHERE id=? AND revision=?""", (case_id, revision))
            self._audit(db, case_id, "graph_mapping_confirmed", "succeeded", "approved", "approved")
        return self.get(case_id)

    def record_mapping_failure(self, case_id, revision):
        with self.connect() as db:
            item = self._current(db, case_id, revision)
            self._audit(db, case_id, "graph_mapping_failed", "failed", item["status"], item["status"])

    def record_rejection(self, case_id, action):
        with self.connect() as db:
            row = db.execute("SELECT status FROM drafts WHERE id=?", (case_id,)).fetchone()
            if row:
                self._audit(db, case_id, action, "rejected", row["status"], row["status"])

    def update(self, case_id, answers, evidence, revision):
        answers = normalize_answers(answers)
        evidence = normalize_evidence(evidence)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            item = self._current(db, case_id, revision)
            if item["status"] not in ("draft", "pending", "approved"):
                raise ValueError("This case cannot be edited after an upload attempt.")
            self._check_title(db, answers["title"], case_id)
            db.execute("""UPDATE drafts SET answers=?, evidence=?, status='draft',
                          graph_mapping_proposal=NULL, graph_mapping_approved=0, revision=revision+1
                          WHERE id=?""", (json.dumps(answers), json.dumps(evidence), case_id))
            action = "approval_invalidated" if item["status"] == "approved" else "review_updated"
            self._audit(db, case_id, action, "succeeded", item["status"], "draft")
        return self.get(case_id)

    def submit(self, case_id, revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            item = self._current(db, case_id, revision)
            if item["status"] != "draft":
                raise ValueError("Only a draft can be submitted for approval.")
            graph_mapping(case_id, item["answers"], item["evidence"])
            self._check_title(db, item["answers"]["title"], case_id)
            db.execute("UPDATE drafts SET status='pending', revision=revision+1 WHERE id=?", (case_id,))
            self._audit(db, case_id, "submitted", "succeeded", "draft", "pending")
        return self.get(case_id)

    def approve(self, case_id, revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            item = self._current(db, case_id, revision)
            if item["status"] != "pending":
                raise ValueError("Submit the case for approval before approving it.")
            graph_mapping(case_id, item["answers"], item["evidence"])
            self._check_title(db, item["answers"]["title"], case_id)
            db.execute("UPDATE drafts SET status='approved', revision=revision+1 WHERE id=?", (case_id,))
            self._audit(db, case_id, "approved", "succeeded", "pending", "approved")
        return self.get(case_id)

    def save(self, case_id, revision, repository, require_mapping=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            item = self._current(db, case_id, revision)
            if item["is_sample"] and not self.allow_mock_uploads:
                raise ValueError("Mock uploads are disabled. Enable them only for a dedicated test database.")
            if item["status"] not in ("approved", "upload_failed"):
                raise ValueError("Approve this case before writing it to Neo4j.")
            if (require_mapping and item["status"] == "approved"
                    and not item["graph_mapping_approved"]):
                raise ValueError("Generate and confirm the Copilot graph mapping before uploading this approved case.")
            self._check_title(db, item["answers"]["title"], case_id)
            snapshot = db.execute("SELECT upload_graph FROM drafts WHERE id=?", (case_id,)).fetchone()["upload_graph"]
            if item["status"] == "upload_failed" and not snapshot:
                raise GraphSchemaError("This older uncertain upload has no frozen snapshot. Reconcile its stable case ID before retrying; edits remain locked.")
            if item["status"] == "upload_failed":
                graph = json.loads(snapshot)
            else:
                proposal = item["graph_mapping_proposal"] if item["graph_mapping_approved"] else None
                graph = graph_mapping(case_id, item["answers"], item["evidence"], proposal)
                if item["is_sample"]:
                    graph["case"]["is_mock"] = True
            db.execute("UPDATE drafts SET status='writing', upload_graph=?, revision=revision+1 WHERE id=?",
                       (json.dumps(graph), case_id))
            self._audit(db, case_id, "upload_started", "started", item["status"], "writing")
        try:
            repository.write(graph)
        except DuplicateTitleError:
            target = "upload_failed" if item["status"] == "upload_failed" else "draft"
            self._finish_upload(case_id, item["revision"] + 1, target, "duplicate_title_rejected", "rejected")
            if target == "upload_failed":
                raise DuplicateTitleError("This upload has an uncertain outcome. Reconcile its stable case ID in Neo4j before retrying; edits remain locked.") from None
            raise
        except GraphSchemaError:
            self._finish_upload(case_id, item["revision"] + 1, item["status"], "upload_rejected_schema", "rejected")
            raise
        except Exception:
            self._finish_upload(case_id, item["revision"] + 1, "upload_failed", "upload_failed", "unknown")
            raise
        self._finish_upload(case_id, item["revision"] + 1, "saved", "upload_completed", "succeeded",
                            graph["case"]["graph_schema_version"])
        return self.get(case_id)

    def _finish_upload(self, case_id, revision, status, action, outcome, graph_version=None):
        with self.connect() as db:
            changed = db.execute("""UPDATE drafts SET status=?, graph_schema_version=COALESCE(?,graph_schema_version),
                                    revision=revision+1 WHERE id=? AND status='writing' AND revision=?""",
                                 (status, graph_version, case_id, revision)).rowcount
            if changed != 1:
                raise RuntimeError("Upload state changed unexpectedly. Reconcile the case before retrying.")
            self._audit(db, case_id, action, outcome, "writing", status)

    def drafts(self):
        return self._list_cases("status='draft'")

    def pending(self):
        return self._list_cases("status='pending'")

    def history(self):
        return self._list_cases("""status IN ('approved','writing','saved','upload_failed','upload_unverified') OR EXISTS
            (SELECT 1 FROM audit_events a WHERE a.case_id=drafts.id AND
             (a.action='approved' OR (a.action='legacy_imported' AND a.to_status IN ('approved','saved','writing'))))""")

    def pending_upload(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM drafts WHERE status IN ('approved','writing','upload_failed') ORDER BY rowid DESC").fetchall()
            items = [self.decode(row) for row in rows]
        return [{key: item[key] for key in ("id", "status", "revision", "is_sample", "answers", "evidence",
                                            "graph_mapping_proposal", "graph_mapping_approved")}
                for item in items]

    def _list_cases(self, condition):
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM drafts WHERE {condition} ORDER BY rowid DESC").fetchall()
            cases = [self.decode(row) for row in rows]
        return [{"id": item["id"], "title": item["answers"]["title"], "status": item["status"],
                 "revision": item["revision"], "is_sample": item["is_sample"],
                 "graph_schema_version": item["graph_schema_version"]} for item in cases]

    def audit(self):
        with self.connect() as db:
            rows = db.execute("""SELECT id, case_id, occurred_at, action, outcome, from_status, to_status, actor
                                 FROM audit_events ORDER BY id DESC LIMIT 200""").fetchall()
            return [dict(row) for row in rows]

    def record_target_reset(self, database, expected_saved_ids=None):
        """Preserve old upload history without claiming its current database state."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM drafts WHERE status='saved'").fetchall()
            if expected_saved_ids is not None and {row["id"] for row in rows} != set(expected_saved_ids):
                raise ValueError("Local upload history changed. Review it before recording the database reset.")
            for row in rows:
                db.execute("UPDATE drafts SET status='upload_unverified', revision=revision+1 WHERE id=?", (row["id"],))
                self._audit(db, row["id"], "target_reset_upload_unverified", "unverified", "saved", "upload_unverified")
            self._audit(db, f"database:{database}", "target_database_cleared", "succeeded")
        return len(rows)
