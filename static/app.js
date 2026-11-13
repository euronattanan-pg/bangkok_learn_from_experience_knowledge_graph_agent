"use strict";
let fields = {};
let questions = [];
let samples = [];
let draft = null;
let connectionStatus = {configured: false, mock_uploads_allowed: false, message: "Configuration has not been checked."};
const byId = id => document.getElementById(id);
const tabNames = ["workspace", "pending", "upload", "history", "audit"];

async function request(path, data) {
  const options = data === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)
  };
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Request failed.");
  return body;
}

async function run(action) {
  byId("error").textContent = "";
  try { await action(); } catch (error) { byId("error").textContent = error.message; }
}

function statusLabel(item) {
  const labels = {
    draft: "Draft",
    pending: "Pending approval",
    approved: "Approved · awaiting upload",
    writing: "Upload in progress",
    saved: "Uploaded",
    upload_unverified: "Previous upload · unverified after database reset",
    upload_failed: "Upload failed or interrupted · outcome unknown"
  };
  if (item.status === "saved" && !item.graph_schema_version) {
    return `${item.is_sample ? "Mock · " : ""}Uploaded · graph mapping version unverified`;
  }
  if (item.is_sample && item.status === "approved") {
    return connectionStatus.mock_uploads_allowed ? "Approved mock · awaiting test upload" : "Approved mock · upload disabled";
  }
  if (item.is_sample) return `Mock · ${labels[item.status] || item.status}`;
  return labels[item.status] || item.status;
}

async function showTab(name) {
  for (const tab of tabNames) {
    const active = name === tab;
    byId(`tab-${tab}`).hidden = !active;
    byId(`tab-button-${tab}`).setAttribute("aria-selected", String(active));
    byId(`tab-button-${tab}`).tabIndex = active ? 0 : -1;
  }
  byId("search-section").hidden = name !== "workspace";
  if (name === "pending" || name === "history") {
    const cases = (await request(`/api/${name}`)).cases;
    renderCaseList(name, cases);
  } else if (name === "upload") {
    const [status, queue] = await Promise.all([request("/api/connection"), request("/api/pending-upload")]);
    connectionStatus = status;
    renderUploadList(queue.cases);
  } else if (name === "audit") {
    renderAudit((await request("/api/audit")).events);
  }
}

function uploadUnavailable(item) {
  if (item.status === "writing") return "Upload is in progress.";
  if (item.is_sample && !connectionStatus.mock_uploads_allowed) {
    return "Mock uploads are disabled. Enable test-database mode only for a dedicated test database.";
  }
  if (!connectionStatus.configured) return connectionStatus.message;
  if (draft && draft.id === item.id && hasChanges()) {
    return "This review has unsaved edits. Save and resubmit it before uploading.";
  }
  return "";
}

function uploadConfirmation(item) {
  const target = item.is_sample ? "approved mock case to the configured dedicated test database" : "approved case to Neo4j";
  return `Upload this ${target}?\n\nNamed references are reused by normalized name; machines and components are scoped to their line and machine where known. Preview the graph and qualify ambiguous names before approving.`;
}

async function showGraphPreview(target, item) {
  const preview = await request(`/api/drafts/${encodeURIComponent(item.id)}/graph-preview`);
  if (preview.revision !== item.revision) throw new Error("This case changed. Reload it before previewing.");
  target.replaceChildren();
  const title = document.createElement("p");
  title.className = "upload-meta";
  title.textContent = `Proposed mapping (not the current graph) for ${preview.case_name}. Review the separated names and source answers before approval or upload.`;
  const list = document.createElement("ul");
  for (const entry of preview.entries) {
    const row = document.createElement("li");
    const scope = entry.shared ? "reusable reference" : "case-specific";
    const machine = entry.label === "MachineComponent"
      ? (entry.machine_linked ? " · linked to machine" : " · machine assignment unknown") : "";
    row.textContent = `${entry.label}: ${entry.name} · ${scope}${machine}`;
    list.append(row);
  }
  target.append(title, list);
}

