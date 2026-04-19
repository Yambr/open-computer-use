# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""
Tier 6 — uploaded files exposed as native MCP resources.

Clients (Agents SDK, MCP Inspector, Claude Desktop) can call `resources/list`
to see every uploaded file across every live chat, and `resources/read` to
fetch content. Upload stays on the existing POST /api/uploads/* HTTP
endpoint (MCP has no upload primitive — community consensus).

Design decisions:

- URI shape: `file://uploads/{chat_id}/{url-encoded-rel-path}`. `chat_id` is
  embedded because clients don't re-send X-Chat-Id on per-resource calls
  (headers ride only on the outer request). URIs must be self-contained.
  `rel_path` is urllib.parse.quote'd because FastMCP's ResourceTemplate
  uses a per-param regex of `[^/]+` (verified at
  .venv/.../mcp/server/fastmcp/resources/templates.py:88), so nested
  paths wouldn't match `{rel}` — we flatten via percent-encoding.

- Dynamic per-chat list: FastMCP's `ResourceManager._resources` is a plain
  dict with no `remove_resource` public API. `sync_chat_resources(chat_id)`
  clears-then-re-adds under an asyncio.Lock to avoid "dict changed size
  during iteration" when resources/list is concurrent with a new upload.
  Private-API access (`mcp._resource_manager._resources.pop`) is justified
  because the alternative is a full ResourceManager subclass. `mcp`
  version is pinned in requirements.txt to guard against attribute renames.

- Called from two places:
    * docker_manager._create_container — initial sync when the chat's
      container spins up, so any already-existing uploads are visible.
    * app.py:upload_file POST handler — after a new file is saved.

Tenancy: `X-Chat-Id` is untrusted. Any caller holding MCP_API_KEY can guess
URIs and read any chat's uploads — same model as today's /api/uploads/*
endpoints. Per-chat auth is out of scope.
"""

import asyncio
import threading
import urllib.parse

from mcp.server.fastmcp.resources import FunctionResource  # verified path

from mcp_tools import mcp
from security import sanitize_chat_id
from uploads import UploadEntry, list_chat_uploads, read_chat_upload


# MIMEs that should round-trip as text (UTF-8 decoded) rather than as bytes.
# Anything not matching `text/*` or this set is returned as bytes, which
# FastMCP encodes as a base64 blob per the MCP resources spec.
_TEXT_MIMES = frozenset({
    "application/json",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
    "application/javascript",
    "application/x-sh",
})


# threading.Lock instead of asyncio.Lock — sync_chat_resources_sync runs in
# a worker thread (asyncio.to_thread) under its own asyncio.run() loop, while
# the request-path sync_chat_resources runs on the main server loop. An
# asyncio.Lock binds to the loop that first awaits it; once bound, the other
# loop's await would either deadlock or silently no-op. The critical section
# below contains NO `await` (all dict ops are synchronous), so a plain
# threading.Lock serializes both paths correctly.
_resource_lock = threading.Lock()
# chat_id → set of URIs we registered for that chat, so we can remove them
# on the next sync without sweeping the whole _resources dict.
_chat_uris: dict[str, set[str]] = {}


def _encode(rel_path: str) -> str:
    # safe="" → encode `/` too, so `sub/nested.txt` becomes `sub%2Fnested.txt`.
    return urllib.parse.quote(rel_path, safe="")


def _build_function_resource(chat_id: str, entry: UploadEntry) -> FunctionResource:
    uri = f"file://uploads/{chat_id}/{_encode(entry.rel_path)}"

    # Capture chat_id + rel + mime as defaults so the closure doesn't
    # reference the outer loop variable.
    async def _reader(chat_id: str = chat_id, rel: str = entry.rel_path,
                      mime: str = entry.mime_type) -> str | bytes:
        data, _ = read_chat_upload(chat_id, rel)
        if mime.startswith("text/") or mime in _TEXT_MIMES:
            return data.decode("utf-8", errors="replace")
        return data

    return FunctionResource(
        uri=uri,  # type: ignore[arg-type]  # FastMCP accepts str, validates internally
        name=f"{chat_id}/{entry.name}",
        description=f"Uploaded file ({entry.size} bytes, {entry.mime_type})",
        mime_type=entry.mime_type,
        fn=_reader,
    )


async def sync_chat_resources(chat_id: str) -> int:
    """
    Clear previously-registered upload resources for `chat_id` and re-register
    from the current filesystem state. Returns the count of registered entries.

    Holds _resource_lock so a concurrent list_resources() won't see a dict
    mutating mid-iteration. Private-API access into
    mcp._resource_manager._resources is covered by the mcp version pin.

    Emits notifications/resources/list_changed when the set of URIs for this
    chat actually changed AND a request-scoped session is available
    (`request_ctx` ContextVar set). Skipped silently outside a request context
    (e.g. _create_container from a worker thread) — clients still see the
    fresh list on their next resources/list call.
    """
    # Normalize at the boundary so case/whitespace variants of chat_id
    # share the same _chat_uris entry (files in uploads.py are also keyed
    # by sanitized chat_id, so out-of-band variants would otherwise leak
    # stale registrations).
    chat_id = sanitize_chat_id(chat_id)

    # Build new resources OUTSIDE the lock — list_chat_uploads scans the
    # filesystem and may be slow. We only need the lock to protect the
    # registry mutation window. Doing the FS scan + resource construction
    # under the lock would block all other syncs (and any future
    # list_resources callers that take the same lock) for the scan duration.
    new_entries = list_chat_uploads(chat_id)
    new_resources = [(_build_function_resource(chat_id, e)) for e in new_entries]
    fresh: set[str] = {str(r.uri) for r in new_resources}

    changed = False
    # Critical section: must contain NO `await` so list_resources() (which
    # currently does NOT take this lock) cannot observe a half-swapped
    # registry. The window is now O(len(stale) + len(fresh)) dict ops only.
    # threading.Lock works across event loops — see _resource_lock comment.
    with _resource_lock:
        stale = _chat_uris.pop(chat_id, set())
        registry = mcp._resource_manager._resources
        # Remove stale entries that are NOT in the fresh set (idempotent
        # re-sync should not flap visible URIs).
        for uri in stale - fresh:
            registry.pop(uri, None)
        for resource in new_resources:
            registry[str(resource.uri)] = resource
        _chat_uris[chat_id] = fresh
        changed = fresh != stale

    if changed:
        try:
            session = mcp._mcp_server.request_context.session
            await session.send_resource_list_changed()
        except LookupError:
            # No active request context (e.g. called from docker_manager
            # during container creation in a worker thread). Skip —
            # clients will see the updated list next time they poll.
            pass
        except Exception as e:
            print(f"[MCP] resource list_changed notification failed: {e}")

    return len(fresh)


def sync_chat_resources_sync(chat_id: str) -> int:
    """
    Sync wrapper for worker-thread callers (docker_manager._create_container).
    Same asyncio.run() justification as render_system_prompt_sync:
    _create_container runs inside asyncio.to_thread — no running loop → safe.
    """
    return asyncio.run(sync_chat_resources(chat_id))
