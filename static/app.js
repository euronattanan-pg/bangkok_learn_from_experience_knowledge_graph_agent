"use strict";
let fields = {};
let questions = [];
let samples = [];
let draft = null;
let mutationPending = false;
let editGeneration = 0;
let activeTab = "workspace";
let mappingRequired = false;
let modelStatus = {provider: "manual", cli_available: false};
const disabledControls = new Map();
const unverifiedCases = new Set();
let connectionStatus = {configured: false, mock_uploads_allowed: false, message: "Configuration has not been checked."};
const byId = id => document.getElementById(id);
const tabNames = ["workspace", "drafts", "pending", "upload", "history", "audit"];

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

function lockControls() {
  if (!mutationPending) return;
  document.querySelectorAll("button, input, textarea, select").forEach(control => {
    if (!disabledControls.has(control)) disabledControls.set(control, control.disabled);
    control.disabled = true;
  });
}

function restoreControls() {
  for (const [control, disabled] of disabledControls) {
    if (control.isConnected) control.disabled = disabled;
  }
  disabledControls.clear();
}

async function mutate(action) {
  if (mutationPending) return;
  mutationPending = true;
  lockControls();
  try { return await action(); } finally {
    mutationPending = false;
    restoreControls();
  }
}

function workspaceToken() {
  return {selected: draft, generation: editGeneration};
}

function applyWorkspace(updated, token, preserveTranscript = false) {
  if (draft !== token.selected || editGeneration !== token.generation) return false;
  draft = updated;
  editGeneration++;
  unverifiedCases.delete(draft.id);
  localStorage.setItem("lfeDraft", draft.id);
  if (!preserveTranscript && (!token.selected || token.selected.id !== updated.id)) {
    byId("transcript").value = draft.transcript || "";
  }
  render();
  return true;
}

function refreshWorkspace(updated, token) {
  if (!draft || draft.id !== updated.id || draft !== token.selected) return;
  unverifiedCases.delete(updated.id);
  if (!applyWorkspace(updated, token)) {
    draft = updated;
    restoreControls();
    renderControls();
    lockControls();
  }
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
  activeTab = name;
  for (const tab of tabNames) {
    const active = name === tab;
    byId(`tab-${tab}`).hidden = !active;
    byId(`tab-button-${tab}`).setAttribute("aria-selected", String(active));
    byId(`tab-button-${tab}`).tabIndex = active ? 0 : -1;
  }
  byId("search-section").hidden = name !== "workspace";
  if (name === "pending" || name === "history" || name === "drafts") {
    const cases = (await request(`/api/${name}`)).cases;
    if (activeTab === name) renderCaseList(name, cases);
  } else if (name === "upload") {
    const [status, queue] = await Promise.all([request("/api/connection"), request("/api/pending-upload")]);
    if (activeTab === name) {
      connectionStatus = status;
      mappingRequired = queue.mapping_required === true;
      renderUploadList(queue.cases);
    }
  } else if (name === "audit") {
    const events = (await request("/api/audit")).events;
    if (activeTab === name) renderAudit(events);
  }
  lockControls();
}

