"""
File Server for Computer Use Outputs + MCP Endpoint

Provides:
1. HTTP API for file upload/download
2. MCP (Model Context Protocol) endpoint for Computer Use tools

See /docs for Swagger UI, /redoc for ReDoc, / for HTML documentation.
"""

import os
import asyncio
import html as html_module
import hashlib
import json
import mimetypes
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, List, Any

import aiohttp
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Request, Response, Depends, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from system_prompt import SYSTEM_PROMPT_TEMPLATE, build_system_prompt
from docker_manager import get_container_cdp_address, FILE_SERVER_URL
import skill_manager


# =============================================================================
# MCP Authorization
# =============================================================================

MCP_API_KEY = os.getenv("MCP_API_KEY")  # Required for /mcp endpoints

security = HTTPBearer(auto_error=False)


async def verify_mcp_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify Bearer token for MCP endpoints."""
    if not MCP_API_KEY:
        # If no key configured, allow all requests (development mode)
        return None

    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if credentials.credentials != MCP_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return credentials.credentials


# =============================================================================
# Pydantic Models for Swagger Documentation
# =============================================================================

class MCPRequest(BaseModel):
    """MCP JSON-RPC Request"""
    jsonrpc: str = Field(default="2.0", description="JSON-RPC version")
    id: int = Field(..., description="Request ID")
    method: str = Field(..., description="MCP method: initialize, tools/list, tools/call")
    params: Dict[str, Any] = Field(default={}, description="Method parameters")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"}
                    }
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "bash_tool",
                        "arguments": {"command": "echo hello", "description": "test"}
                    }
                }
            ]
        }
    }


class MCPResponse(BaseModel):
    """MCP JSON-RPC Response"""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class MCPToolInfo(BaseModel):
    """MCP Tool information"""
    name: str
    description: str


class MCPInfo(BaseModel):
    """MCP Server information"""
    name: str
    version: str
    description: str
    tools: List[MCPToolInfo]
    headers: Dict[str, List[str]]


class UploadResponse(BaseModel):
    """File upload response"""
    status: str
    filename: str
    size: int
    md5: str


# =============================================================================
# FastAPI Application
# =============================================================================

SWAGGER_DESCRIPTION = """
## Computer Use Server + MCP

HTTP API for file upload/download and **MCP (Model Context Protocol)** endpoint for Computer Use tools.

### Quick Start

```bash
# Step 1: Initialize (get session ID)
curl -sD - -X POST "http://localhost:8081/mcp" \\
  -H "Authorization: Bearer <MCP_API_KEY>" \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json, text/event-stream" \\
  -H "X-Chat-Id: my-session" \\
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
# Response contains header: mcp-session-id: <SESSION_ID>

# Step 2: Call a tool
curl -s -X POST "http://localhost:8081/mcp" \\
  -H "Authorization: Bearer <MCP_API_KEY>" \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json, text/event-stream" \\
  -H "Mcp-Session-Id: <SESSION_ID>" \\
  -H "X-Chat-Id: my-session" \\
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"bash_tool","arguments":{"command":"echo Hello","description":"test"}}}'
```

### MCP Tools

- **bash_tool** - execute bash commands in isolated Docker container
- **view** - view files and directories
- **create_file** - create new files
- **str_replace** - edit files (text replacement)
- **sub_agent** - delegate tasks to autonomous agent (Claude Code)
"""

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan: start MCP session manager for Streamable HTTP."""
    try:
        from mcp_tools import mcp as _mcp_server
        if _mcp_server._session_manager is None:
            _mcp_server.streamable_http_app()  # triggers lazy init of session_manager
        async with _mcp_server.session_manager.run():
            yield
    except ImportError:
        yield

app = FastAPI(
    title="Computer Use File Server + MCP",
    description=SWAGGER_DESCRIPTION,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "MCP", "description": "Model Context Protocol endpoint for Computer Use tools"},
        {"name": "Files", "description": "File upload and download"},
        {"name": "System", "description": "Health check and service information"},
    ]
)

# CORS — needed for preview SPA loaded inside iframe (opaque origin → cross-origin fetch)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Static files (bundled JS/CSS libraries)
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Base directory where chat data is stored
# Mounted from host: /tmp/computer-use-data/{chat_id}/outputs/
BASE_DATA_DIR = Path("/data")


# =============================================================================
# File Classification for Preview
# =============================================================================

_CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.css', '.json', '.yaml', '.yml',
    '.toml', '.sh', '.bash', '.sql', '.go', '.rs', '.java', '.c', '.cpp',
    '.h', '.hpp', '.rb', '.php', '.swift', '.kt', '.scala', '.r', '.m',
    '.vue', '.svelte', '.xml', '.dockerfile',
}

_TEXT_EXTENSIONS = {'.txt', '.log', '.ini', '.cfg', '.conf', '.env'}

_MARKDOWN_EXTENSIONS = {'.md', '.markdown'}

_SPREADSHEET_EXTENSIONS = {'.csv', '.tsv'}

_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}

_AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.wma'}
_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mkv', '.mov', '.avi'}


