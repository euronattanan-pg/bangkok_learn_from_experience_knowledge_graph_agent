"""Browser regressions with routed APIs: no database, credentials, or live writes."""
import json
import os
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from lfe.schema import FIELDS, QUESTIONS, normalize_answers


ROOT = Path(__file__).resolve().parent.parent


class FrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            options = {"headless": True}
            if os.environ.get("LFE_TEST_BROWSER_CHANNEL"):
                options["channel"] = os.environ["LFE_TEST_BROWSER_CHANNEL"]
            cls.browser = cls.playwright.chromium.launch(**options)
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("dialog", lambda dialog: dialog.accept())
        self.cases = {
            key: {"id": key, "status": "draft", "revision": 1, "is_sample": False,
                  "transcript": "", "answers": normalize_answers({"title": title}), "evidence": {}}
            for key, title in (("case-a", "Case A"), ("case-b", "Case B"))
        }
        self.failure_status = None
        self.fail_refresh = False
        self.saved_requests = []
        self.context.route("**/*", self.route)
        self.page.add_init_script("if (!localStorage.getItem('lfeDraft')) localStorage.setItem('lfeDraft', 'case-a')")
        self.page.goto("http://127.0.0.1:8000/")
        self.page.wait_for_function("document.getElementById('status').textContent.includes('case-a')")
        self.page.wait_for_function("!document.getElementById('create').disabled")

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def route(self, route):
        path = route.request.url.split(":8000", 1)[-1]
        if path in ("/", "/app.js", "/style.css"):
            filename = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[path]
            mime = {"/": "text/html", "/app.js": "text/javascript", "/style.css": "text/css"}[path]
            return route.fulfill(body=(ROOT / "static" / filename).read_bytes(), content_type=mime)
        if path == "/api/schema":
            result = {"fields": FIELDS, "questions": [
                {"number": i, "label": label, "fields": fields}
                for i, (label, fields) in enumerate(QUESTIONS, 1)]}
        elif path == "/api/connection":
            result = {"configured": True, "mock_uploads_allowed": False, "message": "Test configuration"}
        elif path == "/api/samples":
            result = {"samples": []}
        elif path in ("/api/drafts", "/api/pending-upload", "/api/pending", "/api/history"):
            statuses = {"/api/drafts": ("draft",), "/api/pending": ("pending",),
                        "/api/pending-upload": ("approved", "writing", "upload_failed"),
                        "/api/history": ("approved", "saved", "upload_failed")}[path]
            result = {"cases": [dict(item, title=item["answers"]["title"]) for item in self.cases.values()
                                if item["status"] in statuses]}
        elif path.startswith("/api/drafts/"):
            parts = path.split("/")
            item = self.cases[parts[3]]
            if len(parts) == 4:
                if self.fail_refresh:
                    return route.fulfill(status=503, json={"error": "Refresh unavailable"})
                result = item
            elif parts[4] == "save":
                self.saved_requests.append(route.request.post_data_json)
                item["status"] = self.failure_status or "saved"
                item["revision"] += 2
                if self.failure_status:
                    return route.fulfill(status=503, json={"error": "Upload rejected"})
                result = item
            elif parts[4] == "update":
                payload = route.request.post_data_json
                item.update(answers=payload["answers"], evidence=payload["evidence"], status="draft",
                            revision=item["revision"] + 1)
                result = item
            else:
                raise AssertionError(f"Unexpected API action: {path}")
        else:
            raise AssertionError(f"Unexpected request: {path}")
        route.fulfill(json=result)

    def select_case(self, case_id):
        self.page.evaluate("""item => {
            draft = item;
            editGeneration++;
            render();
        }""", self.cases[case_id])

    def defer(self, suffix):
        self.page.evaluate("""suffix => {
            const original = window.fetch;
            window.fetch = (url, options) => {
                if (url.endsWith(suffix)) {
                    window.deferredPayload = options?.body ? JSON.parse(options.body) : null;
                    return new Promise(resolve => { window.finishRequest = (item, status = 200) =>
                        resolve(new Response(JSON.stringify(item), {status})); });
                }
                return original(url, options);
            };
        }""", suffix)

    def test_queue_upload_failure_refreshes_selected_revision_and_retry_controls(self):
        for status in ("draft", "approved", "upload_failed"):
            with self.subTest(status=status):
                self.cases["case-a"].update(status="approved", revision=1)
                self.failure_status = status
                self.select_case("case-a")
                self.page.locator("#tab-button-upload").click()
                self.page.locator("#upload-list .primary").click()
                self.page.wait_for_function("!mutationPending")
                self.page.wait_for_function("document.getElementById('error').textContent === 'Upload rejected'")
                self.assertEqual(self.page.evaluate("draft.status"), status)
                self.assertEqual(self.page.evaluate("draft.revision"), 3)
                self.assertEqual(self.page.locator("#field-title").is_disabled(), status == "upload_failed")
                self.assertEqual(self.page.locator("#save").is_disabled(), status == "draft")
                self.assertEqual(self.page.locator("#upload-list .primary").count(), 0 if status == "draft" else 1)

    def test_queue_upload_refresh_does_not_replace_later_selected_case(self):
        self.cases["case-a"]["status"] = "approved"
        self.select_case("case-a")
        self.page.locator("#tab-button-upload").click()
        self.defer("/save")
        self.page.locator("#upload-list .primary").click()
        self.select_case("case-b")
        self.page.evaluate("window.finishRequest({...draft, id: 'case-a', status: 'saved'})")
        self.page.wait_for_function("!mutationPending")
        self.assertEqual(self.page.evaluate("draft.id"), "case-b")
        self.assertEqual(self.page.locator("#field-title").input_value(), "Case B")

    def test_failed_queue_refresh_preserves_different_selected_case(self):
        self.cases["case-a"]["status"] = "approved"
        self.select_case("case-a")
        self.page.locator("#tab-button-upload").click()
        self.defer("/save")
        self.page.locator("#upload-list .primary").click()
        self.select_case("case-b")
        self.cases["case-a"].update(status="upload_failed", revision=3)
        self.page.evaluate("window.finishRequest({error: 'Lost acknowledgement'}, 503)")
        self.page.wait_for_function("!mutationPending")
        self.assertEqual(self.page.evaluate("draft.id"), "case-b")
        self.assertEqual(self.page.locator("#field-title").input_value(), "Case B")
        self.assertFalse(self.page.locator("#field-title").is_disabled())

    def test_failed_queue_refresh_retains_later_input_but_locks_unknown_upload(self):
        self.cases["case-a"]["status"] = "approved"
        self.select_case("case-a")
        self.page.locator("#tab-button-upload").click()
        self.defer("/save")
        self.page.locator("#upload-list .primary").click()
        self.page.evaluate("""() => {
            document.getElementById('field-title').value = 'Later input';
            editGeneration++;
        }""")
        self.cases["case-a"].update(status="upload_failed", revision=3)
        self.page.evaluate("window.finishRequest({error: 'Lost acknowledgement'}, 503)")
        self.page.wait_for_function("!mutationPending")
        self.assertEqual(self.page.locator("#field-title").input_value(), "Later input")
        self.assertEqual(self.page.evaluate("draft.revision"), 3)
        self.assertTrue(self.page.locator("#field-title").is_disabled())

    def test_failed_upload_and_failed_status_refresh_disable_stale_retry(self):
        self.cases["case-a"]["status"] = "approved"
        self.select_case("case-a")
        self.failure_status = "upload_failed"
        self.fail_refresh = True
        self.page.locator("#tab-button-upload").click()
        self.page.locator("#upload-list .primary").click()
        self.page.wait_for_function("!mutationPending")
        self.assertIn("could not be refreshed", self.page.locator("#error").inner_text())
        self.assertTrue(self.page.locator("#save").is_disabled())

    def test_mutation_locks_typing_and_switching_and_restores_correct_controls(self):
        self.defer("/update")
        self.page.locator("#update").click()
        self.assertTrue(self.page.locator("#field-title").is_disabled())
        self.assertTrue(self.page.locator("#create").is_disabled())
        self.assertTrue(self.page.locator("#tab-button-drafts").is_disabled())
        updated = dict(self.cases["case-a"], revision=2)
        self.page.evaluate("item => window.finishRequest(item)", updated)
        self.page.wait_for_function("!mutationPending")
        self.assertFalse(self.page.locator("#field-title").is_disabled())
        self.assertFalse(self.page.locator("#submit").is_disabled())
        self.assertTrue(self.page.locator("#save").is_disabled())

    def test_late_save_preserves_later_edits_and_advances_revision_only(self):
        self.defer("/update")
        self.page.locator("#update").click()
        # Simulate an edit arriving from another client-side event while awaiting the response.
        self.page.evaluate("""() => {
            const input = document.getElementById('field-title');
            input.value = 'Later edit';
            input.dispatchEvent(new Event('input'));
        }""")
        updated = dict(self.cases["case-a"], revision=2)
        self.page.evaluate("item => window.finishRequest(item)", updated)
        self.page.wait_for_function("!mutationPending")
        self.assertEqual(self.page.locator("#field-title").input_value(), "Later edit")
        self.assertEqual(self.page.evaluate("draft.revision"), 2)
        self.assertTrue(self.page.evaluate("hasChanges()"))

    def test_late_save_response_cannot_replace_different_selected_case(self):
        self.defer("/update")
        self.page.locator("#update").click()
        self.select_case("case-b")
        self.page.evaluate("item => window.finishRequest(item)", dict(self.cases["case-a"], revision=2))
        self.page.wait_for_function("!mutationPending")
        self.assertEqual(self.page.evaluate("draft.id"), "case-b")
        self.assertEqual(self.page.locator("#field-title").input_value(), "Case B")

    def test_saved_draft_list_resumes_case_that_is_not_the_last_open_case(self):
        self.select_case("case-b")
        self.page.evaluate("localStorage.setItem('lfeDraft', 'case-b')")
        self.page.reload()
        self.page.wait_for_function("!mutationPending && draft && draft.id === 'case-b'")
        self.page.locator("#tab-button-drafts").click()
        self.page.locator("#drafts-list .case-row").filter(has_text="Case A").get_by_role("button").click()
        self.page.wait_for_function("!mutationPending && draft.id === 'case-a'")
        self.assertEqual(self.page.locator("#field-title").input_value(), "Case A")
        self.assertEqual(self.page.evaluate("localStorage.getItem('lfeDraft')"), "case-a")
