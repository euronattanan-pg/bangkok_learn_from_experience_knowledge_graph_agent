---
name: fdm-api-expert
description: "Live product master data from FDM (Foundational Data Manager) over its REST API: look up a finished product by GCAS code, walk the BOM tree (CUP/IPU/COP, PMP packaging, FOP formulation and raw materials, quantities), read a specification, and read/write/delete its parameters. Do NOT use for Enovia PLM BOM/where-used SQL (enovia-sql-author) or SAP material master (sap-sql-expert)."
license: "Proprietary — P&G internal use"
---

# FDM API Expert

Generic, reusable capability for autonomous interaction with the FDM (Foundational Data
Manager) REST API. It handles authentication, product lookup by GCAS code, hierarchical BOM
data retrieval and traversal, and reading/writing parameters on specifications.

FDM organizes all product data as a BOM (Bill of Materials) tree. Each node is a Part with a
fixed Part Type that determines its position in the hierarchy. Before querying or
interpreting FDM data, read `references/fdm_bom_structure.md` to understand the type
hierarchy and structural rules.

> Scope: this skill is the **domain-agnostic FDM API layer** — lookup, traversal, and generic
> parameter CRUD. *Business-specific* logic (which parameters to derive, what values to write,
> notifications, batch discovery) belongs to the calling agent's own workflow, not here. An
> agent decides *what* to write; this skill knows *how* to talk to FDM.

---

## Bundled script (preferred execution path)

`scripts/fdm_client.py` is a stdlib-only REST client. It loads `.env`, handles login +
URL-encoding, and exposes `search_finished_product`, `get_specification`, `get_parameters`,
`upsert_parameter`, and `delete_parameter`. It never logs credentials. Import it from other
code, or run a CLI smoke test:

```bash
python scripts/fdm_client.py 80848203
```

It uses only the Python stdlib. `FDM_ENV` (or the default `.env` in the cwd) provides FDM
credentials. FDM HTTP calls time out after `FDM_HTTP_TIMEOUT` seconds (default `60`) and
raise a clear error instead of hanging when the service is slow or unreachable.

Read this file to understand the contract; call the script to execute it. Encoding the rules
in the client removes run-to-run drift on parsing-heavy steps (URL-encoding, BOM walking,
sub-formulation lookup).

---

## Safety and Constraints

These rules are non-negotiable:

1. **Read-only by default.** Only perform `POST`/`PUT`/`DELETE` on parameters when the user
   (or the calling agent's workflow) explicitly requests a write or update. Query operations
   (`GET`) are always safe.
2. **Confirm before mutation.** Before writing parameters, show what will be written (key,
   value, dataType) and get confirmation. Before updating an existing parameter, `GET` the
   current value first and show the diff.
3. **Never expose secrets in commands or output.** Credentials (username, password) must
   never appear as literal strings in shell commands, curl arguments, or terminal output. The
   password is especially sensitive — a curl `-d '{"password":"..."}'` command is visible in
   the terminal and in process listings. Always use the file-based auth pattern described in
   Phase 1 so credentials stay inside a temp file that is never echoed. Do not print JWT
   tokens or `.env` contents.
4. **Never load the full OpenAPI file.** Only extract targeted endpoint or schema definitions
   from `references/fdm_openapi.json` using grep, jq, or a script that reads specific paths.
5. **URL-encode the specificationId.** The `uniqueId` contains commas and spaces (e.g.
   `80848203,001,Finished Product Part`). Always URL-encode it when used in a URL path segment.

---

## Prerequisites

### Environment file

The skill requires a `.env` with FDM connection details. Look for `.env` in the workspace
root (or the path in `FDM_ENV`). If not found, ask the user for the path — never broad-search
the filesystem.

Required variables:

```
FDM_API_BASE_URL=https://<fdm-host>/api/   # Full base URL including /api/ with trailing slash
FDM_API_USERNAME=<ldap-username>            # LDAP username (no domain prefix)
FDM_API_PASSWORD=<password>                 # LDAP password
```

All API calls use the pattern `{FDM_API_BASE_URL}<endpoint>` (no extra `/api/` needed since
the base URL already includes it).

> Other credential groups (URM, SMTP, etc.) are **not** part of this skill. If an agent
> workflow needs them, that workflow documents and reads them itself.

---

## Identity Model

FDM uses several identifiers at different stages. Confusing them will break API calls.

| Term | Format | Example | Role |
|------|--------|---------|------|
| **GCAS code** | Numeric string | `80848203` | User-facing product code; the search input. |
| **identifier** | String (may have prefix) | `80848203`, `CUP-00425946`, `IP-00057687` | The Part's internal ID in Enovia. For FPP it often equals the GCAS code; other types have a type-specific prefix. |
| **revision** | Zero-padded string | `001`, `003` | Version number for the Part. |
| **type** | Full type name string | `Finished Product Part`, `pgCustomerUnitPart` | The Part Type as it appears in the API. |
| **uniqueId** | `{identifier},{revision},{type}` | `80848203,001,Finished Product Part` | **The composite key used by all downstream endpoints.** Always: identifier + comma + revision + comma + full type name. |
| **specificationId** | uniqueId, URL-encoded | `80848203%2C001%2CFinished%20Product%20Part` | The `{specificationId}` path parameter. |

**Critical rule**: After searching, extract the `uniqueId` field from the response and
URL-encode it for use as `specificationId`. Do not construct it manually — always use the
value returned by the API.

**UniqueId format is consistent across all Part Types**:

```
FPP:  80848203,001,Finished Product Part
CUP:  CUP-00425946,001,pgCustomerUnitPart
IPU:  IP-00057687,001,pgInnerPackUnitPart
COP:  COP-00376102,001,pgConsumerUnitPart
TUP:  TUP-00160485,001,pgTransportUnitPart
MCUP: MCUP-00101160,001,pgMasterCustomerUnitPart
PMP:  90218837,003,Packaging Material Part
FOP:  21310360,001,Formulation Part
```

---

## Reference Files — When to Read

| File | When to read | How to read |
|------|-------------|-------------|
| `references/fdm_bom_structure.md` | Before interpreting BOM hierarchy, part types, or parent-child relationships | Read fully — it is concise (~160 lines) |
| `references/fdm_api_reference.md` | When you need the correct API group or endpoint for a task | Read the overview table; then jump to the relevant group section |
| `references/fdm_openapi.json` | When you need exact request/response schemas for a specific endpoint | **Never load the whole file.** Use grep or a script to extract only the target endpoint path and referenced schema. |

---

## Workflow

### Phase 1 — Authenticate

**Goal**: Obtain a JWT token for subsequent API calls.

1. Read `.env` from the workspace root (or `FDM_ENV`). If required variables are missing,
   stop and report which ones.
2. Build the login request body in a temp file — **never embed credentials as literal
   strings** in a curl command that will be displayed:

   ```bash
   cat > /tmp/fdm_auth.json << AUTHEOF
   {"username":"${FDM_API_USERNAME}","password":"${FDM_API_PASSWORD}"}
   AUTHEOF

   TOKEN=$(curl -s -X POST "${FDM_API_BASE_URL}Users/Login" \
     -H "Content-Type: application/json" \
     -d @/tmp/fdm_auth.json | tr -d '"')

   rm -f /tmp/fdm_auth.json
   ```

   The `@file` approach keeps the password out of the terminal, shell history, and process
   listings. This is a hard requirement — there is no acceptable shortcut. (`fdm_client.py`
   already does this for you.)
3. On `200`: the body is a bare JWT string (quoted). Store it; use as `Authorization: Bearer
   <token>` on all subsequent requests.
4. On `401`: stop and report "Authentication failed — check credentials in .env".
5. On other errors: stop and report the status code and message.

**Output**: a valid JWT token stored in a variable (never printed).

---

### Phase 2 — Product Lookup

**Goal**: Resolve the user's GCAS code to a `uniqueId`.

1. `GET {FDM_API_BASE_URL}FinishedProducts/Search/{gcasCode}` with the Bearer token.
2. The response groups specifications:

   ```json
   {
     "searchValue": "80848203",
     "groups": [
       { "name": "Digital Specs",
         "specifications": [
           { "specification": {
               "uniqueId": "80848203,001,Finished Product Part",
               "identifier": "80848203", "revision": "001",
               "type": "Finished Product Part",
               "description": "OLD SPICE MIND AND BODY ..." },
             "fpmStatus": "Available" } ] }
     ]
   }
   ```
3. Flatten all `specifications` across all `groups`, then:
   - **Single match**: extract `specification.uniqueId`. Proceed.
   - **Multiple matches**: present the list (identifier, revision, description, group) and ask
     the user to pick one.
   - **No matches**: stop and report "No finished product found for GCAS code {gcasCode}".

**Output**: the resolved `uniqueId` plus the product description for confirmation.

---

### Phase 3a — Fetch Root Specification

**Goal**: Retrieve the full specification for the Finished Product Part (FPP).

1. URL-encode the `uniqueId` and `GET {FDM_API_BASE_URL}Specifications/{encodedUniqueId}`.
2. `200`: store the full specification response.
3. `404`: the `uniqueId` may be wrong — re-verify with the user.
4. `401`: the JWT may have expired — re-run Phase 1 once, then retry; if still 401, stop.

The specification contains the full BOM tree nested as properties:

```
Root specification (FPP)
├── customerUnit                          → CUP object (single, not array)
│   ├── innerPack                         → IPU object (single)
│   │   └── consumerUnits[]               → array of COP objects
│   │       ├── assemblies[]              → array of PAP objects
│   │       │   └── parts[]               → PMP parts within the assembly
│   │       └── parts[]                   → PMP, FOP, and other leaf parts
│   ├── assemblies[]                      → PAP objects at CUP level
│   └── parts[]                           → PMP/OPP parts at CUP level
├── transportUnits[]                      → array of TUP objects
│   └── customerUnit                      → MCUP object (nested inside TUP)
├── basicElements[]                       → key-value metadata
├── extendedElements[]                    → extended key-value metadata
├── sapBomAsFedParts[]                    → SAP BOM flat list
├── performanceSpecificationsReference[]  → quality specs
└── productDetails                        → product code, metrics, attributes
```

Every nested part object (CUP, IPU, COP, TUP, MCUP, PAP, PMP, FOP) has the same standard
fields including `uniqueId`, `identifier`, `revision`, `type`, and its own `parts[]`,
`basicElements[]`, etc.

**Output**: the complete FPP specification object with its entire BOM hierarchy.

---

### Phase 3b — BOM Traversal and Targeted Queries

**Goal**: Navigate the BOM to retrieve additional data as needed.

The Phase 3a response already contains the full nested BOM — for most use cases, traversing
the in-memory response is sufficient without extra API calls. Read
`references/fdm_bom_structure.md` before traversing. Quick cheat sheet:

- **FPP** is the root. **CUP** (retail) and **TUP** (logistics) are the two top-level branches.
- Hierarchy: FPP → CUP → IPU → COP → PAP/PMP/FOP.
- **Twin packs and other Manips configurations may skip the IPU layer** —
  `customerUnit.consumerUnits[]` then lives directly under CUP. When walking to the COP, try
  `customerUnit.innerPack.consumerUnits[]` first and fall back to
  `customerUnit.consumerUnits[]`.
- Leaf types: **PMP** (packaging material), **FOP** (formulation), **OPP** (online printing),
  **MCUP** (dimension template).
- **PMP** can appear at multiple levels — always check parent type for context.
- `isSubstitute=true` → alternative part, not a separate hierarchy level.

**Decision rules — always follow the product BOM structure when querying**:

- **Default (BOM / materials / product overview)**: walk the full BOM top-down (FPP → CUP →
  IPU → COP → leaves). Always include Formulation Parts (FOP). Present quantities **with units**
  for every node.
- **Formulation data**: navigate to `customerUnit.innerPack.consumerUnits[].parts[]` and
  filter for `type == "Formulation Part"`. FOPs often contain nested sub-formulations and raw
  materials — traverse the full depth of the FOP subtree (including `parts[]` within each FOP)
  to capture the complete ingredient composition. A shallow query that stops at the top-level
  FOP misses the actual breakdown.
- **Packaging data**: gather PMP nodes from all levels (CUP, IPU, COP, PAP); clarify the level
  if ambiguous.
- **Specific child part**: use its `uniqueId` to `GET Specifications/{encodedUniqueId}` for
  the detailed view.

---

### Parameters — Read and Write (generic CRUD)

The Parameters endpoints let you read and persist local parameters on a specification. This
skill provides the **mechanics**; the *set of parameters and their values* is decided by the
calling agent/workflow.

**This is a mutation surface — Phase 4 write operations execute ONLY when explicitly
requested. Never auto-trigger writes.**

1. **Discover existing**: `GET {baseUrl}Specifications/{encodedUniqueId}/Parameters` →
   list of `{key, value, dataType}`. Use this to decide POST vs PUT and to show diffs.
2. For each parameter to persist:
   - **Skip** when the existing value matches exactly (idempotent re-runs).
   - **POST** when the key is new. Body: `{"parameter": {"key": "...", "value": ...,
     "dataType": <int>}}`.
   - **PUT** when the key already exists. Same body shape; show old → new before sending.
   - **DELETE** uses the same body shape with `value: null`. Confirm with the user first.
3. Report `{action, key, old, new}` per write. On any non-2xx, stop and surface the server
   message — do not retry silently.

**`dataType` integer mapping** (as accepted by the FDM tenant):

| dataType | Meaning |
|---|---|
| 1 | Number (Single/Int) |
| 2 | String (also used for booleans on tenants that reject `0`) |

> **Tenant caveat:** although the OpenAPI enum lists `0` as a valid `dataType`, the production
> tenant (`gbs-fdmprod01`) rejects it with HTTP 400 `"Parameter data type is invalid."`
> Booleans on that tenant are written as `dataType=2` strings with literal lowercase
> `"true"`/`"false"`. When updating an existing parameter, preserve the server's current
> `dataType` unless explicitly overridden — a mismatch surfaces as a `400`.

`fdm_client.py` exposes `get_parameters`, `upsert_parameter`, and `delete_parameter` so the
calling workflow does not re-implement this.

---

## Error Handling

| Error | Action |
|-------|--------|
| `.env` not found | Ask the user for the path. Do not guess. |
| `.env` missing required vars | Report which variables are missing. Do not proceed. |
| `401 Unauthorized` | During login: report bad credentials. During a later call: re-authenticate once, then retry; if still 401, stop. |
| `404 Not Found` | Verify the uniqueId / encoding. Report to user. |
| `400 Bad Request` | Inspect the request body against the expected schema. Report the mismatch. |
| `500 Server Error` | Report the error. Do not retry automatically. |
| Multiple search results | Present options and ask for selection. |
| No search results | Report clearly with the searched GCAS code. |
| `Permission denied and could not request permission from user` | The Copilot CLI sandbox blocked the shell tool (per-tool approval not granted). `python3` and `curl` are NOT auto-allowed. Ask the user to run **`/allow-all`** (or `/reset-allowed-tools` then "Always allow" for `python3` and `curl`), and optionally `/add-dir <repo>`. |

---

## Output Format

After completing a run, report a structured summary containing:

1. **Product identified**: GCAS code, resolved uniqueId, description, revision.
2. **Data retrieved**: what was fetched (root spec, child specs, parameter list).
3. **Actions taken**: any writes (parameter key, old → new).
4. **Warnings**: ambiguities, missing data, or errors.

**Quantities must always include units.** Every amount must show its unit of measure (e.g.
`0.08983 KG`, `1.0 EACH`, `252 mm`). The API returns `quantity` and `baseUnitOfMeasure` as
separate fields — always combine them. A bare number without a unit is meaningless and can
cause misinterpretation.