def classify_file(filename: str) -> tuple:
    """Classify file by extension. Returns (type_category, mime_type)."""
    ext = Path(filename).suffix.lower()
    mime, _ = mimetypes.guess_type(filename)
    if mime is None:
        mime = 'application/octet-stream'

    if ext in ('.html', '.htm'):
        return 'html', mime
    if ext in _IMAGE_EXTENSIONS:
        return 'image', mime
    if ext in _AUDIO_EXTENSIONS:
        return 'audio', mime or 'audio/mpeg'
    if ext in _VIDEO_EXTENSIONS:
        return 'video', mime or 'video/mp4'
    if ext == '.pdf':
        return 'pdf', 'application/pdf'
    if ext in _MARKDOWN_EXTENSIONS:
        return 'markdown', 'text/markdown'
    if ext in _SPREADSHEET_EXTENSIONS:
        return 'spreadsheet', mime
    if ext == '.docx':
        return 'docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if ext in ('.xlsx', '.xls'):
        return 'xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if ext == '.pptx':
        return 'pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    if ext == '.drawio':
        return 'drawio', 'application/xml'
    if ext in _CODE_EXTENSIONS:
        return 'code', mime
    if ext in _TEXT_EXTENSIONS:
        return 'text', mime
    # Fallback: check mime type
    if mime.startswith('image/'):
        return 'image', mime
    if mime.startswith('audio/'):
        return 'audio', mime
    if mime.startswith('video/'):
        return 'video', mime
    if mime.startswith('text/'):
        return 'text', mime
    return 'other', mime


def format_size(size_bytes: int) -> str:
    """Format file size for display."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


_FILE_ICONS = {
    'html': '🌐', 'image': '🖼️', 'code': '📝', 'text': '📄',
    'pdf': '📕', 'markdown': '📃', 'spreadsheet': '📊',
    'docx': '📄', 'xlsx': '📊', 'pptx': '📊',
    'audio': '🎵', 'video': '🎬', 'other': '📎',
}



@app.get("/", response_class=HTMLResponse, tags=["System"], include_in_schema=False)
async def root():
    """Main page with MCP and File API documentation"""
    from docs_html import get_root_html
    return get_root_html()

@app.get("/api/uploads/{chat_id}/manifest", tags=["Files"])
async def get_uploads_manifest(chat_id: str) -> Dict[str, str]:
    """
    Get manifest of uploaded files with their MD5 checksums.

    Args:
        chat_id: Unique chat identifier

    Returns:
        Dictionary mapping filename to MD5 checksum
        Example: {"file1.txt": "abc123def456", "doc.pdf": "789xyz"}
    """
    uploads_dir = BASE_DATA_DIR / chat_id / "uploads"

    # Return empty dict if directory doesn't exist yet
    if not uploads_dir.exists():
        return {}

    manifest = {}

    # Scan all files in uploads directory
    for file_path in uploads_dir.rglob("*"):
        if file_path.is_file():
            # Calculate MD5 checksum
            md5_hash = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    md5_hash.update(chunk)

            # Use relative filename as key
            relative_name = file_path.relative_to(uploads_dir)
            manifest[str(relative_name)] = md5_hash.hexdigest()

    return manifest


@app.get("/api/uploads/{chat_id}/list", tags=["Files"])
async def list_uploads(chat_id: str, response: Response):
    """List all files in the uploads directory with metadata."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    uploads_dir = BASE_DATA_DIR / chat_id / "uploads"
    if not uploads_dir.exists():
        return {"files": [], "total": 0}
    files = []
    for fp in uploads_dir.rglob("*"):
        if not fp.is_file():
            continue
        rel = fp.relative_to(uploads_dir)
        stat = fp.stat()
        files.append({
            "name": fp.name,
            "path": str(rel),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "container_path": f"/mnt/user-data/uploads/{rel}",
        })
    files.sort(key=lambda f: f["modified"], reverse=True)
    return {"files": files, "total": len(files)}


@app.post("/api/uploads/{chat_id}/{filename:path}", tags=["Files"], response_model=UploadResponse)
async def upload_file(chat_id: str, filename: str, file: UploadFile = File(...)):
    """
    Upload a file to chat uploads directory.

    Args:
        chat_id: Unique chat identifier
        filename: Target filename (can include subdirectories)
        file: File to upload

    Returns:
        Success message with file info

    Raises:
        400: Invalid filename or security violation
    """
    # Create uploads directory if it doesn't exist
    uploads_dir = BASE_DATA_DIR / chat_id / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Construct target path
    file_path = uploads_dir / filename

    # Security: ensure path is within uploads directory
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(uploads_dir.resolve())):
            raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid path")

    # Create parent directories if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Save file
    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Calculate MD5 for confirmation
        md5_hash = hashlib.md5(content).hexdigest()

        return {
            "status": "success",
            "filename": filename,
            "size": len(content),
            "md5": md5_hash
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")


@app.get("/files/{chat_id}/archive", tags=["Files"])
async def download_archive(chat_id: str):
    """
    Download entire outputs directory as a zip archive.

    Args:
        chat_id: Unique chat identifier

    Returns:
        StreamingResponse with zip archive

    Raises:
        404: Directory not found or empty
    """
    # Construct outputs directory path
    outputs_dir = BASE_DATA_DIR / chat_id / "outputs"

    # Check if directory exists
    if not outputs_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Outputs directory not found for chat: {chat_id}"
        )

    if not outputs_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Path is not a directory"
        )

    # Get all files in directory
    files = list(outputs_dir.rglob("*"))
    files = [f for f in files if f.is_file()]

    if not files:
        raise HTTPException(
            status_code=404,
            detail="No files found in outputs directory"
        )

    # Create zip archive in memory
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in files:
            # Add file to zip with relative path
            arcname = file_path.relative_to(outputs_dir)
            zip_file.write(file_path, arcname=str(arcname))

    # Seek to beginning of buffer
    zip_buffer.seek(0)

    # Return as streaming response
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=chat-{chat_id}-outputs.zip"
        }
    )