function renderUploadList(cases) {
  const list = byId("upload-list");
  list.replaceChildren();
  if (!cases.length) {
    const empty = document.createElement("p");
    empty.className = "empty-list";
    empty.textContent = "No approved cases are waiting for upload.";
    list.append(empty);
    return;
  }
  for (const item of cases) {
    const card = document.createElement("article");
    card.className = "upload-card";
    const heading = document.createElement("h3");
    heading.textContent = item.answers.title || "Untitled case";
    const meta = document.createElement("p");
    meta.className = "upload-meta";
    meta.textContent = `${statusLabel(item)} · ${item.id}`;
    const detail = document.createElement("details");
    detail.className = "upload-details";
    const summary = document.createElement("summary");
    summary.textContent = "View all questionnaire answers and evidence";
    detail.append(summary);
    for (const question of questions) {
      const section = document.createElement("div");
      section.className = "upload-question";
      const title = document.createElement("h4");
      title.textContent = `${question.number}. ${question.label}`;
      section.append(title);
      for (const key of question.fields) {
        const label = document.createElement("strong");
        label.textContent = fields[key][0];
        const value = document.createElement("p");
        const answer = item.answers[key];
        value.textContent = answer === null ? "Unknown" : typeof answer === "boolean" ? (answer ? "Yes" : "No") : String(answer);
        section.append(label, value);
        if (item.evidence[key]) {
          const evidence = document.createElement("p");
          evidence.className = "upload-evidence";
          evidence.textContent = `Evidence: ${item.evidence[key]}`;
          section.append(evidence);
        }
      }
      detail.append(section);
    }
    const reason = document.createElement("p");
    reason.className = "upload-meta";
    reason.textContent = uploadUnavailable(item) || (item.status === "upload_failed"
      ? "The previous outcome is unknown. Retry the unchanged approved snapshot."
      : item.is_sample ? "Mock data will be marked in Neo4j. Only use the designated test database." : "Ready for explicit upload.");
    const previewButton = document.createElement("button");
    previewButton.className = "button secondary";
    previewButton.textContent = "Preview graph mapping";
    const preview = document.createElement("div");
    preview.setAttribute("aria-live", "polite");
    previewButton.addEventListener("click", () => run(() => showGraphPreview(preview, item)));
    const upload = document.createElement("button");
    upload.className = "button primary";
    upload.textContent = item.status === "upload_failed" ? "Retry upload" : "Upload to Neo4j";
    upload.disabled = Boolean(uploadUnavailable(item));
    upload.addEventListener("click", () => run(async () => {
      if (!confirm(uploadConfirmation(item))) return;
      try {
        const updated = await request(`/api/drafts/${item.id}/save`, {revision: item.revision});
        if (draft && draft.id === item.id) { draft = updated; render(); }
      } catch (error) {
        await showTab("upload");
        throw error;
      }
      await showTab("history");
    }));
    card.append(heading, meta, detail, previewButton, preview, reason, upload);
    list.append(card);
  }
}

function renderCaseList(name, cases) {
  const list = byId(`${name}-list`);
  list.replaceChildren();
  if (!cases.length) {
    const empty = document.createElement("p");
    empty.className = "empty-list";
    empty.textContent = name === "pending" ? "No cases are awaiting approval." : "No approved cases yet.";
    list.append(empty);
    return;
  }
  for (const item of cases) {
    const row = document.createElement("div");
    row.className = "case-row";
    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.title || "Untitled case";
    const meta = document.createElement("p");
    const state = name === "history" && item.status === "draft"
      ? "Returned to draft · approval invalidated" : statusLabel(item);
    meta.textContent = `${state} · ${item.id}`;
    details.append(title, meta);
    const open = document.createElement("button");
    open.className = "button secondary";
    open.textContent = "Open review";
    open.addEventListener("click", () => run(async () => {
      if (draft && !confirm("Open another case? Unsaved edits in the current review will be lost.")) return;
      draft = await request(`/api/drafts/${encodeURIComponent(item.id)}`);
      localStorage.setItem("lfeDraft", draft.id);
      byId("transcript").value = draft.transcript;
      render();
      await showTab("workspace");
      byId("review").scrollIntoView();
    }));
    row.append(details, open);
    list.append(row);
  }
}

function renderAudit(events) {
  const list = byId("audit-list");
  list.replaceChildren();
  if (!events.length) {
    const empty = document.createElement("p");
    empty.className = "empty-list";
    empty.textContent = "No lifecycle events yet.";
    list.append(empty);
    return;
  }
  for (const event of events) {
    const row = document.createElement("div");
    row.className = "case-row";
    const details = document.createElement("div");
    const action = document.createElement("strong");
    action.textContent = `${event.action.replaceAll("_", " ")} · ${event.outcome}`;
    const meta = document.createElement("p");
    meta.textContent = `${event.occurred_at} · ${event.case_id} · ${event.actor || "Actor unknown"} · ${event.from_status || "—"} → ${event.to_status || "—"}`;
    details.append(action, meta);
    row.append(details);
    list.append(row);
  }
}

