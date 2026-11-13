"""Questionnaire contract and deterministic graph mapping."""
import math
import hashlib
import json
import re
import unicodedata
import uuid

# These are the included questions only. Evidence records are separate from answers.
FIELDS = {
    "title": ("LFE Title", "text"),
    "activity": ("What happened during activity?", "text"),
    "occurred_at": ("Date & Time", "text"),
    "safety_impacted": ("Safety impacted?", "boolean"),
    "safety_details": ("Safety impact details", "text"),
    "quality_impacted": ("Product quality impacted?", "boolean"),
    "quality_details": ("Quality impact details", "text"),
    "project": ("Project", "text"),
    "product": ("Product/SKU", "text"),
    "product_context": ("Product/SKU status or details", "text"),
    "material": ("Material", "text"),
    "supplier": ("Supplier", "text"),
    "line": ("Line", "text"),
    "machine": ("Machine", "text"),
    "component": ("Machine component/part", "text"),
    "downtime_incurred": ("Downtime incurred?", "boolean"),
    "downtime_minutes": ("Total downtime (minutes)", "number"),
    "stop_count": ("Total stops", "integer"),
    "product_run": ("Total product run", "number"),
    "product_run_context": ("Product run details", "text"),
    "defect_count": ("Number of defects", "integer"),
    "defect_description": ("Defect description", "text"),
    "cause": ("Cause", "text"),
    "cause_confirmed": ("Is this cause confirmed?", "boolean"),
    "action": ("Action taken", "text"),
    "action_effective": ("Action effective?", "boolean"),
    "verification": ("How effectiveness verified", "text"),
    "attachment": ("Attachment link", "text"),
    "attachment_description": ("Attachment names or details", "text"),
}

QUESTIONS = (
    ("LFE Title", ("title",)),
    ("What happened during activity?", ("activity",)),
    ("Date & Time", ("occurred_at",)),
    ("Was safety / product quality impacted? How?", ("safety_impacted", "safety_details", "quality_impacted", "quality_details")),
    ("Project", ("project",)),
    ("Product/SKU", ("product", "product_context")),
    ("Material and supplier", ("material", "supplier")),
    ("Line", ("line",)),
    ("Machine and component/part", ("machine", "component")),
    ("Downtime incurred", ("downtime_incurred",)),
    ("Total downtime and total stops", ("downtime_minutes", "stop_count")),
    ("Total product run", ("product_run", "product_run_context")),
    ("Number of defects", ("defect_count",)),
    ("Defect description", ("defect_description",)),
    ("Cause and action taken", ("cause", "cause_confirmed", "action")),
    ("Action effective", ("action_effective",)),
    ("How effectiveness verified", ("verification",)),
    ("Attachment", ("attachment", "attachment_description")),
)


def normalize_answers(answers):
    if not isinstance(answers, dict) or set(answers) - set(FIELDS):
        raise ValueError("Answers must contain only included questionnaire fields.")
    result = {}
    for key, (_, kind) in FIELDS.items():
        value = answers.get(key)
        if value is None or value == "":
            result[key] = None
        elif kind == "text":
            if not isinstance(value, str):
                raise ValueError(f"{key} must be text.")
            result[key] = value.strip() or None
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true, false, or null.")
            result[key] = value
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a non-negative number.")
            if not math.isfinite(value) or value < 0 or (kind == "integer" and value != int(value)):
                raise ValueError(f"{key} must be a non-negative {kind}.")
            result[key] = int(value) if kind == "integer" else value
    return result


def normalize_evidence(evidence):
    if not isinstance(evidence, dict) or set(evidence) - set(FIELDS):
        raise ValueError("Evidence must reference included questionnaire fields.")
    result = {}
    for key, value in evidence.items():
        if not isinstance(value, str):
            raise ValueError("Evidence must be text.")
        if value.strip():
            result[key] = value.strip()
    return result


def normalized_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def identity_key(*values):
    normalized = [normalized_name(value) for value in values]
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False).encode("utf-8")).hexdigest()


ACRONYMS = frozenset(("lfe", "sku", "rca", "eo", "plc", "vat", "npi", "ctmz", "hu",
                      "ymp", "belca", "ipu", "cop", "pmp", "fop"))


def display_name(value):
    def format_word(match):
        word = match.group()
        if word.casefold() in ACRONYMS:
            return word.upper()
        if any(c.isdigit() for c in word) and word.isupper():
            return word
        return word[0].upper() + word[1:].lower()
    return re.sub(r"[^\W_]+", format_word, value, flags=re.UNICODE)


def split_items(value, *, commas=False, conjunction=False, deduplicate=False):
    """Split explicitly delimited values; double-quoted names protect delimiters."""
    if not value:
        return []
    items, current, quoted = [], [], False
    index = 0
    def finish():
        item = "".join(current).strip()
        if item:
            items.append(item)
        current.clear()
    while index < len(value):
        char = value[index]
        if quoted:
            if char == '"':
                if index + 1 < len(value) and value[index + 1] == '"':
                    current.append('"')
                    index += 1
                else:
                    quoted = False
            else:
                current.append(char)
        elif char == '"' and not "".join(current).strip():
            quoted = True
        elif char in ";\r\n" or (commas and char == ","):
            finish()
        elif (conjunction and value[index:index + 3].casefold() == "and"
              and index > 0 and value[index - 1].isspace()
              and index + 3 < len(value) and value[index + 3].isspace()):
            finish()
            index += 2
        else:
            current.append(char)
        index += 1
    if quoted:
        raise ValueError("Close the quoted item before submitting the questionnaire.")
    finish()
    if deduplicate:
        seen, unique = set(), []
        for item in items:
            key = normalized_name(item)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique
    return items