@app.get("/files/{chat_id}/{filename:path}", tags=["Files"])
async def download_file(chat_id: str, filename: str, download: Optional[int] = None):
    """
    Download a specific file from chat outputs directory.

    Args:
        chat_id: Unique chat identifier
        filename: File name (can include subdirectories)

    Returns:
        FileResponse with the requested file

    Raises:
        404: File not found
    """
    # Construct full path
    file_path = BASE_DATA_DIR / chat_id / "outputs" / filename

    # Security: ensure path is within allowed directory
    try:
        file_path = file_path.resolve()
        BASE_DATA_DIR.resolve()
        if not str(file_path).startswith(str(BASE_DATA_DIR.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid path")

    # Check if file exists
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {filename}"
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Path is not a file: {filename}"
        )

    # Return file
    # ?download=1 → force download (Content-Disposition: attachment)
    # default → serve with real MIME type (browser displays inline)
    if download:
        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type="application/octet-stream"
        )
    else:
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type=mime_type
        )


# =============================================================================
# Output Files API + Preview
# =============================================================================

@app.get("/api/outputs/{chat_id}", tags=["Files"])
async def list_outputs(chat_id: str, response: Response):
    """List all files in the outputs directory with metadata."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

    outputs_dir = BASE_DATA_DIR / chat_id / "outputs"

    if not outputs_dir.exists():
        return {"chat_id": chat_id, "files": [], "total": 0, "timestamp": time.time()}

    files = []

    for file_path in outputs_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name.startswith('.'):
            continue
        relative = file_path.relative_to(outputs_dir)
        file_type, mime = classify_file(str(relative))
        stat = file_path.stat()
        files.append({
            "name": file_path.name,
            "path": str(relative),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "type": file_type,
            "mime": mime,
            "url": f"/files/{chat_id}/{relative}",
        })

    files.sort(key=lambda f: f["modified"], reverse=True)
    return {"chat_id": chat_id, "files": files, "total": len(files), "timestamp": time.time()}


# =============================================================================
# Browser CDP Proxy — live browser viewer
# =============================================================================

@app.get("/browser/{chat_id}/status", tags=["Browser"])
async def browser_status(chat_id: str, response: Response):
    """Check if browser (Chromium CDP) is running in the chat's container."""
    response.headers["Cache-Control"] = "no-cache, no-store"
    container_ip = get_container_cdp_address(chat_id)
    if not container_ip:
        return {"active": False, "pages": []}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{container_ip}:9222/json",
                timeout=aiohttp.ClientTimeout(total=2)
            ) as resp:
                pages = await resp.json()
                return {
                    "active": True,
                    "pages": [
                        {"id": p.get("id", ""), "title": p.get("title", ""), "url": p.get("url", "")}
                        for p in pages
                        if p.get("type") == "page"
                    ]
                }
    except Exception:
        return {"active": False, "pages": []}


@app.get("/browser/{chat_id}/json", tags=["Browser"])
async def browser_cdp_json(chat_id: str):
    """Proxy CDP /json endpoint from container."""
    container_ip = get_container_cdp_address(chat_id)
    if not container_ip:
        raise HTTPException(404, "Container not found or not running")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{container_ip}:9222/json",
                timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                return await resp.json()
    except Exception:
        raise HTTPException(503, "Browser not available")


@app.get("/browser/{chat_id}/json/version", tags=["Browser"])
async def browser_cdp_json_version(chat_id: str):
    """Proxy CDP /json/version endpoint from container."""
    container_ip = get_container_cdp_address(chat_id)
    if not container_ip:
        raise HTTPException(404, "Container not found or not running")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{container_ip}:9222/json/version",
                timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                return await resp.json()
    except Exception:
        raise HTTPException(503, "Browser not available")