for (const name of tabNames) {
  const button = byId(`tab-button-${name}`);
  button.addEventListener("click", () => run(() => showTab(name)));
  button.addEventListener("keydown", event => {
    const index = tabNames.indexOf(name);
    let target;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") target = (index + 1) % tabNames.length;
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft") target = (index + tabNames.length - 1) % tabNames.length;
    else if (event.key === "Home") target = 0;
    else if (event.key === "End") target = tabNames.length - 1;
    else return;
    event.preventDefault();
    byId(`tab-button-${tabNames[target]}`).focus();
    run(() => showTab(tabNames[target]));
  });
}

function render() {
  byId("review").hidden = false;
  byId("status").textContent = draft.id
    ? `${statusLabel(draft)} · ${draft.id}`
    : "Mock case — not saved";
  byId("fields").replaceChildren();
  for (const question of questions) {
    const group = document.createElement("details");
    group.className = "question";
    const heading = document.createElement("summary");
    const number = document.createElement("span");
    number.className = "question-number";
    number.textContent = String(question.number).padStart(2, "0");
    const headingText = document.createElement("span");
    headingText.textContent = question.label;
    heading.append(number, headingText);
    group.append(heading);
    const content = document.createElement("div");
    content.className = "question-content";
    for (const key of question.fields) {
      const [label, kind] = fields[key];
      const wrapper = document.createElement("div");
      wrapper.className = "field";
      const title = document.createElement("label");
      title.htmlFor = `field-${key}`;
      title.textContent = label;
      let input;
      if (kind === "boolean") {
        input = document.createElement("select");
        for (const [value, text] of [["", "Unknown"], ["true", "Yes"], ["false", "No"]]) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = text;
          input.append(option);
        }
        input.value = draft.answers[key] === null ? "" : String(draft.answers[key]);
      } else {
        input = document.createElement(kind === "text" ? "textarea" : "input");
        if (kind !== "text") {
          input.type = "number";
          input.min = "0";
          input.step = kind === "integer" ? "1" : "any";
        } else input.rows = 2;
        input.value = draft.answers[key] ?? "";
      }
      input.id = `field-${key}`;
      input.addEventListener("input", () => byId("graph-preview").replaceChildren());
      const hints = {
        project: "Separate multiple names with semicolons or new lines; quote a name containing a delimiter.",
        product: "Separate multiple names with semicolons or new lines; quote a name containing a delimiter.",
        material: "Separate multiple names with semicolons or new lines; quote a name containing a delimiter.",
        supplier: "Separate multiple names with semicolons or new lines; quote a name containing a delimiter.",
        line: "Separate multiple names with semicolons or new lines; quote a name containing a delimiter.",
        machine: "Separate multiple names with semicolons or new lines; quote a name containing a delimiter.",
        component: "Separate components with commas, semicolons, new lines, or 'and'; quote a single name containing a delimiter.",
        action: "Separate distinct actions with semicolons or new lines; quote an action containing a delimiter.",
        attachment_description: "Separate attachment names with commas, semicolons, or new lines; quote a name containing a delimiter."
      };
      wrapper.append(title, input);
      if (hints[key]) {
        const hint = document.createElement("small");
        hint.className = "hint";
        hint.id = `hint-${key}`;
        hint.textContent = hints[key];
        input.setAttribute("aria-describedby", hint.id);
        wrapper.append(hint);
      }
      const evidenceLabel = document.createElement("label");
      evidenceLabel.htmlFor = `evidence-${key}`;
      evidenceLabel.className = "evidence";
      evidenceLabel.textContent = "Evidence / transcript excerpt";
      const evidence = document.createElement("textarea");
      evidence.id = `evidence-${key}`;
      evidence.rows = 2;
      evidence.value = draft.evidence[key] || "";
      evidence.addEventListener("input", () => byId("graph-preview").replaceChildren());
      wrapper.append(evidenceLabel, evidence);
      content.append(wrapper);
    }
    group.append(content);
    byId("fields").append(group);
  }
  const locked = ["saved", "writing", "upload_failed", "upload_unverified"].includes(draft.status);
  byId("fields").querySelectorAll("textarea, input, select").forEach(element => { element.disabled = locked; });
  byId("update").disabled = locked;
  byId("preview-graph").disabled = !draft.id;
  byId("graph-preview").replaceChildren();
  byId("submit").disabled = draft.status !== "draft" || !draft.id;
  byId("approve").disabled = draft.status !== "pending" || !draft.id;
  const reason = uploadUnavailable(draft);
  byId("save").disabled = !["approved", "upload_failed"].includes(draft.status) || Boolean(reason);
  byId("upload-explanation").textContent = reason || (!["approved", "upload_failed"].includes(draft.status) ? "Submit and approve this case before uploading." : "");
  byId("save").textContent = draft.status === "upload_failed" ? "Retry upload" : "Upload to Neo4j";
}