def graph_mapping(case_id, answers, evidence):
    uuid.UUID(case_id)
    a = normalize_answers(answers)
    ev = normalize_evidence(evidence)
    if not a["title"]:
        raise ValueError("A reviewed LFE title is required before approval.")
    case = {key: value for key, value in a.items() if value is not None}
    case["id"] = case_id
    case["title_key"] = identity_key(a["title"])
    case["display_name"] = display_name(a["title"])
    case["graph_schema_version"] = 2
    lists = {field: split_items(a[field], commas=field == "component",
                                conjunction=field == "component", deduplicate=True)
             for field in ("project", "product", "line", "machine", "component", "material", "supplier")}
    nodes = []
    for field, label, relation in (
        ("project", "Project", "HAS_PROJECT"), ("product", "Product", "HAS_PRODUCT"),
        ("line", "ProductionLine", "HAS_LINE"), ("machine", "Machine", "HAS_MACHINE"),
        ("component", "MachineComponent", "HAS_COMPONENT"), ("material", "Material", "HAS_MATERIAL"),
        ("supplier", "Supplier", "HAS_SUPPLIER"),
    ):
        for name in lists[field]:
            node = {"label": label, "relation": relation, "properties": {"name": display_name(name)}}
            if field in ("project", "product", "line", "material", "supplier"):
                node["identity_key"] = identity_key(name)
            elif field == "machine" and len(lists["line"]) == 1:
                node["identity_key"] = identity_key(lists["line"][0], name)
                node["properties"]["line_name"] = display_name(lists["line"][0])
            elif field == "component" and len(lists["line"]) == len(lists["machine"]) == 1:
                node["identity_key"] = identity_key(lists["line"][0], lists["machine"][0], name)
            if field == "component" and len(lists["machine"]) == 1:
                machine_index = next(i for i, existing in enumerate(nodes) if existing["label"] == "Machine")
                machine = nodes[machine_index]
                node["machine_ref"] = ({"identity_key": machine["identity_key"]} if "identity_key" in machine
                                       else {"item": machine_index})
            if field == "product" and len(lists["product"]) == 1 and a["product_context"]:
                node["relationship_properties"] = {"details": a["product_context"]}
            nodes.append(node)
    if not lists["product"] and a["product_context"]:
        nodes.append({"label": "Product", "relation": "HAS_PRODUCT",
                      "properties": {"details": a["product_context"]}})
    specs = [
        ("Issue", "HAS_ISSUE", {"description": a["activity"], "reported_cause": a["cause"]}),
        ("Defect", "HAS_DEFECT", {"description": a["defect_description"], "count": a["defect_count"]}),
        ("ConfirmedCause", "HAS_CAUSE", {"description": a["cause"] if a["cause_confirmed"] is True else None}),
        ("SafetyImpact", "HAS_SAFETY_IMPACT", {"impacted": a["safety_impacted"], "details": a["safety_details"]}),
        ("QualityImpact", "HAS_QUALITY_IMPACT", {"impacted": a["quality_impacted"], "details": a["quality_details"]}),
        ("CapacityImpact", "HAS_CAPACITY_IMPACT", {"downtime_incurred": a["downtime_incurred"], "downtime_minutes": a["downtime_minutes"], "stop_count": a["stop_count"], "product_run": a["product_run"], "product_run_details": a["product_run_context"]}),
        ("Verification", "HAS_VERIFICATION", {"description": a["verification"]}),
    ]
    for label, relation, props in specs:
        props = {key: value for key, value in props.items() if value is not None}
        if props:
            nodes.append({"label": label, "relation": relation, "properties": props})
    actions = split_items(a["action"])
    for action in actions:
        props = {"description": action}
        if len(actions) == 1 and a["action_effective"] is not None:
            props["effective"] = a["action_effective"]
        nodes.append({"label": "Action", "relation": "HAS_ACTION", "properties": props})
    if not actions and a["action_effective"] is not None:
        nodes.append({"label": "Action", "relation": "HAS_ACTION",
                      "properties": {"effective": a["action_effective"]}})
    attachments = split_items(a["attachment_description"], commas=True)
    if a["attachment"] and len(attachments) != 1:
        nodes.append({"label": "Evidence", "relation": "HAS_EVIDENCE", "properties": {"attachment": a["attachment"]}})
    for attachment in attachments:
        props = {"name": display_name(attachment), "description": attachment}
        if len(attachments) == 1 and a["attachment"]:
            props["attachment"] = a["attachment"]
        nodes.append({"label": "Evidence", "relation": "HAS_EVIDENCE", "properties": props})
    for field, text in ev.items():
        nodes.append({"label": "Evidence", "relation": "HAS_EVIDENCE",
                      "properties": {"field": field, "text": text}})
    return {"case": case, "nodes": nodes}


def graph_preview(case_id, answers, evidence):
    graph = graph_mapping(case_id, answers, evidence)
    entries = []
    for node in graph["nodes"]:
        props = node["properties"]
        name = props.get("name") or props.get("description") or props.get("attachment")
        if name:
            entries.append({"label": node["label"], "name": name,
                            "shared": "identity_key" in node,
                            "machine_linked": "machine_ref" in node})
    return {"case_name": graph["case"]["display_name"], "entries": entries}
