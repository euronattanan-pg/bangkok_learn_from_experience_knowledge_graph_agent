import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from copilot import RuntimeConnection
from lfe.model import (AnswerResponse, ExtractionResponse, LocalCopilotAdapter,
                       GraphMappingResponse, ModelProviderError, ReadPlanResponse)
from lfe.schema import FIELDS, GRAPH_ENTITY_FIELDS, normalize_answers


def extraction_payload(answers=None, evidence=None):
    return {
        "answers": {**{key: None for key in FIELDS}, **(answers or {})},
        "evidence": {**{key: None for key in FIELDS}, **(evidence or {})},
    }


def graph_mapping_payload(entities=None, unresolved=None):
    return {
        "entities": {**{key: [] for key in GRAPH_ENTITY_FIELDS}, **(entities or {})},
        "unresolved": unresolved or [],
    }


class FakeSession:
    def __init__(self, client, session_id):
        self.client = client
        self.session_id = session_id

    async def send_and_wait_typed(self, prompt, response_type, timeout):
        self.client.calls.append((prompt, response_type, timeout))
        value = self.client.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        if value == "timeout":
            await asyncio.sleep(timeout + 0.02)
            raise TimeoutError()
        return response_type.model_validate(value)

    async def disconnect(self):
        self.client.disconnected.append(self.session_id)


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.sessions = []
        self.disconnected = []
        self.deleted = []
        self.options = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def create_session(self, **options):
        self.options = options
        session = FakeSession(self, options["session_id"])
        self.sessions.append(session)
        return session

    async def list_models(self):
        return [SimpleNamespace(id="account-model")]

    async def delete_session(self, session_id):
        self.deleted.append(session_id)