function hasChanges() {
  const current = reviewedValues();
  return Object.keys(fields).some(key =>
    current.answers[key] !== draft.answers[key] ||
    (current.evidence[key] || "") !== (draft.evidence[key] || ""));
}

async function saveReview() {
  const values = reviewedValues();
  if (draft.is_sample && !draft.id) {
    draft = await request("/api/sample-drafts", values);
    localStorage.setItem("lfeDraft", draft.id);
  } else {
    draft = await request(`/api/drafts/${draft.id}/update`, {...values, revision: draft.revision});
  }
  render();
}

function reviewedValues() {
  const answers = {}, evidence = {};
  for (const [key, [, kind]] of Object.entries(fields)) {
    const value = byId(`field-${key}`).value;
    if (value === "") answers[key] = null;
    else if (kind === "boolean") answers[key] = value === "true";
    else if (kind === "text") answers[key] = value;
    else answers[key] = Number(value);
    const excerpt = byId(`evidence-${key}`).value;
    if (excerpt.trim()) evidence[key] = excerpt;
  }
  return {answers, evidence};
}

byId("create").addEventListener("click", () => run(async () => {
  if (draft && !confirm("Replace the current review? Unsaved edits will be lost.")) return;
  const result = await request("/api/drafts", {transcript: byId("transcript").value});
  draft = result.draft;
  localStorage.setItem("lfeDraft", draft.id);
  byId("notice").textContent = result.notice;
  render();
}));
byId("load-sample").addEventListener("click", () => run(async () => {
  const sample = samples.find(item => item.id === byId("sample").value);
  if (!sample) throw new Error("Select a mock case first.");
  if (draft && !confirm("Replace the current review? Unsaved edits will be lost.")) return;
  draft = {id: null, status: "draft", is_sample: true, answers: {...sample.answers}, evidence: {}};
  byId("transcript").value = "";
  byId("notice").textContent = "Mock case loaded for review only; it has not been saved.";
  render();
}));
byId("preview-graph").addEventListener("click", () => run(async () => {
  if (hasChanges()) throw new Error("Save the review before previewing its graph mapping.");
  await showGraphPreview(byId("graph-preview"), draft);
}));
byId("update").addEventListener("click", () => run(async () => {
  await saveReview();
}));
byId("submit").addEventListener("click", () => run(async () => {
  if (hasChanges()) throw new Error("Save the review before submitting for approval.");
  draft = await request(`/api/drafts/${draft.id}/submit`, {revision: draft.revision});
  render();
  await showTab("pending");
}));
byId("approve").addEventListener("click", () => run(async () => {
  if (hasChanges()) throw new Error("Save edits and submit again before approval.");
  draft = await request(`/api/drafts/${draft.id}/approve`, {revision: draft.revision});
  render();
  await showTab("upload");
}));
byId("save").addEventListener("click", () => run(async () => {
  if (hasChanges()) {
    throw new Error("Answers changed after approval. Save and approve them again.");
  }
  if (!confirm(uploadConfirmation(draft))) return;
  try {
    draft = await request(`/api/drafts/${draft.id}/save`, {revision: draft.revision});
  } catch (error) {
    try {
      draft = await request(`/api/drafts/${draft.id}`);
      render();
    } catch (refreshError) {
      throw new Error("Upload failed and its status could not be refreshed. Reload the case before retrying.");
    }
    throw error;
  }
  render();
  await showTab("history");
}));
byId("search").addEventListener("click", () => run(async () => {
  const result = await request("/api/qa", {question: byId("question").value});
  byId("answer").textContent = result.answer;
}));
byId("check-connection").addEventListener("click", async () => {
  const button = byId("check-connection");
  button.disabled = true;
  byId("connection-status").textContent = "Checking connection…";
  try {
    const result = await request("/api/connection/check", {});
    byId("connection-status").textContent = result.message;
  } catch (error) {
    byId("connection-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
run(async () => {
  const schema = await request("/api/schema");
  fields = schema.fields;
  questions = schema.questions;
  connectionStatus = await request("/api/connection");
  byId("connection-status").textContent = connectionStatus.message;
  samples = (await request("/api/samples")).samples;
  for (const sample of samples) {
    const option = document.createElement("option");
    option.value = sample.id;
    option.textContent = sample.name;
    byId("sample").append(option);
  }
  const id = localStorage.getItem("lfeDraft");
  if (id) {
    draft = await request(`/api/drafts/${encodeURIComponent(id)}`);
    byId("transcript").value = draft.transcript;
    render();
  }
});
