<!-- SPDX-License-Identifier: FSL-1.1-Apache-2.0 -->
<!-- Copyright (c) 2025 Open Computer Use Contributors -->
<!-- GENERATED from scenarios.yaml by render_contrast.py. Do not hand-edit. -->

# PoC vs fleet — journey contrast

One row per scenario. `Proves` is the single invariant the scenario asserts;
`PoC` and `Fleet` are the per-system outcomes; `Bucket` classifies the gap
(IDENTICAL / HARDENED / PoC-HOLE). The negative / inversion keystone that keeps
each assertion non-vacuous lives in scenarios.yaml.

## Group A — Auth & Bootstrap

| ID | Story | Proves | PoC | Fleet | Bucket |
| --- | --- | --- | --- | --- | --- |
| A1 | As a user I open the UI and get a session. | First-party cookie set on bootstrap. | No cookie (Open WebUI only). | SameSite=None/Secure/HttpOnly cookie + embed-token verified (sig+aud+exp<=120s). | HARDENED |
| A2 | As a user I load the UI from an allowed parent origin. | Frame-ancestor allowlist enforced. | No CSP; any parent may frame it. | CSP frame-ancestors from allowlist; foreign parent blocked. | HARDENED |
| A3 | As a user I perform a mutating action (upload). | CSRF token required on mutations. | No CSRF; mutation accepted unconditionally. | Mutation without a valid CSRF token refused. | HARDENED |
| A4 | As an MCP caller I connect to the orchestrator. | Caller identity is host-attested. | Plain HTTP; any caller with a chat-id is served. | Gateway mTLS, one client cert = one caller; no cert -> TLS/401. | PoC-HOLE |
| A5 | As an MCP caller I present a valid static key. | ADR-0027 static key gate. | No analogue (no key gate). | Valid sk-ocu- key accepted; unknown key -> 401. | HARDENED |
| A6 | As a user I get a sandbox to run work. | Session creation is quota-reserved and image-gated. | docker run of any image, unbounded. | control create: image allow-list + row-as-reservation quota. | HARDENED |

## Group B — Journey 1: create a docx and download it

| ID | Story | Proves | PoC | Fleet | Bucket |
| --- | --- | --- | --- | --- | --- |
| B1 | As a user I ask the agent to build report.docx. | Agent writes to the outputs surface. | Writes host-bind /data/{chat}/outputs. | Guest writes /mnt/user-data/outputs (FUSE rw, dir 0755 / file 0644). | IDENTICAL |
| B2 | As a user I see the docx in my files list. | Outputs are enumerable to me. | GET /api/outputs/{chat_id} lists the file. | F9 /v1/files returns a server-minted scope-bound file_id, cursor-paginated. | HARDENED |
| B3 | As a user I download the docx. | The byte path to the user works end-to-end. | GET /files/{chat}/{file} streams the bytes. | UI download -> three-axis authz (scope+read+downloadable) -> bytes. | HARDENED |
| B4 | As a user I open the downloaded docx. | The artifact is a valid document, not a stub. | File exists on outputs. | Valid OOXML delivered. | IDENTICAL |
| B5 | As a user I download all outputs as a zip. | Bulk export works. | GET /files/{chat}/archive returns a zip. | Per-file loop over F9 (no invented zip endpoint) yields the same file-set. | IDENTICAL |
| B6 | As a user I download while the agent is still writing. | Partial / in-flight download handling is defined. | Serves whatever bytes exist (may be truncated). | Full-file-or-404, not silent truncation (assert the envelope, not a byte guess). | HARDENED |

## Group C — Journey 2: upload, edit-in-guest, download from outputs

| ID | Story | Proves | PoC | Fleet | Bucket |
| --- | --- | --- | --- | --- | --- |
| C1 | As a user I upload a file into inputs. | Upload lands where the guest reads. | Open WebUI -> /data/{chat}/uploads (:ro bind). | F9 / mount upload -> inputs mount (readonly:true, dir 0555 / file 0444). | HARDENED |
| C2 | As a user I have the guest read my uploaded file. | Inputs are readable in-guest. | Container reads the :ro bind. | Guest reads /mnt/user-data/inputs/<f> (cache 5s). | IDENTICAL |
| C3 | As a user I have the agent transform it and write to outputs. | read-inputs / write-outputs split. | Reads uploads, writes outputs (both binds). | Read inputs (ro) -> write outputs (rw). | IDENTICAL |
| C4 | As a user I download the edited result from outputs. | The transform round-trips back to me. | Download endpoint serves the transformed bytes. | Transformed content downloads via F9. | IDENTICAL |
| C5 | As a user I try to overwrite my input file. | Inputs are genuinely read-only. | :ro bind -> write fails EROFS. | Write to inputs -> EROFS/denied at FUSE (dir 0555). | HARDENED |
| C6 | As a user I upload a file with a nasty name (../, spaces, unicode, 255-char). | Path handling is safe. | Host-bind join carries an escape risk. | Name sanitized / scoped; no escape. | HARDENED |
| C7 | As a user I upload a zero-byte file and a large (>chunk) file. | Boundary sizes + chunked upload. | Single PUT. | Chunked fileUpload reassembles; 0-byte handled. | HARDENED |

## Group D — Authz boundary (every-hop enforcement, adversarial)

