# F9 north-list reconcile + cursor findings (2026-07-19)

Four findings surfaced firsthand while authoring the pane-poll-liveness e2e test (M11) against the
assembled OCU next/v1 stand (Lima ocu-linux, compose ocu-donegate). Each is firsthand-reproduced;
none blocks the shipped M-group parity coverage. Grouped by root cause. Owner-triage.

## Cluster A: south (guest FUSE) mutations do not reconcile to the F9 north handle-store index

The F9 north list (`GET /v1/files`) is served from an append-authoritative handle-store whose
reconcile is additive-only (`reconcileEngineNamespace` mints handles for engine objects lacking
one, never prunes/updates handles whose backing bytes changed or vanished). A guest-side mutation
via the rclone FUSE mount therefore changes the object on disk but leaves the north list record
stale. This is the tracked ADR-0023 open-question #2 (engine-adapter delete/update semantics:
handle-unlink/update vs requested byte-mutation), so these are KNOWN-GAP confirmations, not new
undiscovered defects. Recording the firsthand measurements against that open question.

### F1: a guest `rm` does not remove the object from the north list
Firsthand: guest writes `/mnt/user-data/outputs/<name>` (appears in the north list within ~10s);
guest `rm <name>` succeeds (RC=0, gone from the guest FUSE view); the north `GET /v1/files` STILL
lists the object after 60s. So a guest delete is invisible to the pane. The PoC Files panel would
show a guest-side delete disappear -- whether that specific parity matters is an owner call (the
PoC may only reflect north-face deletes too; worth a firsthand PoC check before ruling the parity
gap real).

### F4: a guest overwrite does not update size/mime in the north list
Firsthand: guest writes a 5-byte object (north record size=5); guest overwrites it to 42 bytes on
disk (`wc -c`=42); the north record still shows size 5, SAME file_id, SAME created_at after 12s.
So content changes to an existing object are invisible to the north list metadata. Same additive-
reconcile root as F1.

Disposition (cluster A): file both as measurements under ADR-0023 open-question #2. The pane-facing
mutation path (north `DELETE`) DOES prune correctly (`handlestore.Delete` writes a tombstone +
removes the record); only south/FUSE mutations are unreconciled. Low severity for the current PoC
demo (the model's own outputs are append-mostly); a real fix is the deferred south->north reconcile.

## F3: the pane BFF DELETE route requires write intent the read-scoped pane token lacks
Firsthand: `DELETE /v1/files/<id>` via the pane's embed-token 403s. Root (ocu-webui
`api/v1/files/[file_id]/route.ts`): the BFF DELETE handler runs three-axis authz with
`operation:"write"`; the pane embed-token carries READ intent (it is a list/preview/download
surface). So the pane cannot delete via its own credential. This is likely DELIBERATE (a read-only
pane surface), not a defect -- recorded so a future "pane delete affordance" design knows the BFF
gate must be satisfied with a write-intent token, and so the filestore-engine authz note (delete
authorizes on scope-match without an intent axis at the engine south face) is not mistaken for the
BFF's stricter gate.

## F2: `GET /v1/files?after=<malformed-cursor>` returns 500, not 400
Firsthand: `?after=<next_cursor>` (the opaque base64 token) -> 200; `?after=<last_id>` (a raw
32-hex file_id, not a valid cursor token) -> 500. The handle-store classifies a malformed cursor as
`ErrMalformedCursor` which the wire is designed to map to 400 invalid_argument (a client fault), but
the north face returns 500 (a server error). Error-classification gap: a client fault is mis-filed
as a server error. Low severity (correct clients send `next_cursor`), but a contract-correctness
defect -- a malformed `?after` should be 400.

## Not in scope of these findings
- #182 (F9 list ascending + pane page-1-only = new file hidden at >=100 objects) is a DIFFERENT
  mechanism (ordering/pagination) with its own internal fix + 5 strict-xfails + the ADR-0031 wire
  half (owner-gated). Do not conflate.
- The pane background poll (live re-list) is present + deployed + firing (firsthand: 4 GET ticks in
  20s at the 5s interval), regression-guarded by M11.
