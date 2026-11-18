"""Allowlisted read plans compiled to parameterized, fixed Cypher."""
import re


READ_FIELDS = {
    "title": ("title",),
    "activity": ("activity",),
    "project": ("project",),
    "product": ("product", "product_context"),
    "material": ("material",),
    "supplier": ("supplier",),
    "line": ("line",),
    "machine": ("machine", "component"),
    "cause": ("cause",),
    "action": ("action",),
    "defect": ("defect_description",),
    "impact": ("safety_details", "quality_details"),
    "any": ("title", "activity", "project", "product", "product_context", "material",
            "supplier", "line", "machine", "component", "cause", "action",
            "defect_description", "safety_details", "quality_details"),
}
_PLAN_KEYS = frozenset(("field", "terms", "case_id"))
_TERM_LIMIT = 10
_TERM_LENGTH = 120


def validate_read_plan(plan):
    if hasattr(plan, "model_dump"):
        plan = plan.model_dump()
    if not isinstance(plan, dict) or set(plan) - _PLAN_KEYS:
        raise ValueError("Read plan contains unsupported fields.")
    field = plan.get("field", "any")
    if field not in READ_FIELDS:
        raise ValueError("Read plan selected an unsupported case field.")
    terms = plan.get("terms", [])
    if not isinstance(terms, list) or len(terms) > _TERM_LIMIT:
        raise ValueError("Read plan must contain at most 10 search terms.")
    normalized_terms = []
    for term in terms:
        if not isinstance(term, str) or not term.strip() or len(term.strip()) > _TERM_LENGTH:
            raise ValueError("Read plan contains an invalid search term.")
        normalized_terms.append(term.strip().casefold())
    case_id = plan.get("case_id")
    if case_id is not None and (not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 80):
        raise ValueError("Read plan contains an invalid case ID.")
    if not normalized_terms and not case_id:
        raise ValueError("Read plan must include a case ID or at least one search term.")
    return {"field": field, "terms": normalized_terms, "case_id": case_id.strip() if case_id else None}


def compile_read_plan(plan):
    plan = validate_read_plan(plan)
    clauses = []
    params = {"terms": plan["terms"], "case_id": plan["case_id"]}
    if plan["case_id"]:
        clauses.append("c.id = $case_id")
    if plan["terms"]:
        properties = READ_FIELDS[plan["field"]]
        expressions = ", ".join(f"coalesce(c.{key}, '')" for key in properties)
        clauses.append("any(term IN $terms WHERE any(value IN [" + expressions +
                       "] WHERE toLower(value) CONTAINS term))")
    query = (
        "MATCH (c:LFECase) WHERE " + " AND ".join(f"({clause})" for clause in clauses) +
        " RETURN c.id AS id, c.title AS title, c.activity AS activity, "
        "c.occurred_at AS occurred_at, c.project AS project, c.product AS product, "
        "c.product_context AS product_context, c.material AS material, c.supplier AS supplier, "
        "c.line AS line, c.machine AS machine, c.component AS component, c.cause AS cause, "
        "c.action AS action, c.defect_description AS defect_description, "
        "c.safety_details AS safety_details, c.quality_details AS quality_details, "
        "c.downtime_minutes AS downtime_minutes, c.stop_count AS stop_count, "
        "c.product_run AS product_run, c.defect_count AS defect_count "
        "ORDER BY c.occurred_at DESC LIMIT 20"
    )
    return query, params


def question_terms(question):
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Enter a question.")
    terms = [term for term in re.findall(r"[^\W_]+", question, re.UNICODE) if len(term) > 1]
    return terms[:_TERM_LIMIT]