@app.websocket("/browser/{chat_id}/devtools/page/{page_id}")
async def browser_ws_proxy(websocket: WebSocket, chat_id: str, page_id: str):
    """Bidirectional WebSocket proxy for CDP — connects browser viewer to container's Chromium."""
    container_ip = get_container_cdp_address(chat_id)
    if not container_ip:
        await websocket.close(code=1008, reason="Container not found")
        return

    await websocket.accept()

    backend_url = f"ws://{container_ip}:9222/devtools/page/{page_id}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(backend_url) as backend_ws:
                async def forward_client_to_backend():
                    try:
                        while True:
                            data = await websocket.receive_text()
                            await backend_ws.send_str(data)
                    except WebSocketDisconnect:
                        pass
                    except Exception:
                        pass
                    finally:
                        await backend_ws.close()

                async def forward_backend_to_client():
                    try:
                        async for msg in backend_ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await websocket.send_text(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    except Exception:
                        pass
                    finally:
                        try:
                            await websocket.close()
                        except Exception:
                            pass

                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(forward_client_to_backend()),
                        asyncio.create_task(forward_backend_to_client()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
    except Exception:
        try:
            await websocket.close(code=1011, reason="Backend connection failed")
        except Exception:
            pass



# =============================================================================
# Terminal Proxy — ttyd WebSocket terminal (like Browser CDP proxy)
# =============================================================================

def _get_container_for_terminal(chat_id: str):
    """Get running container for terminal access. Does NOT create containers."""
    import re as _re
    from docker_manager import get_docker_client
    client = get_docker_client()
    sanitized_id = _re.sub(r'[^a-zA-Z0-9_.-]', '-', chat_id)
    container_name = f"owui-chat-{sanitized_id}"
    try:
        c = client.containers.get(container_name)
        c.reload()
        if c.status == "running":
            return c
    except Exception:
        pass
    return None


def _get_container_stopped(chat_id: str):
    """Find a stopped (but not removed) container for this chat."""
    import re as _re
    from docker_manager import get_docker_client
    client = get_docker_client()
    sanitized_id = _re.sub(r'[^a-zA-Z0-9_.-]', '-', chat_id)
    container_name = f"owui-chat-{sanitized_id}"
    try:
        c = client.containers.get(container_name)
        c.reload()
        if c.status in ("exited", "created"):
            return c
    except Exception:
        pass
    return None


@app.get("/terminal/{chat_id}/status", tags=["Terminal"])
async def terminal_status(chat_id: str, response: Response):
    """Check if ttyd terminal is available in the chat's container."""
    response.headers["Cache-Control"] = "no-cache, no-store"
    container_ip = get_container_cdp_address(chat_id)
    if not container_ip:
        # Check if container exists but is stopped
        container = _get_container_stopped(chat_id)
        if container:
            return {"active": False, "container_stopped": True}
        # Container removed — check if .meta.json exists for resurrection
        from docker_manager import load_container_meta
        if load_container_meta(chat_id):
            return {"active": False, "meta_exists": True}
        return {"active": False}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{container_ip}:7681/",
                timeout=aiohttp.ClientTimeout(total=2)
            ) as resp:
                return {"active": resp.status == 200}
    except Exception:
        return {"active": False}


class StartTtydRequest(BaseModel):
    dangerous_mode: bool = False


@app.post("/terminal/{chat_id}/start-ttyd", tags=["Terminal"])
async def start_ttyd(chat_id: str, body: StartTtydRequest = Body(default=StartTtydRequest())):
    """Start ttyd + tmux in the container (lazy start).

    Uses tmux -A (attach-if-exists) so reconnections work without errors.
    If dangerous_mode=True, sets CLAUDE_AUTOSTARTED=1 so .bashrc skips auto-launch —
    the frontend will inject `claude --dangerously-skip-permissions` after connecting.
    """
    from docker_manager import _execute_bash
    container = _get_container_for_terminal(chat_id)
    if not container:
        raise HTTPException(404, "Container not running")
    # Check if already running
    check = await asyncio.to_thread(
        _execute_bash, container,
        "pgrep -x ttyd > /dev/null 2>&1 && echo RUNNING || echo STOPPED", 5)
    if "RUNNING" in check.get("output", ""):
        return {"started": False, "already_running": True}
    # Start ttyd + tmux in background (-A = attach if session exists, create if not)
    env_prefix = "CLAUDE_AUTOSTARTED=1 " if body.dangerous_mode else ""
    await asyncio.to_thread(
        _execute_bash, container,
        f"cd /home/assistant && echo 'set -g mouse on' > ~/.tmux.conf && LANG=C.UTF-8 {env_prefix}nohup ttyd -W -p 7681 tmux -u new-session -A -s main bash > /dev/null 2>&1 &", 5)
    # Wait briefly for ttyd to start
    await asyncio.sleep(0.5)
    return {"started": True}


@app.post("/terminal/{chat_id}/stop-ttyd", tags=["Terminal"])
async def stop_ttyd(chat_id: str):
    """Stop ttyd + tmux in the container so next start is fresh (with .bashrc autostart)."""
    from docker_manager import _execute_bash
    container = _get_container_for_terminal(chat_id)
    if not container:
        raise HTTPException(404, "Container not running")
    await asyncio.to_thread(
        _execute_bash, container,
        "pkill -x ttyd 2>/dev/null; tmux kill-server 2>/dev/null; true", 5)
    return {"stopped": True}


@app.post("/terminal/{chat_id}/restart-container", tags=["Terminal"])
async def restart_container(chat_id: str):
    """Restart a stopped container. Handles dead networks after deploy."""
    container = _get_container_stopped(chat_id)
    if not container:
        raise HTTPException(404, "No stopped container found")
    try:
        from docker_manager import get_docker_client, _get_compose_network_name
        client = get_docker_client()

        # Disconnect from dead networks (left over after docker-compose down/up)
        container.reload()
        old_nets = list(container.attrs.get("NetworkSettings", {}).get("Networks", {}).keys())
        for net_name in old_nets:
            try:
                net = client.networks.get(net_name)
                net.disconnect(container, force=True)
            except Exception:
                pass  # Network already dead — ignore

        # Connect to current compose network (force refresh — network ID changed after deploy)
        compose_net = _get_compose_network_name(force_refresh=True)
        if compose_net:
            try:
                net = client.networks.get(compose_net)
                net.connect(container)
            except Exception as e:
                print(f"[RESTART] Warning: could not connect to {compose_net}: {e}")

        await asyncio.to_thread(container.start)
        await asyncio.sleep(2)  # Wait for entrypoint
        return {"restarted": True}
    except Exception as e:
        raise HTTPException(500, f"Failed to restart: {e}")


@app.post("/terminal/{chat_id}/resurrect-container", tags=["Terminal"])
async def resurrect_container(chat_id: str):
    """Recreate a removed container using saved .meta.json and existing host data.

    Used when container was removed by cron but /data/{chat_id}/.meta.json
    still exists. Restores user identity (email, name, MCP servers) from saved metadata.
    """
    import re as _re
    from docker_manager import load_container_meta, _create_container, _ensure_gitlab_token
    from context_vars import (
        current_chat_id, current_user_email, current_user_name,
        current_mcp_servers,
    )

    # Guard: container must not already exist
    existing = _get_container_for_terminal(chat_id) or _get_container_stopped(chat_id)
    if existing:
        raise HTTPException(409, "Container already exists. Use restart-container instead.")

    meta = load_container_meta(chat_id)
    if not meta:
        raise HTTPException(404, "No .meta.json found for this chat")

    # Set context vars from saved metadata (non-secret only).
    # Tokens (ANTHROPIC_AUTH_TOKEN, VISION_*) come from computer-use-orchestrator ENV
    # via fallback in _create_container.
    current_chat_id.set(chat_id)
    user_email = meta.get("user_email", "")
    user_name = meta.get("user_name", "")
    mcp_servers = meta.get("mcp_servers", "")
    if user_email:
        current_user_email.set(user_email)
    if user_name:
        current_user_name.set(user_name)
    if mcp_servers:
        current_mcp_servers.set(mcp_servers)

    # Fetch fresh GitLab token by email (never stored on disk)
    await _ensure_gitlab_token()

    sanitized_id = _re.sub(r'[^a-zA-Z0-9_.-]', '-', chat_id)
    container_name = f"owui-chat-{sanitized_id}"

    try:
        print(f"[RESURRECT] Recreating {container_name} for {user_email}")
        await asyncio.to_thread(_create_container, chat_id, container_name)
        await asyncio.sleep(2)  # Wait for entrypoint
        return {"resurrected": True, "user_email": user_email}
    except Exception as e:
        raise HTTPException(500, f"Failed to resurrect container: {e}")


@app.get("/terminal/{chat_id}/sessions", tags=["Terminal"])
async def terminal_sessions(chat_id: str, response: Response):
    """List Claude Code JSONL sessions from the container."""
    response.headers["Cache-Control"] = "no-cache, no-store"
    from docker_manager import _execute_bash
    container = _get_container_for_terminal(chat_id)
    if not container:
        return {"sessions": []}
    result = await asyncio.to_thread(
        _execute_bash, container,
        r"""for f in $(ls -t /home/assistant/.claude/projects/-home-assistant/*.jsonl /root/.claude/projects/-home-assistant/*.jsonl 2>/dev/null | sort -u | head -20); do
            sid=$(basename "$f" .jsonl)
            model=$(grep -o '"model":"[^"]*"' "$f" 2>/dev/null | head -1 | cut -d'"' -f4)
            ts=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
            label=$(grep -m1 '"type":"user"' "$f" 2>/dev/null | sed 's/.*"content":\s*"//' | sed 's/".*//' | cut -c1-80)
            echo "$sid|$model|$ts|$label"
        done""", 10)
    sessions = []
    for line in (result.get("output", "") or "").strip().split("\n"):
        if not line.strip() or "|" not in line:
            continue
        parts = line.strip().split("|", 3)
        if len(parts) >= 3:
            sessions.append({
                "session_id": parts[0],
                "model": parts[1] or "unknown",
                "timestamp": float(parts[2]) if parts[2] else 0,
                "label": parts[3].strip() if len(parts) > 3 else "",
            })
    return {"sessions": sessions}


@app.get("/terminal/{chat_id}/processes", tags=["Terminal"])
async def terminal_processes(chat_id: str, response: Response):
    """List running Claude processes in the container."""
    response.headers["Cache-Control"] = "no-cache, no-store"
    from docker_manager import _execute_bash
    container = _get_container_for_terminal(chat_id)
    if not container:
        return {"processes": []}
    result = await asyncio.to_thread(
        _execute_bash, container,
        r"ps -eo pid,etimes,args --no-headers 2>/dev/null | grep '[c]laude-code/cli.js' | head -10", 10)
    processes = []
    for line in (result.get("output", "") or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) >= 3:
            try:
                pid = int(parts[0])
                elapsed_sec = int(parts[1])
                command = parts[2]
                processes.append({
                    "pid": pid,
                    "elapsed_minutes": elapsed_sec // 60,
                    "command": command[:100],  # truncate for display
                })
            except (ValueError, IndexError):
                continue
    return {"processes": processes}


@app.post("/terminal/{chat_id}/processes/{pid}/kill", tags=["Terminal"])
async def kill_terminal_process(chat_id: str, pid: int):
    """Kill a Claude process in the container by PID."""
    container = _get_container_for_terminal(chat_id)
    if not container:
        raise HTTPException(404, "Container not running")
    # Validate: only kill claude processes (not PID 1 or random processes)
    def _do_kill():
        check = container.exec_run(
            ["bash", "-c", f"ps -p {pid} -o args= 2>/dev/null | grep -q claude && echo OK || echo DENIED"],
            demux=True)
        stdout = (check.output[0] or b"").decode().strip() if check.output else ""
        if "OK" not in stdout:
            return False
        # SIGTERM first, then SIGKILL if still alive after 2s
        container.exec_run(["kill", "-15", str(pid)])
        import time; time.sleep(2)
        alive = container.exec_run(
            ["bash", "-c", f"kill -0 {pid} 2>/dev/null && echo ALIVE || echo DEAD"],
            demux=True)
        alive_out = (alive.output[0] or b"").decode().strip() if alive.output else ""
        if "ALIVE" in alive_out:
            container.exec_run(["kill", "-9", str(pid)])
        return True
    killed = await asyncio.to_thread(_do_kill)
    if not killed:
        raise HTTPException(400, "Can only kill Claude processes")
    return {"killed": True, "pid": pid}


@app.get("/terminal/{chat_id}/heartbeat", tags=["Terminal"])
async def terminal_heartbeat(chat_id: str):
    """Reset container idle timer. Called by JS every 2 min while page is open."""
    container = _get_container_for_terminal(chat_id)
    if container:
        from docker_manager import _reset_shutdown_timer
        await asyncio.to_thread(_reset_shutdown_timer, container)
    return {"ok": True}


@app.websocket("/terminal/{chat_id}/ws")
async def terminal_ws_proxy(websocket: WebSocket, chat_id: str):
    """Bidirectional WebSocket proxy — connects xterm.js to container's ttyd."""
    container_ip = get_container_cdp_address(chat_id)
    if not container_ip:
        await websocket.close(code=1008, reason="Container not found")
        return

    await websocket.accept(subprotocol="tty")

    backend_url = f"ws://{container_ip}:7681/ws"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(backend_url, protocols=["tty"]) as backend_ws:
                async def forward_client_to_backend():
                    try:
                        while True:
                            msg = await websocket.receive()
                            if msg["type"] == "websocket.disconnect":
                                break
                            if msg.get("bytes"):
                                await backend_ws.send_bytes(msg["bytes"])
                            elif msg.get("text"):
                                await backend_ws.send_str(msg["text"])
                    except WebSocketDisconnect:
                        pass
                    except Exception:
                        pass
                    finally:
                        await backend_ws.close()

                async def forward_backend_to_client():
                    try:
                        async for msg in backend_ws:
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                await websocket.send_bytes(msg.data)
                            elif msg.type == aiohttp.WSMsgType.TEXT:
                                await websocket.send_text(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    except Exception:
                        pass
                    finally:
                        try:
                            await websocket.close()
                        except Exception:
                            pass

                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(forward_client_to_backend()),
                        asyncio.create_task(forward_backend_to_client()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
    except Exception:
        try:
            await websocket.close(code=1011, reason="Backend connection failed")
        except Exception:
            pass


@app.get("/preview/{chat_id}", response_class=HTMLResponse, tags=["Files"])
async def preview_page(chat_id: str, response: Response):
    """
    Self-contained file preview SPA.
    Shows output files with auto-refresh, file navigation, and type-specific preview.
    Designed to be embedded in an iframe (Open WebUI Artifacts panel).
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    # Use relative URLs so it works behind HTTPS reverse proxy
    api_url = f"/api/outputs/{chat_id}"
    files_base = f"/files/{chat_id}"

    return _generate_preview_html(chat_id, api_url, files_base)


def _generate_preview_html(chat_id: str, api_url: str, files_base: str) -> str:
    """Generate the preview SPA HTML page."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>File Preview</title>
<link rel="stylesheet" href="/static/preview.css">
<link rel="stylesheet" href="/static/github.min.css" media="(prefers-color-scheme: light)">
<link rel="stylesheet" href="/static/github-dark.min.css" media="(prefers-color-scheme: dark)">
<link rel="stylesheet" href="/static/katex/katex.min.css">
<link rel="stylesheet" href="/static/xterm.css">
<script src="/static/highlight.min.js"></script>
<script src="/static/highlightjs-line-numbers.min.js"></script>
<script src="/static/marked.min.js"></script>
<script src="/static/xterm.min.js"></script>
<script src="/static/xterm-addon-fit.min.js"></script>
<script src="/static/xterm-addon-web-links.min.js"></script>
</head>
<body>
<div id="app"></div>
<script>
window.__CONFIG__ = {{
  apiUrl: "{api_url}",
  filesBase: "{files_base}",
  chatId: "{chat_id}"
}};
// Heartbeat: keep container alive while page is open (every 2 min)
setInterval(function() {{ fetch('/terminal/' + "{chat_id}" + '/heartbeat').catch(function(){{}}); }}, 120000);
</script>
<script type="module" src="/static/preview.js"></script>
</body>
</html>'''


@app.get("/system-prompt", response_class=PlainTextResponse, tags=["System"])
async def system_prompt(
    chat_id: Optional[str] = None,
    file_base_url: Optional[str] = None,
    archive_url: Optional[str] = None,
    user_email: Optional[str] = None,
):
    """
    Get Computer Use system prompt for AI integrations.

    Returns the system prompt template that teaches AI how to use the
    Computer Use virtual machine (tools, skills, file handling, etc.).

    When user_email is provided, returns a dynamic prompt with skills
    based on the user's settings (fetched from mcp-settings-wrapper).

    Args:
        chat_id: Recommended. Server constructs file URLs from this.
        file_base_url: Deprecated (legacy). Use chat_id instead.
        archive_url: Deprecated (legacy). Use chat_id instead.
        user_email: Optional. If provided, fetches user-specific skill settings.
    """
    if user_email:
        # Dynamic prompt based on user's enabled skills
        skills = await skill_manager.get_user_skills(user_email)

        # Cache user-uploaded skill ZIPs
        for s in skills:
            if s.category == "user":
                await skill_manager.ensure_skill_cached(s)

        skills_xml = skill_manager.build_available_skills_xml(skills)
        has_user_skills = any(s.category == "user" for s in skills)
        result = build_system_prompt(skills_xml=skills_xml, has_user_skills=has_user_skills)
    else:
        # Fallback: static template with hardcoded 10 public skills
        result = SYSTEM_PROMPT_TEMPLATE

    if chat_id:
        # New path: server constructs URLs from chat_id
        base = f"{FILE_SERVER_URL}/files/{chat_id}"
        result = result.replace("{file_base_url}", base)
        result = result.replace("{archive_url}", f"{base}/archive")
        result = result.replace("{chat_id}", chat_id)
    elif file_base_url is not None:
        # Legacy path: external integrations (n8n etc.) pass full URLs
        result = result.replace("{file_base_url}", file_base_url)
        legacy_chat_id = file_base_url.rstrip("/").rsplit("/", 1)[-1]
        result = result.replace("{chat_id}", legacy_chat_id)
        if archive_url is not None:
            result = result.replace("{archive_url}", archive_url)
    return result


@app.get("/skill-mounts", tags=["System"])
async def skill_mounts_endpoint(user_email: Optional[str] = None):
    """
    Get Docker volume mounts for user-uploaded skills.

    Returns dict of {host_path: {"bind": container_path, "mode": "ro"}}
    for use by computer_use_tools.py when creating containers.
    """
    if not user_email:
        return {}
    skills = await skill_manager.get_user_skills(user_email)
    for s in skills:
        if s.category == "user":
            await skill_manager.ensure_skill_cached(s)
    return skill_manager.get_skill_mounts(skills)


@app.get("/skill-list", response_class=PlainTextResponse, tags=["System"])
async def skill_list_endpoint(
    user_email: Optional[str] = None,
    format: str = "sub_agent",
):
    """
    Get skills list as text for sub-agent prompt.

    Returns formatted text: "- name: location - description" per line.
    """
    skills = await skill_manager.get_user_skills(user_email)
    if format == "sub_agent":
        return skill_manager.build_sub_agent_skills_text(skills)
    return skill_manager.build_sub_agent_skills_text(skills)


@app.get("/health", tags=["System"])
async def health():
    """Health check for monitoring"""
    return {"status": "healthy"}


# ============================================================================
# Skill Usage Stats
# ============================================================================

CENTRAL_LOG = BASE_DATA_DIR / "skill-usage-central.jsonl"
_central_log_lock = asyncio.Lock()


def _harvest_and_get_stats() -> dict:
    """
    Scan per-chat .skill-usage.jsonl files, append new events to central log,
    then aggregate stats from the central log.
    """
    seen: set = set()

    # Load already-seen events from central log (dedup key: ts+chat_id+skill)
    if CENTRAL_LOG.exists():
        with open(CENTRAL_LOG) as f:
            for line in f:
                try:
                    ev = json.loads(line)
                    seen.add((ev["ts"], ev.get("chat_id", ""), ev.get("skill", "")))
                except Exception:
                    pass

    # Harvest new events from per-chat logs
    new_events: list = []
    for log_path in BASE_DATA_DIR.glob("*/outputs/.skill-usage.jsonl"):
        try:
            with open(log_path) as f:
                for line in f:
                    try:
                        ev = json.loads(line.strip())
                        key = (ev["ts"], ev.get("chat_id", ""), ev.get("skill", ""))
                        if key not in seen:
                            seen.add(key)
                            new_events.append(ev)
                    except Exception:
                        pass
        except OSError:
            pass

    # Persist new events to central log
    if new_events:
        with open(CENTRAL_LOG, "a") as f:
            for ev in new_events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # Aggregate stats from central log
    stats: dict = {}
    if CENTRAL_LOG.exists():
        with open(CENTRAL_LOG) as f:
            for line in f:
                try:
                    ev = json.loads(line)
                    skill = ev.get("skill", "unknown")
                    email = ev.get("email", "unknown")
                    s = stats.setdefault(skill, {"total": 0, "by_email": {}})
                    s["total"] += 1
                    s["by_email"][email] = s["by_email"].get(email, 0) + 1
                except Exception:
                    pass

    return {
        "skills": stats,
        "total_events": sum(s["total"] for s in stats.values()),
        "harvested_new": len(new_events),
    }


@app.get("/api/skill-stats", tags=["System"])
async def skill_stats(x_internal_api_key: Optional[str] = Header(default=None)):
    """
    Aggregate skill usage stats from all chat containers.

    Scans per-chat .skill-usage.jsonl files written by the inotify watcher
    running inside containers, persists new events to a central durable log,
    and returns aggregated counts per skill and user email.

    Requires X-Internal-Api-Key header (matches MCP_TOKENS_API_KEY env var).
    """
    api_key = os.getenv("MCP_TOKENS_API_KEY", "")
    if api_key and x_internal_api_key != api_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    async with _central_log_lock:
        result = await asyncio.get_event_loop().run_in_executor(None, _harvest_and_get_stats)
    return result


# ============================================================================
# MCP Endpoint Integration
# ============================================================================

# MCP requires initialization via lifespan context manager
# We'll use a custom SSE-based approach for better compatibility

_mcp_server = None
_mcp_set_context = None


def _init_mcp():
    """Initialize MCP server (lazy load)."""
    global _mcp_server, _mcp_set_context
    if _mcp_server is None:
        try:
            from mcp_tools import mcp, set_context_from_headers
            _mcp_server = mcp
            _mcp_set_context = set_context_from_headers
            print("[MCP] MCP server initialized")
        except ImportError as e:
            print(f"[MCP] Warning: MCP tools not available: {e}")
    return _mcp_server, _mcp_set_context


# =============================================================================
# Mount native MCP Streamable HTTP app (SSE + progress notifications)
# =============================================================================
# Replaces the old custom JSON-RPC handler with FastMCP's native Starlette app.
# This enables:
# - SSE streaming for real-time progress updates via ctx.report_progress()
# - Standard MCP protocol compliance (initialize, tools/list, tools/call)
# - Session management by FastMCP
#
# Example usage with MCP client:
#   from mcp import ClientSession
#   from mcp.client.streamable_http import streamablehttp_client
#
#   async with streamablehttp_client(
#       "http://localhost:8081/mcp",
#       headers={"X-Chat-Id": "my-chat-123"}
#   ) as (read, write, _):
#       async with ClientSession(read, write) as session:
#           await session.initialize()
#           tools = await session.list_tools()
#           result = await session.call_tool("bash_tool", {
#               "command": "echo hello",
#               "description": "Test command"
#           })

try:
    from mcp_tools import get_mcp_app
    _mcp_asgi_app = get_mcp_app(api_key=MCP_API_KEY)

    # Add MCP Starlette route directly to FastAPI router (avoids trailing slash issues)
    from starlette.routing import Route

    async def _mcp_endpoint(request):
        """Forward to MCP ASGI app."""
        # Rewrite path to "/" (root of MCP app)
        scope = dict(request.scope)
        scope["path"] = "/"
        scope["raw_path"] = b"/"
        await _mcp_asgi_app(scope, request.receive, request._send)

    app.routes.insert(0, Route("/mcp", endpoint=_mcp_endpoint, methods=["POST", "GET", "DELETE"]))
    print("[MCP] Native Streamable HTTP MCP app route added at /mcp")
except ImportError as e:
    print(f"[MCP] Warning: MCP tools not available: {e}")


@app.get("/mcp-info", tags=["MCP"], response_model=MCPInfo)
async def mcp_info(_auth: str = Depends(verify_mcp_auth)):
    """Get MCP endpoint information (for documentation/debugging)."""
    mcp_server, _ = _init_mcp()

    if mcp_server is None:
        raise HTTPException(
            status_code=503,
            detail="MCP endpoint not available"
        )

    tools = []
    for tool in mcp_server._tool_manager.list_tools():
        tools.append(MCPToolInfo(
            name=tool.name,
            description=tool.description.strip() if tool.description else ""
        ))

    return MCPInfo(
        name="computer-use-mcp",
        version="1.0.0",
        description="Computer Use tools via MCP - command execution in isolated Docker containers",
        tools=tools,
        headers={
            "required": ["X-Chat-Id"],
            "optional": [
                "X-User-Email",
                "X-User-Name",
                "X-Gitlab-Token",
                "X-Gitlab-Host",
                "X-Anthropic-Api-Key",
                "X-Anthropic-Base-Url"
            ]
        }
    )