class ModelAdapterTests(unittest.TestCase):
    def make_adapter(self, responses, model="auto", timeout=1):
        clients = []

        def client_factory(**options):
            client = FakeClient(responses)
            client.client_options = options
            clients.append(client)
            return client

        adapter = LocalCopilotAdapter(model, timeout, client_factory=client_factory,
                                      cli_lookup=lambda _: "copilot",
                                      runtime_status=lambda: ("1.0.113", True))
        return adapter, clients

    def test_extracts_only_included_fields_with_verified_evidence_and_null_defaults(self):
        transcript = "Line 4 stopped at 10:30."
        adapter, clients = self.make_adapter([extraction_payload(
            {"title": "Line stop", "activity": "Line 4 stopped at 10:30.", "line": "Line 4"},
            {"title": "Line 4 stopped", "activity": "Line 4 stopped at 10:30.", "line": "Line 4"},
        )])
        result = adapter.extract(transcript)
        self.assertEqual(result["answers"]["title"], "Line stop")
        self.assertEqual(result["answers"]["line"], "Line 4")
        self.assertIsNone(result["answers"]["safety_impacted"])
        self.assertEqual(set(result["answers"]), set(FIELDS))
        self.assertEqual(result["evidence"]["line"], "Line 4")
        self.assertEqual(clients[0].deleted, clients[0].disconnected)

    def test_rejects_unverified_evidence_and_unknown_questionnaire_fields(self):
        adapter, _ = self.make_adapter([extraction_payload(
            {"title": "Invented"}, {"title": "not in transcript"},
        )])
        with self.assertRaisesRegex(ModelProviderError, "evidence"):
            adapter.extract("A transcript with no matching excerpt.")

        payload = extraction_payload({"title": "Case"}, {"title": "Case"})
        payload["answers"]["unlisted_question"] = "value"
        payload["evidence"]["unlisted_question"] = "Case"
        adapter, _ = self.make_adapter([payload])
        with self.assertRaisesRegex(ModelProviderError, "schema validation"):
            adapter.extract("Case")

    def test_typed_plan_isolated_per_request_and_tool_free(self):
        adapter, clients = self.make_adapter([
            {"field": "machine", "terms": ["capper"], "case_id": None},
            {"field": "project", "terms": ["project a"], "case_id": None},
        ])
        self.assertEqual(adapter.plan("Capper case"), {
            "field": "machine", "terms": ["capper"], "case_id": None,
        })
        self.assertEqual(adapter.plan("Project A cases"), {
            "field": "project", "terms": ["project a"], "case_id": None,
        })
        self.assertEqual(len(clients), 2)
        self.assertEqual(clients[0].client_options["mode"], "coding-agent")
        self.assertEqual(clients[0].client_options["github"], {"use_logged_in_user": True})
        runtime = clients[0].client_options["runtime"]
        self.assertIsInstance(runtime, type(RuntimeConnection.for_inprocess()))
        self.assertEqual(runtime.base_directory, str(Path.home() / ".copilot"))
        self.assertEqual(clients[0].options["tools"], {"available_tools": []})
        self.assertEqual(clients[0].options["github"], {"telemetry_enabled": False})
        self.assertEqual(clients[0].options["hooks"], {"enable_repository_hooks": False})
        self.assertEqual(clients[0].options["git"], {"enable_host_git_operations": False})
        self.assertEqual(clients[0].options["mcp"], {"servers": {}, "enable_apps": False})
        self.assertEqual(clients[0].options["skills"], {"enabled": False})
        self.assertEqual(clients[0].options["state"], {
            "embedding_cache_storage": "in-memory",
            "skip_embedding_retrieval": True,
            "enable_cross_session_store": False,
            "memory": {"enabled": False},
        })
        self.assertFalse(clients[0].options["enable_config_discovery"])
        self.assertNotEqual(clients[0].options["session_id"], clients[1].options["session_id"])
        self.assertTrue(all(client.deleted == client.disconnected for client in clients))

    def test_graph_mapping_is_schema_limited_and_source_grounded(self):
        answers = normalize_answers({
            "title": "Line stop", "project": "Project A; Project B",
            "component": "Chute, Inner Guide",
        })
        adapter, clients = self.make_adapter([{
            **graph_mapping_payload({
                "project": [
                    {"name": "Project A", "evidence": "Project A"},
                    {"name": "Project B", "evidence": "Project B"},
                ],
                "component": [
                    {"name": "Chute", "evidence": "Chute"},
                    {"name": "Inner Guide", "evidence": "Inner Guide"},
                ],
            }),
        }])
        proposal = adapter.map_graph(answers)
        self.assertEqual([item["name"] for item in proposal["entities"]["project"]],
                         ["Project A", "Project B"])
        self.assertEqual([item["name"] for item in proposal["entities"]["component"]],
                         ["Chute", "Inner Guide"])
        prompt = clients[0].calls[0][0]
        self.assertIn("Do not write Cypher", prompt)
        self.assertNotIn("transcript", prompt.casefold())
        self.assertIn("Project A; Project B", prompt)
        self.assertNotIn("Line stop", prompt)
        self.assertTrue(all(client.deleted == client.disconnected for client in clients))

        adapter, _ = self.make_adapter([graph_mapping_payload({
            "project": [{"name": "Invented", "evidence": "Project A"}],
        })])
        with self.assertRaisesRegex(ModelProviderError, "ungrounded graph mapping"):
            adapter.map_graph(answers)

        adapter, _ = self.make_adapter([graph_mapping_payload({
            "project": [{"name": "Project A", "evidence": "Project A"}],
        })])
        with self.assertRaisesRegex(ModelProviderError, "ungrounded graph mapping"):
            adapter.map_graph(answers)

    def test_graph_mapping_rejects_extra_schema_and_cypher_fields(self):
        with self.assertRaises(ValidationError):
            GraphMappingResponse.model_validate({
                **graph_mapping_payload({
                    "project": [{"name": "Project A", "evidence": "Project A"}],
                }),
                "cypher": "MATCH (n) DETACH DELETE n",
            })
        with self.assertRaises(ValidationError):
            GraphMappingResponse.model_validate({
                **graph_mapping_payload({"unknown_label": []}),
            })
        payload = graph_mapping_payload()
        payload["cypher"] = "MATCH (n) DETACH DELETE n"
        adapter, clients = self.make_adapter([payload])
        with self.assertRaisesRegex(ModelProviderError, "schema validation"):
            adapter.map_graph(normalize_answers({"project": "Project A"}))
        self.assertNotEqual(clients[0].sessions, [])

    def test_answer_requires_valid_case_id_citation(self):
        adapter, clients = self.make_adapter([{"answer": "The line stopped. [case case-1]"}])
        self.assertIn("[case case-1]", adapter.answer("What happened?", [
            {"id": "case-1", "title": "Line stop", "activity": "Line 4 stopped."},
        ]))
        self.assertNotIn("transcript", clients[0].calls[0][0].casefold())
        adapter, _ = self.make_adapter([{"answer": "The line stopped."}])
        with self.assertRaisesRegex(ModelProviderError, "case references"):
            adapter.answer("What happened?", [{"id": "case-1", "title": "Line stop"}])

    def test_timeout_and_auth_errors_are_sanitized(self):
        adapter, _ = self.make_adapter(["timeout"], timeout=0.01)
        with self.assertRaisesRegex(ModelProviderError, "timed out") as timeout:
            adapter.plan("find a case")
        self.assertNotIn("find a case", str(timeout.exception))

        class AuthenticationError(Exception):
            pass

        adapter, _ = self.make_adapter([AuthenticationError("secret-token-value")])
        with self.assertRaisesRegex(ModelProviderError, "copilot login") as auth:
            adapter.plan("find a case")
        self.assertNotIn("secret-token-value", str(auth.exception))

    def test_configured_model_must_be_account_available(self):
        adapter, clients = self.make_adapter([{"field": "any", "terms": ["case"], "case_id": None}],
                                             model="not-an-account-model")
        with self.assertRaisesRegex(ModelProviderError, "not available"):
            adapter.plan("find a case")
        self.assertEqual(clients[0].sessions, [])

    def test_missing_cli_requires_user_sign_in_without_echoing_credentials(self):
        adapter = LocalCopilotAdapter("auto", 1, client_factory=lambda **_: self.fail("SDK must not start"),
                                      cli_lookup=lambda _: None)
        self.assertFalse(adapter.status()["cli_available"])
        with self.assertRaisesRegex(ModelProviderError, "copilot login"):
            adapter.plan("find a case")

    def test_missing_sdk_runtime_is_reported_without_starting_or_downloading(self):
        adapter = LocalCopilotAdapter("auto", 1, client_factory=lambda **_: self.fail("SDK must not start"),
                                      cli_lookup=lambda _: "copilot",
                                      runtime_status=lambda: ("1.0.113", False))
        status = adapter.status()
        self.assertFalse(status["runtime_available"])
        self.assertIn("will not download", status["message"])
        with self.assertRaisesRegex(ModelProviderError, "no download was started"):
            adapter.plan("find a case")

    def test_response_types_reject_arbitrary_plan_or_answer_properties(self):
        with self.assertRaises(ValidationError):
            ReadPlanResponse.model_validate({"field": "any", "terms": ["pump"],
                                             "case_id": None, "cypher": "MATCH (n) DELETE n"})
        with self.assertRaises(ValidationError):
            AnswerResponse.model_validate({"answer": "ok", "query": "CREATE (n)"})
        with self.assertRaises(ValidationError):
            ExtractionResponse.model_validate({"answers": {"title": 7}, "evidence": {}})

    def test_typed_response_schemas_require_every_property(self):
        extraction_schema = ExtractionResponse.model_json_schema()
        self.assertEqual(set(extraction_schema["properties"]), set(extraction_schema["required"]))
        for name in ("AnswerFields", "EvidenceFields"):
            schema = extraction_schema["$defs"][name]
            self.assertEqual(set(schema["properties"]), set(schema["required"]))

        mapping_schema = GraphMappingResponse.model_json_schema()
        self.assertEqual(set(mapping_schema["properties"]), set(mapping_schema["required"]))
        entity_schema = mapping_schema["$defs"]["GraphEntityGroups"]
        self.assertEqual(set(entity_schema["properties"]), set(entity_schema["required"]))
        read_plan_schema = ReadPlanResponse.model_json_schema()
        self.assertEqual(set(read_plan_schema["properties"]), set(read_plan_schema["required"]))


if __name__ == "__main__":
    unittest.main()