function uploadUnavailable(item) {
  if (unverifiedCases.has(item.id)) return "Upload status is unknown. Reopen this case before editing or retrying.";
  if (item.status === "writing") return "Upload is in progress.";
  if (mappingRequired && item.status === "approved" && !item.graph_mapping_approved) {
    return "Generate, review, and confirm the Copilot graph mapping before uploading.";
  }
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
  const source = preview.source === "frozen_upload" ? "Frozen upload snapshot"
    : preview.source === "copilot_proposal" ? "Copilot structured mapping proposal"
      : "Deterministic mapping preview";
  title.textContent = `${source} for ${preview.case_name}. ${
    preview.mapping_approved ? "Confirmed mapping will be used for upload."
      : "Review the separated names and source answers before upload."}`;
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
  if (preview.unresolved.length) {
    const heading = document.createElement("p");
    heading.className = "upload-meta";
    heading.textContent = "Unresolved entities must be corrected in the questionnaire, then resubmitted and reapproved:";
    const issues = document.createElement("ul");
    for (const issue of preview.unresolved) {
      const row = document.createElement("li");
      row.textContent = `${issue.field}: “${issue.excerpt}” — ${issue.reason}`;
      issues.append(row);
    }
    target.append(heading, issues);
  }
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
    if (mappingRequired && item.status === "approved") {
      const mappingButton = document.createElement("button");
      mappingButton.className = "button secondary mapping-generate";
      mappingButton.textContent = item.graph_mapping_proposal ? "Regenerate Copilot mapping" : "Generate Copilot mapping";
      mappingButton.disabled = item.graph_mapping_approved;
      mappingButton.addEventListener("click", () => run(() => mutate(async () => {
        const mapped = await request(`/api/drafts/${encodeURIComponent(item.id)}/map`, {revision: item.revision});
        item.graph_mapping_proposal = mapped.graph_mapping_proposal;
        item.graph_mapping_approved = false;
        item.revision = mapped.revision;
        await showGraphPreview(preview, item);
        mappingButton.textContent = "Regenerate Copilot mapping";
        upload.disabled = true;
        reason.textContent = mapped.graph_mapping_proposal.unresolved.length
          ? "Resolve the flagged entities in the questionnaire, then resubmit and reapprove."
          : "Review the proposal below, then confirm it before upload.";
        confirmMapping.hidden = mapped.graph_mapping_proposal.unresolved.length > 0;
        correctMapping.hidden = mapped.graph_mapping_proposal.unresolved.length === 0;
      })));
      const confirmMapping = document.createElement("button");
      confirmMapping.className = "button secondary mapping-confirm";
      confirmMapping.textContent = "Confirm graph mapping";
      confirmMapping.hidden = !item.graph_mapping_proposal || item.graph_mapping_proposal.unresolved.length > 0;
      confirmMapping.disabled = item.graph_mapping_approved;
      confirmMapping.addEventListener("click", () => run(() => mutate(async () => {
        const confirmed = await request(`/api/drafts/${encodeURIComponent(item.id)}/confirm-mapping`,
          {revision: item.revision});
        item.graph_mapping_proposal = confirmed.graph_mapping_proposal;
        item.graph_mapping_approved = confirmed.graph_mapping_approved;
        item.revision = confirmed.revision;
        await showGraphPreview(preview, item);
        await showTab("upload");
      })));
      const correctMapping = document.createElement("button");
      correctMapping.className = "button secondary mapping-correct";
      correctMapping.textContent = "Open review to correct";
      correctMapping.hidden = !item.graph_mapping_proposal || !item.graph_mapping_proposal.unresolved.length;
      correctMapping.addEventListener("click", () => run(() => mutate(async () => {
        if (draft && !confirm("Open this approved case for correction? Saving changes will return it to draft and require approval again.")) return;
        const token = workspaceToken();
        const updated = await request(`/api/drafts/${encodeURIComponent(item.id)}`);
        if (!applyWorkspace(updated, token)) return;
        await showTab("workspace");
        byId("review").scrollIntoView();
      })));
      if (item.graph_mapping_proposal) {
        showGraphPreview(preview, item).catch(error => { byId("error").textContent = error.message; });
      }
      card.append(mappingButton, confirmMapping, correctMapping);
    }
    const upload = document.createElement("button");
    upload.className = "button primary";
    upload.textContent = item.status === "upload_failed" ? "Retry upload" : "Upload to Neo4j";
    upload.disabled = Boolean(uploadUnavailable(item));
    upload.addEventListener("click", () => run(() => mutate(async () => {
      if (!confirm(uploadConfirmation(item))) return;
      await uploadCase(item);
    })));
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
    empty.textContent = name === "pending" ? "No cases are awaiting approval."
      : name === "drafts" ? "No saved drafts yet." : "No approved cases yet.";
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
    open.addEventListener("click", () => run(() => mutate(async () => {
      if (draft && !confirm("Open another case? Unsaved edits in the current review will be lost.")) return;
      const token = workspaceToken();
      const updated = await request(`/api/drafts/${encodeURIComponent(item.id)}`);
      if (!applyWorkspace(updated, token)) return;
      await showTab("workspace");
      byId("review").scrollIntoView();
    })));
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
  restoreControls();
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
      input.addEventListener("input", () => { editGeneration++; byId("graph-preview").replaceChildren(); });
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
      evidence.addEventListener("input", () => { editGeneration++; byId("graph-preview").replaceChildren(); });
      wrapper.append(evidenceLabel, evidence);
      content.append(wrapper);
    }
    group.append(content);
    byId("fields").append(group);
  }
  renderControls();
  lockControls();
}

function renderControls() {
  const unverified = unverifiedCases.has(draft.id);
  const locked = unverified || ["saved", "writing", "upload_failed", "upload_unverified"].includes(draft.status);
  byId("fields").querySelectorAll("textarea, input, select").forEach(element => { element.disabled = locked; });
  byId("update").disabled = locked;
  byId("preview-graph").disabled = !draft.id || unverified;
  byId("graph-preview").replaceChildren();
  byId("submit").disabled = unverified || draft.status !== "draft" || !draft.id;
  byId("approve").disabled = unverified || draft.status !== "pending" || !draft.id;
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
  const token = workspaceToken();
  const values = reviewedValues();
  let updated;
  if (draft.is_sample && !draft.id) {
    updated = await request("/api/sample-drafts", values);
  } else {
    updated = await request(`/api/drafts/${draft.id}/update`, {...values, revision: draft.revision});
  }
  if (!applyWorkspace(updated, token, true)) {
    if (draft === token.selected) {
      // Advance the server baseline without replacing input entered after this save.
      draft = updated;
      localStorage.setItem("lfeDraft", draft.id);
      restoreControls();
      renderControls();
      lockControls();
    }
    byId("notice").textContent = "The submitted snapshot was saved. Later edits were not replaced and still need saving.";
  }
}

