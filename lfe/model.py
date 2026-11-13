"""Model boundary. No credentials or model calls are made in manual mode."""
from .schema import FIELDS


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
