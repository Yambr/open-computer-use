# Platform defect: O_TRUNC-on-an-existing file fails on the outputs FUSE surface

Severity: HIGH. Class: silent data loss on the common `command > existing_file` path.

## One-sentence statement

Opening an existing file with `O_TRUNC` on the `/mnt/user-data/outputs` FUSE
surface fails at close: the object keeps its prior content (mtime updated, size
unchanged); a shell redirect (`echo x > existing`) exits 0 and loses the write
silently, while `cp` over an existing file and Python `open(existing, 'w')`
fail loudly with `EIO`.

## Firsthand behavior matrix (live stand, real MCP -> gateway -> guest leg)

| Operation on `/mnt/user-data/outputs` | Result | Mechanism |
|---|---|---|
| `printf X > NEWfile` (O_CREAT, no existing) | works | create, no truncate |
| `echo X > EXISTINGfile` (O_TRUNC) | rc=0, content UNCHANGED (silent loss) | shell discards the close(2) EIO on a redirect |
| `cp SRC EXISTINGfile` (O_TRUNC dest) | loud `EIO`, content unchanged | cp checks close; surfaces the error |
| Python `open(EXISTING, 'w')` (O_TRUNC) | loud `OSError(5)`, content unchanged | Python raises on the close EIO |
| `echo X >> EXISTINGfile` (append) | works | append does not truncate |
| `sed -i` | works | writes a temp file, then rename-over-existing |
| `mv SRC EXISTINGfile` (rename) | works | rename-over-existing is supported |
| `str_replace` / `create_file` (r+ seek/write/truncate) | works | in-place r+, no O_TRUNC-on-open |

The loud-vs-silent split is a shell-semantics artifact, not two different FUSE
behaviors: the underlying surface rejects the truncate at close for every
O_TRUNC-on-existing caller; the shell is the only one that swallows the error.

## Same presentation on the read-only uploads mount

The identical bash-swallows-close-error presentation also appears on the
read-only `/mnt/user-data/uploads` mount, and it is NOT a separate defect. The
uploads mount is genuinely kernel read-only (`/proc/mounts` shows `fuse ro`;
MS_RDONLY is active). A guest write there is rejected with a loud EROFS for any
caller that checks close -- `python open('w')` returns `OSError(30, 'Read-only
file system')`, `touch` prints `Read-only file system` -- but a shell
`printf x > uploads_file` still exits 0 because bash discards the close(2) error
on the redirect. The read-only tamper invariant HOLDS (nothing persists; see
`test_j5b_guest_cannot_tamper_existing_upload`); only the shell-redirect exit
code is misleading, via this same mechanism. Fix the shell-`>` presentation once
here and both surfaces read cleanly.

## Root layer

The guest mounts via rclone's `cmd/mount2` **DirectMountStrict** path (go-fuse
direct `mount(2)`; see `ocu-rclone-filestore/internal/mounter/directmount.go`),
not the classic cached-VFS mount frontend. `vfs-cache-mode` is therefore not on
the truncate path: changing control's default from `writes` to `full`
(`ocu-control/cmd/ocu-controld/main.go`, `defaultMountDefaults`) was tested
firsthand and did NOT change the behavior -- the loud Python `EIO` was
byte-identical under both modes. The rejection is the go-fuse `SetAttr(size=0)`
-> VFS Truncate against an object backend that cannot represent an in-place
truncate.

Ruled out as fixes (firsthand): `vfs-cache-mode=full` (byte-identical to
`writes` on both the silent shell loss and the loud Python EIO -- do not
re-propose). `--vfs-write-back`, `--no-modtime`, `--vfs-cache-poll-interval`
tune the same bracketed-out VFS cache layer and cannot change the outcome.

Untested option for the owner (NOT tried; evaluate only after the trace routes
the ticket): `--write-back-cache` (FUSE `writeback_cache` mount option). It
changes the kernel-side protocol, but gVisor sentry support is doubtful and its
failure mode converts the loud Python EIO into a second silent-loss path --
strictly worse if it half-works. Do not enable without the trace verdict.

## Next diagnostic (ticket owner): step 1

Capture an rclone debug trace during the repro to route this ticket. The trace
verdict decides the owning layer.

Change (mount-cmd builder, `ocu-rclone-filestore/internal/mounter`): a
`--log-file /tmp/rclone-mount.log` sink at DEBUG. `-vv` / stderr is not enough
here -- rclone freezes its stderr log gate at NOTICE on import and mutating
`fs.GetConfig(ctx).LogLevel` does not lift it (see `internal/mounter/diag.go`),
so the level must be set at mount construction and the sink must be a file, not
stderr. Rebuild control-minted mount argv, not a manual in-guest mount: the
mount config is scrubbed after load (NFR-SEC-25), so a hand-run second mount
cannot read it.

Protocol (non-vacuous): run case 1 (`> NEWfile`) FIRST as the positive control
-- its `OpenFile`/`Write` entries prove logging is live -- then case 2
(`> EXISTING`) and case 5 (python `open('w')`). Read the log for the target
path.

Verdict:
- case-1 ops present, case-2/5 open-or-setattr ABSENT -> the gVisor sentry FUSE
  passthrough eats the truncate -> upstream gVisor / guest FUSE client ticket.
- ops present and erroring in rclone (`Setattr`/`Truncate`, `Flush`) -> rclone
  mount2 VFS / object-backend truncate path -> our mount layer or upstream
  rclone.

Revert the flag after capture.

## Mitigation shipped

- **File-edit tools use r+**, not O_TRUNC-on-open: `create_file` and
  `str_replace` (gateway `projection.go`) seek/write/truncate in place, so the
  model's file-editing path never trips this. Covered by journey `test_i10`.
- **System-prompt steering** (`openwebui/system_prompt.txt`): the model is told
  to edit existing outputs with `str_replace`/`create_file` and not to overwrite
  them with a shell redirect or `cp`.

These mitigate the model's common path; the platform defect for a raw shell
`>`-overwrite remains open pending the trace above.