async function uploadCase(item) {
  const token = workspaceToken();
  try {
    const updated = await request(`/api/drafts/${item.id}/save`, {revision: item.revision});
    if (draft && draft.id === item.id) refreshWorkspace(updated, token);
  } catch (error) {
    let refreshFailed = false;
    try {
      const updated = await request(`/api/drafts/${item.id}`);
      if (draft && draft.id === item.id) refreshWorkspace(updated, token);
    } catch (refreshError) {
      refreshFailed = true;
      unverifiedCases.add(item.id);
      if (draft && draft.id === item.id) {
        restoreControls();
        renderControls();
        lockControls();
      }
    }
    // Drop stale controls before refetching; a failed refresh must not leave a retry enabled.
    byId("upload-list").replaceChildren();
    try { await showTab("upload"); } catch (refreshError) { refreshFailed = true; }
    if (refreshFailed) throw new Error(`${error.message} Upload status could not be refreshed. Reload the case before retrying.`);
    throw error;
  }
  await showTab("history");
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

byId("create").addEventListener("click", () => run(() => mutate(async () => {
  if (draft && !confirm("Replace the current review? Unsaved edits will be lost.")) return;
  const token = workspaceToken();
  const result = await request("/api/drafts", {transcript: byId("transcript").value});
  if (!applyWorkspace(result.draft, token)) return;
  byId("notice").textContent = result.notice;
})));
byId("load-sample").addEventListener("click", () => run(async () => {
  if (mutationPending) return;
  const sample = samples.find(item => item.id === byId("sample").value);
  if (!sample) throw new Error("Select a mock case first.");
  if (draft && !confirm("Replace the current review? Unsaved edits will be lost.")) return;
  draft = {id: null, status: "draft", is_sample: true, answers: {...sample.answers}, evidence: {}};
  editGeneration++;
  byId("transcript").value = "";
  byId("notice").textContent = "Mock case loaded for review only; it has not been saved.";
  render();
}));
byId("preview-graph").addEventListener("click", () => run(async () => {
  if (hasChanges()) throw new Error("Save the review before previewing its graph mapping.");
  await showGraphPreview(byId("graph-preview"), draft);
}));
byId("update").addEventListener("click", () => run(() => mutate(async () => {
  await saveReview();
})));
byId("submit").addEventListener("click", () => run(() => mutate(async () => {
  if (hasChanges()) throw new Error("Save the review before submitting for approval.");
  const token = workspaceToken();
  const updated = await request(`/api/drafts/${draft.id}/submit`, {revision: draft.revision});
  if (!applyWorkspace(updated, token)) return;
  await showTab("pending");
})));
byId("approve").addEventListener("click", () => run(() => mutate(async () => {
  if (hasChanges()) throw new Error("Save edits and submit again before approval.");
  const token = workspaceToken();
  const updated = await request(`/api/drafts/${draft.id}/approve`, {revision: draft.revision});
  if (!applyWorkspace(updated, token)) return;
  await showTab("upload");
})));
byId("save").addEventListener("click", () => run(() => mutate(async () => {
  if (hasChanges()) {
    throw new Error("Answers changed after approval. Save and approve them again.");
  }
  if (!confirm(uploadConfirmation(draft))) return;
  await uploadCase(draft);
})));
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
    if (mutationPending) disabledControls.set(button, false);
    button.disabled = mutationPending;
  }
});
run(() => mutate(async () => {
  const schema = await request("/api/schema");
  fields = schema.fields;
  questions = schema.questions;
  connectionStatus = await request("/api/connection");
  byId("connection-status").textContent = connectionStatus.message;
  modelStatus = await request("/api/model");
  byId("model-status").textContent = modelStatus.provider === "copilot-local-cli"
    ? !modelStatus.cli_available ? "Copilot CLI not found · install and sign in locally"
      : !modelStatus.runtime_available ? `Copilot SDK unavailable · ${modelStatus.message}`
        : "Copilot local CLI · account checked on first AI request"
    : "Manual mode · no AI requests";
  samples = (await request("/api/samples")).samples;
  for (const sample of samples) {
    const option = document.createElement("option");
    option.value = sample.id;
    option.textContent = sample.name;
    byId("sample").append(option);
  }
  const id = localStorage.getItem("lfeDraft");
  if (id) {
    const token = workspaceToken();
    try {
      const updated = await request(`/api/drafts/${encodeURIComponent(id)}`);
      applyWorkspace(updated, token);
    } catch (error) {
      byId("notice").textContent = "The last case could not be restored. Use Saved drafts to resume saved work.";
    }
  }
}));