| ID | Story | Proves | PoC | Fleet | Bucket |
| --- | --- | --- | --- | --- | --- |
| D1 | As an attacker I read another user's file by guessing an id. | No cross-scope read and no enumeration leak. | SUCCEEDS — any chat_id reads that chat's files. | Foreign file_id -> 404 (not 403), no enumeration oracle. | PoC-HOLE |
| D2 | As an attacker I present a valid token for a foreign scope. | The scope check is distinct from the auth check. | No analogue. | Valid signature, foreign scope -> 403. | PoC-HOLE |
| D3 | As an attacker I call the filestore with no or an expired token. | Missing-auth is refused. | No analogue (no token model). | Missing/expired -> 401 with a BoundedReason envelope. | PoC-HOLE |
| D4 | As an attacker in the guest I hit MinIO / control directly. | Guest network isolation. | SUCCEEDS — guest has full network. | Guest only on the mount-facing net; no route to control/south/exchange/MinIO. | PoC-HOLE |
| D5 | As an attacker in the guest I read the real filestore credential. | The guest never holds the upstream secret. | Host has raw files; no secret model at all. | Guest holds only the weak JWT; the real credential is injected at egress, absent in the guest. | PoC-HOLE |
| D6 | As a user I preview a downloadable=false file, then try to save it. | Preview-not-download exfil control. | No analogue — everything downloads. | Preview renders in-session; the byte path to the browser is REFUSED. | PoC-HOLE |
| D7 | As an attacker I replay a captured / expired session-JWT at egress. | Token freshness is enforced at the edge. | No analogue. | Egress validates via control JWKS; expired/replayed -> 401. | PoC-HOLE |

## Group E — Auto-disconnect, lifecycle, kill-switch

| ID | Story | Proves | PoC | Fleet | Bucket |
| --- | --- | --- | --- | --- | --- |
| E1 | As a user I go idle and get reaped. | Idle reaper / TTL releases the session. | Reaper per backlog #91 (verify what exists). | Session -> released; next op returns a deny status (assert released-state + status, not a hardcoded timeout). | HARDENED |
| E2 | As an operator I force-disconnect everyone. | The kill-switch revoke/all denies everyone. | No kill-switch. | revoke/all (SO_PEERCRED sock) -> all sessions denied. | PoC-HOLE |
| E3 | As a user I come back after the operator resumes. | resume/all restores new sessions. | No analogue. | resume/all -> new create ok; pre-revoke sessions stay denied. | HARDENED |
| E4 | As a user I keep working after a control restart. | State durability / boot-reconcile. | In-memory; the container map is lost on restart. | Postgres state survives; #93 reconcile reclaims orphan rows. | HARDENED |
| E5 | As an operator I restart control after a guest crashed. | An orphan row does not leak a quota slot. | No analogue. | Container-less row -> reclaimed to released + slot returned; a fresh create 201s without a manual RevokeAll. | PoC-HOLE |
| E6 | As an operator I restart control with a stray container. | A row-less container is killed. | No analogue. | A row-less container is killed on reconcile. | HARDENED |
| E7 | As a user I hit the quota ceiling. | Concurrency is actually capped. | Unbounded docker run. | N sessions ok, N+1 -> 409 at the tier cap. | PoC-HOLE |
| E8 | As a user my session-JWT expires mid-journey. | Expiry surfaces cleanly, not as a hang. | No token. | Mid-download 401 at egress; UI re-auth on embed-token exp<=120s. | HARDENED |

## Group F — Agentic-load simulation

| ID | Story | Proves | PoC | Fleet | Bucket |
| --- | --- | --- | --- | --- | --- |
| F1 | As a user I run many sessions concurrently. | Isolation + quota hold under concurrency. | Containers created freely; noisy-neighbor. | Up-to-cap concurrent sessions isolated; cap enforced under race. | HARDENED |
| F2 | As a user I fan out sub-agents / parallel exec in one session. | Parallel work is stable. | MCP sub_agent tool. | Concurrent exec calls carry the correct exec-identity (RuntimeID:cname); no cross-talk. | HARDENED |
| F3 | As a user I push a large file through the storage chain. | Streaming / backpressure without truncation. | Single stream. | Chunked up+down, hash-stable. | HARDENED |
| F4 | As a user I list a directory with hundreds of files. | Pagination does not leak or OOM. | One dir listing. | F9 cursor pagination; page N+1 continues with no dupes/gaps. | HARDENED |
| F5 | As a user I churn create->exec->release rapidly. | Slots do not leak under churn. | No analogue. | Steady-state slot count returns to baseline (reconcile under load). | HARDENED |

## Group G — Negative / adversarial / isolation invariants

| ID | Story | Proves | PoC | Fleet | Bucket |
| --- | --- | --- | --- | --- | --- |
| G1 | As an auditor I inspect the guest for the mount-config after boot. | The config is scrubbed post-load (NFR-SEC-25). | No such config exists. | Config unlinked after Load; absent in the guest. | HARDENED |
| G2 | As an attacker I send a forged / tampered wire frame to a hop. | Signature verification refuses forgeries. | No signing. | A forged frame is refused (F9 / gateway signature check). | PoC-HOLE |
| G3 | As an attacker I tamper with an audit event on disk. | Audit hash-chain integrity + fail-closed. | NO audit at all. | A file-op emits an OCSF class-1001 hash-chained event; tamper -> chain verify fails; sink-down -> op refused. | PoC-HOLE |
| G4 | As an attacker in the guest I reach the internet. | Egress is allow-listed, not open. | Full network. | Only allow-listed egress is reachable. | PoC-HOLE |
| G5 | As a user I read a file after my session ended. | Post-session data lifecycle is defined. | Host-bind persists on disk; container gone -> download 404s. | Assert the DEFINED end state (file_id lifecycle) and the status class; do not invent a retention window. | HARDENED |
| G6 | As a user I download a file I own but marked non-downloadable via the raw byte route. | The exfil control cannot be bypassed at the wire. | No analogue. | The direct byte route for downloadable=false is refused (mirrors D6 at the API level). | PoC-HOLE |

## Bucket totals

- IDENTICAL: 6
- HARDENED: 24
- PoC-HOLE: 15
- total scenarios: 45
