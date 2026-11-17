"""Model boundary. No credentials or model calls are made in manual mode."""
from typing import Protocol

from .schema import FIELDS


class ModelAdapter(Protocol):
    def extract(self, transcript: str) -> dict: ...
    def answer(self, question: str, cases: list[dict]) -> str: ...


def configured_adapter(config) -> ModelAdapter:
    provider = config.get("LFE_MODEL_PROVIDER", "manual")
    if provider == "manual":
        return ManualAdapter()
    if provider == "copilot":
        raise ValueError("Copilot inference is disabled until the organization credential, SDK integration, and authenticated VM access are verified. Use LFE_MODEL_PROVIDER=manual.")
    raise ValueError("Unsupported model provider. Use LFE_MODEL_PROVIDER=manual.")


class ManualAdapter:
    def extract(self, transcript):
        if not isinstance(transcript, str):
            raise ValueError("Transcript must be text.")
        return {"answers": {key: None for key in FIELDS}, "evidence": {},
                "notice": "No model configured. Enter and review the answers manually."}

    def answer(self, question, cases):
        if not cases:
            return "No matching cases found."
        lines = ["Matching cases (review the source records for details):"]
        for case in cases:
            lines.append(f"- {case.get('title', '(untitled)')} [case {case['id']}]: {case.get('activity') or 'No activity description.'}")
        return "\n".join(lines)
