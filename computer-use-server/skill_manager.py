"""
Skill Manager for docker-ai.

Fetches user-enabled skills from mcp-settings-wrapper, caches ZIP files,
generates <available_skills> XML for system prompt, and builds Docker mounts.
"""
import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_TOKENS_URL = os.getenv("MCP_TOKENS_URL", "")
MCP_TOKENS_API_KEY = os.getenv("MCP_TOKENS_API_KEY", "")
SKILLS_CACHE_DIR = Path(os.getenv("SKILLS_CACHE_DIR", "/data/skills-cache"))
# Host path for Docker volume mounts (computer-use-orchestrator sees /data/skills-cache,
# but Docker daemon needs the real host path for mounting into user containers)
SKILLS_CACHE_HOST_PATH = Path(os.getenv("SKILLS_CACHE_HOST_PATH", "/tmp/skills-cache"))
MANIFEST_PATH = SKILLS_CACHE_DIR / ".manifest.json"
USER_CONFIGS_DIR = SKILLS_CACHE_DIR / "_user_configs"

# Cache TTLs
MEMORY_CACHE_TTL = 60       # seconds — in-memory cache for user skill lists
API_TIMEOUT = 5             # seconds — HTTP timeout for API calls
ZIP_DOWNLOAD_TIMEOUT = 30   # seconds — HTTP timeout for ZIP download
MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50 MB — max ZIP download size

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SkillInfo:
    name: str
    description: str
    category: str           # "public", "example", "user"
    skill_path: Optional[str] = None   # e.g. "public/pdf" for native
    zip_sha256: Optional[str] = None   # for user-uploaded skills
    host_path: Optional[str] = None    # resolved host path for Docker mount

    @property
    def location(self) -> str:
        """Path inside the container."""
        if self.category == "user":
            return f"/mnt/skills/user/{self.name}/SKILL.md"
        elif self.skill_path:
            return f"/mnt/skills/{self.skill_path}/SKILL.md"
        else:
            return f"/mnt/skills/public/{self.name}/SKILL.md"


# ---------------------------------------------------------------------------
# English descriptions for native skills (for system prompt)
# Taken from the current hardcoded system_prompt.py block.
# ---------------------------------------------------------------------------

NATIVE_PROMPT_DESCRIPTIONS: dict[str, str] = {
    "docx": (
        "Comprehensive document creation, editing, and analysis with support for "
        "tracked changes, comments, formatting preservation, and text extraction. "
        "When You needs to work with professional documents (.docx files) for: "
        "(1) Creating new documents, (2) Modifying or editing content, "
        "(3) Working with tracked changes, (4) Adding comments, or any other document tasks"
    ),
    "pdf": (
        "Comprehensive PDF manipulation toolkit for extracting text and tables, "
        "creating new PDFs, merging/splitting documents, and handling forms. "
        "When You needs to fill in a PDF form or programmatically process, generate, "
        "or analyze PDF documents at scale."
    ),
    "pdf-markdown": (
        "Convert PDF to Markdown with images via MinerU OCR API. "
        "Use when markdown output with preserved images is needed. "
        "Supports Russian (default) and other languages."
    ),
    "pptx": (
        "Presentation creation, editing, and analysis. When You needs to work with "
        "presentations (.pptx files) for: (1) Creating new presentations, "
        "(2) Modifying or editing content, (3) Working with layouts, "
        "(4) Adding comments or speaker notes, or any other presentation tasks"
    ),
    "xlsx": (
        "Comprehensive spreadsheet creation, editing, and analysis with support for "
        "formulas, formatting, data analysis, and visualization. When You needs to "
        "work with spreadsheets (.xlsx, .xlsm, .csv, .tsv, etc) for: "
        "(1) Creating new spreadsheets with formulas and formatting, "
        "(2) Reading or analyzing data, (3) Modify existing spreadsheets while "
        "preserving formulas, (4) Data analysis and visualization in spreadsheets, "
        "or (5) Recalculating formulas"
    ),
    "skill-creator": (
        "Guide for creating effective skills. This skill should be used when users "
        "want to create a new skill (or update an existing skill) that extends You's "
        "capabilities with specialized knowledge, workflows, or tool integrations."
    ),
    "product-self-knowledge": (
        "Reference guide for Open Computer Use AI products. Use when users ask about "
        "models, model selection, personal data (PD), integrations (Confluence, "
        "Jira, Kontur), budget, or AI portal settings."
    ),
    "settings-manager": (
        "Manage AI assistant settings: check MCP token status (Confluence, Jira, "
        "GitLab), view and toggle skills, get recommendations. Use when user asks "
        "about settings, capabilities, skills, tokens, or when a tool call fails "
        "with a missing token error."
    ),
    "gitlab-explorer": (
        "Explore GitLab repositories using glab CLI and git commands. Use when user "
        "asks to: clone repositories, search projects or code in GitLab, view merge "
        "requests, explore project structure, check CI/CD pipelines, work with "
        "issues, or analyze git history. IMPORTANT: Always run authentication check "
        "script first before any GitLab operation."
    ),
    "sub-agent": (
        "Delegate complex tasks to autonomous sub-agent. Use for: creating "
        "presentations, multi-file refactoring, code review, Git operations, "
        "research, documentation. The sub-agent can iterate on tasks until "
        "completion and works in an isolated environment with full tool access."
    ),
    "describe-image": (
        "Describe images (charts, diagrams, tables, screenshots) using Vision AI. "
        "Use as fallback when you cannot read an image file directly."
    ),
    "playwright-cli": (
        "Automates browser interactions for web testing, form filling, screenshots, "
        "and data extraction. Use when the user needs to navigate websites, interact "
        "with web pages, fill forms, take screenshots, test web applications, "
        "or extract information from web pages."
    ),
    # Example skills
    "algorithmic-art": (
        "Create algorithmic art with p5.js using generative randomness and "
        "interactive parameter tuning. Generative art, flow fields, particle systems."
    ),
    "artifacts-builder": (
        "Toolkit for building complex multi-component HTML artifacts using modern "
        "frontend technologies (React, Tailwind CSS, shadcn/ui)."
    ),
    "brand-guidelines": (
        "Apply official brand colors and typography to artifacts. Use when brand "
        "colors, style guidelines, visual design, or corporate standards are needed."
    ),
    "canvas-design": (
        "Create beautiful visual works in .png and .pdf formats using design "
        "philosophy. For posters, illustrations, design, and other static visuals."
    ),
    "internal-comms": (
        "Resources for writing internal communications: status reports, leadership "
        "updates, newsletters, FAQs, incident reports, project updates."
    ),
    "mcp-builder": (
        "Guide for building MCP servers (Model Context Protocol) that let LLMs "
        "interact with external services. Python (FastMCP) or Node/TypeScript (MCP SDK)."
    ),
    "single-cell-rna-qc": (
        "Quality control for single-cell RNA-seq data (.h5ad or .h5 files) "
        "following scverse best practices with MAD filtering and result visualization."
    ),
    "slack-gif-creator": (
        "Tools for creating animated GIFs optimized for Slack. "
        "Size constraints, validation, and animation concepts."
    ),
    "theme-factory": (
        "Toolkit for styling artifacts. 10 ready-made themes with colors and "
        "fonts for slides, documents, reports, HTML landing pages. "
        "Can generate new themes on the fly."
    ),
    "frontend-design": (
        "Create distinctive, production-grade frontend interfaces with high design quality. "
        "Use when building web components, pages, dashboards, React components, HTML/CSS layouts, "
        "or styling/beautifying any web UI. Avoids generic AI aesthetics."
    ),
    "doc-coauthoring": (
        "Structured 3-stage workflow for co-authoring documents: context gathering, "
        "section-by-section refinement with brainstorming, and reader testing via sub-agent. "
        "Use for specs, PRDs, RFCs, proposals, technical documentation."
    ),
    "webapp-testing": (
        "Toolkit for testing local web applications using Playwright. "
        "Verify frontend functionality, debug UI, capture screenshots, view browser logs. "
        "Includes helper scripts for server lifecycle management."
    ),
    "test-driven-development": (
        "TDD workflow: write test first, watch it fail, write minimal code to pass. "
        "Use for any feature or bugfix. Enforces discipline — no production code "
        "without a failing test first."
    ),
    "writing-skills": (
        "TDD-based methodology for writing Claude Code skills. "
        "Test with sub-agents, find gaps, refine. Meta-skill for skill creation."
    ),
    "copy-editing": (
        "Seven-sweep copy editing framework: clarity, flow, power, proof, voice, "
        "conversion, consistency. Systematic improvement of marketing and business copy."
    ),
    "social-content": (
        "Social media content creation for LinkedIn, Twitter/X, Instagram. "
        "Content calendars, repurposing, engagement optimization."
    ),
    "product-marketing-context": (
        "Create product marketing context document: positioning, ICP, messaging, "
        "brand voice. Foundation for other marketing skills."
    ),
}

# Default public skills (fallback when API is unavailable)
DEFAULT_PUBLIC_SKILLS = [
    "docx", "pdf", "pdf-markdown", "pptx", "xlsx",
    "skill-creator", "product-self-knowledge", "settings-manager", "gitlab-explorer",
    "sub-agent", "describe-image", "playwright-cli",
    "frontend-design", "doc-coauthoring", "webapp-testing",
    "test-driven-development",
]

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_memory_cache: dict[str, tuple[float, list[SkillInfo]]] = {}
_email_locks: dict[str, asyncio.Lock] = {}


def _get_lock(email: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for the given email."""
    if email not in _email_locks:
        _email_locks[email] = asyncio.Lock()
    return _email_locks[email]


# ---------------------------------------------------------------------------
# Disk cache helpers
# ---------------------------------------------------------------------------

def _read_manifest() -> dict:
    """Read skills cache manifest from disk."""
    try:
        if MANIFEST_PATH.exists():
            return json.loads(MANIFEST_PATH.read_text())
    except Exception as e:
        logger.warning(f"[SKILLS] Failed to read manifest: {e}")
    return {}


def _write_manifest(manifest: dict) -> None:
    """Write skills cache manifest to disk."""
    try:
        SKILLS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    except Exception as e:
        logger.warning(f"[SKILLS] Failed to write manifest: {e}")


def _save_user_config_cache(email: str, data: dict) -> None:
    """Save user config response to disk for fallback."""
    try:
        USER_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        email_hash = hashlib.md5(email.encode()).hexdigest()
        path = USER_CONFIGS_DIR / f"{email_hash}.json"
        path.write_text(json.dumps(data))
    except Exception as e:
        logger.warning(f"[SKILLS] Failed to save user config cache: {e}")


def _load_user_config_cache(email: str) -> Optional[dict]:
    """Load user config from disk cache."""
    try:
        email_hash = hashlib.md5(email.encode()).hexdigest()
        path = USER_CONFIGS_DIR / f"{email_hash}.json"
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        logger.warning(f"[SKILLS] Failed to load user config cache: {e}")
    return None


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

async def _fetch_user_config(email: str) -> Optional[dict]:
    """
    Fetch user's enabled skills from mcp-settings-wrapper.

    GET /api/internal/user-config/{email}
    Returns: {"email": "...", "enabled_skills": [...]}
    """
    if not MCP_TOKENS_API_KEY:
        logger.warning("[SKILLS] MCP_TOKENS_API_KEY not configured")
        return None

    url = f"{MCP_TOKENS_URL}/api/internal/user-config/{email}"
    headers = {"X-Internal-Api-Key": MCP_TOKENS_API_KEY}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    _save_user_config_cache(email, data)
                    return data
                else:
                    logger.warning(f"[SKILLS] API returned {resp.status} for {email}")
    except asyncio.TimeoutError:
        logger.warning(f"[SKILLS] Timeout fetching config for {email}")
    except Exception as e:
        logger.warning(f"[SKILLS] Error fetching config: {e}")

    return None


async def _download_skill_zip(name: str) -> Optional[bytes]:
    """
    Download skill ZIP from mcp-settings-wrapper.

    GET /api/internal/skills/{name}/download
    Returns ZIP bytes or None.
    """
    if not MCP_TOKENS_API_KEY:
        return None

    url = f"{MCP_TOKENS_URL}/api/internal/skills/{name}/download"
    headers = {"X-Internal-Api-Key": MCP_TOKENS_API_KEY}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=ZIP_DOWNLOAD_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"[SKILLS] Download {name}: HTTP {resp.status}")
                    return None

                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    # Native skill — already on filesystem
                    return None

                # Read ZIP with size limit
                data = bytearray()
                async for chunk in resp.content.iter_chunked(8192):
                    data.extend(chunk)
                    if len(data) > MAX_ZIP_SIZE:
                        logger.warning(f"[SKILLS] ZIP too large for {name}, aborting")
                        return None

                return bytes(data)
    except asyncio.TimeoutError:
        logger.warning(f"[SKILLS] Timeout downloading ZIP for {name}")
    except Exception as e:
        logger.warning(f"[SKILLS] Error downloading ZIP {name}: {e}")

    return None


# ---------------------------------------------------------------------------
# ZIP cache management
# ---------------------------------------------------------------------------

async def ensure_skill_cached(skill: SkillInfo) -> Optional[str]:
    """
    Ensure a user-uploaded skill is cached on disk.

    For native skills (public/example), returns None — they're in the Docker image.
    For user skills, downloads and extracts ZIP if needed.

    Returns the host cache path or None.
    """
    if skill.category != "user":
        return None

    cache_dir = SKILLS_CACHE_DIR / skill.name
    manifest = _read_manifest()

    # Check if already cached with matching SHA256
    cached = manifest.get(skill.name, {})
    if (
        cached.get("sha256") == skill.zip_sha256
        and cache_dir.exists()
        and (cache_dir / "SKILL.md").exists()
    ):
        skill.host_path = str(cache_dir)
        return str(cache_dir)

    # Download ZIP
    logger.info(f"[SKILLS] Downloading ZIP for {skill.name} (sha256={skill.zip_sha256})")
    zip_data = await _download_skill_zip(skill.name)
    if not zip_data:
        # If we have old cache, use it
        if cache_dir.exists() and (cache_dir / "SKILL.md").exists():
            logger.info(f"[SKILLS] Using stale cache for {skill.name}")
            skill.host_path = str(cache_dir)
            return str(cache_dir)
        return None

    # Extract atomically: unzip to temp dir, then rename
    try:
        SKILLS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(dir=SKILLS_CACHE_DIR, prefix=f".{skill.name}-")

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            # Detect if ZIP has a top-level directory wrapper
            names = zf.namelist()
            prefix = ""
            if names and all(n.startswith(names[0].split("/")[0] + "/") for n in names if n):
                prefix = names[0].split("/")[0] + "/"

            for member in zf.infolist():
                if member.is_dir():
                    continue
                # Strip prefix if present
                rel_path = member.filename
                if prefix and rel_path.startswith(prefix):
                    rel_path = rel_path[len(prefix):]
                if not rel_path:
                    continue

                target = os.path.join(tmp_dir, rel_path)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(zf.read(member.filename))

        # Make files world-readable (container user is non-root)
        os.chmod(tmp_dir, 0o755)
        for root, dirs, files in os.walk(tmp_dir):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o755)
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)

        # Replace contents in-place (preserve directory inode for bind mounts)
        if cache_dir.exists():
            for item in os.listdir(str(cache_dir)):
                item_path = os.path.join(str(cache_dir), item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
            for item in os.listdir(tmp_dir):
                shutil.move(os.path.join(tmp_dir, item), os.path.join(str(cache_dir), item))
            shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            os.rename(tmp_dir, str(cache_dir))

        # Update manifest
        manifest[skill.name] = {
            "sha256": skill.zip_sha256,
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write_manifest(manifest)

        skill.host_path = str(cache_dir)
        logger.info(f"[SKILLS] Cached {skill.name} at {cache_dir}")
        return str(cache_dir)

    except Exception as e:
        logger.error(f"[SKILLS] Error extracting ZIP for {skill.name}: {e}")
        # Cleanup temp dir
        if 'tmp_dir' in locals() and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def _build_default_skills() -> list[SkillInfo]:
    """Build default public skills list (fallback)."""
    return [
        SkillInfo(
            name=name,
            description=NATIVE_PROMPT_DESCRIPTIONS.get(name, ""),
            category="public",
            skill_path=f"public/{name}",
        )
        for name in DEFAULT_PUBLIC_SKILLS
    ]


def _parse_api_skills(enabled_skills: list[dict]) -> list[SkillInfo]:
    """Parse API response into SkillInfo list, ensuring default public skills are always present."""
    result = []
    seen_names = set()
    for s in enabled_skills:
        result.append(SkillInfo(
            name=s["name"],
            description=s.get("description", ""),
            category=s.get("category", "user"),
            skill_path=s.get("skill_path"),
            zip_sha256=s.get("zip_sha256"),
        ))
        seen_names.add(s["name"])

    # Ensure default public skills are always included
    for name in DEFAULT_PUBLIC_SKILLS:
        if name not in seen_names:
            result.append(SkillInfo(
                name=name,
                description=NATIVE_PROMPT_DESCRIPTIONS.get(name, ""),
                category="public",
                skill_path=f"public/{name}",
            ))

    return result


async def get_user_skills(email: Optional[str]) -> list[SkillInfo]:
    """
    Get enabled skills for a user.

    3-level fallback: in-memory cache → disk cache → hardcoded defaults.
    """
    if not email:
        return _build_default_skills()

    # 1. In-memory cache
    now = time.time()
    cached = _memory_cache.get(email)
    if cached and (now - cached[0]) < MEMORY_CACHE_TTL:
        return cached[1]

    # Serialize per-email to avoid duplicate API calls
    lock = _get_lock(email)
    async with lock:
        # Double-check after acquiring lock
        cached = _memory_cache.get(email)
        if cached and (now - cached[0]) < MEMORY_CACHE_TTL:
            return cached[1]

        # 2. API call
        data = await _fetch_user_config(email)
        if data and "enabled_skills" in data:
            skills = _parse_api_skills(data["enabled_skills"])
            _memory_cache[email] = (time.time(), skills)
            return skills

        # 3. Disk cache fallback
        disk_data = _load_user_config_cache(email)
        if disk_data and "enabled_skills" in disk_data:
            logger.info(f"[SKILLS] Using disk cache for {email}")
            skills = _parse_api_skills(disk_data["enabled_skills"])
            _memory_cache[email] = (time.time(), skills)
            return skills

        # 4. Hardcoded defaults
        logger.warning(f"[SKILLS] Using default skills for {email}")
        skills = _build_default_skills()
        _memory_cache[email] = (time.time(), skills)
        return skills


def get_user_skills_sync(email: Optional[str]) -> list[SkillInfo]:
    """
    Synchronous version — reads only from cache, no API calls.

    Used by _create_container() which runs in asyncio.to_thread.
    """
    if not email:
        return _build_default_skills()

    # In-memory cache
    cached = _memory_cache.get(email)
    if cached:
        return cached[1]

    # Disk cache
    disk_data = _load_user_config_cache(email)
    if disk_data and "enabled_skills" in disk_data:
        return _parse_api_skills(disk_data["enabled_skills"])

    return _build_default_skills()


# ---------------------------------------------------------------------------
# XML generation for system prompt
# ---------------------------------------------------------------------------

MAX_DESCRIPTION_LEN = 300


def _get_skill_description(skill: SkillInfo) -> str:
    """Get English description for system prompt (native skills use hardcoded)."""
    desc = NATIVE_PROMPT_DESCRIPTIONS.get(skill.name)
    if desc:
        return desc
    # User-uploaded: use description from API, truncate if needed
    desc = skill.description
    if len(desc) > MAX_DESCRIPTION_LEN:
        desc = desc[:MAX_DESCRIPTION_LEN - 3] + "..."
    return desc


def build_available_skills_xml(skills: list[SkillInfo]) -> str:
    """
    Generate <available_skills> XML block for system prompt.

    Format matches the existing hardcoded block in system_prompt.py.
    """
    lines = ["<available_skills>"]
    for skill in skills:
        desc = _get_skill_description(skill)
        lines.append("<skill>")
        lines.append(f"<name>\n{skill.name}\n</name>")
        lines.append(f"<description>\n{desc}\n</description>")
        lines.append(f"<location>\n{skill.location}\n</location>")
        lines.append("</skill>")
        lines.append("")
    lines.append("</available_skills>")
    return "\n".join(lines)


def build_sub_agent_skills_text(skills: list[SkillInfo]) -> str:
    """
    Build skills list text for sub-agent system prompt.

    Format: "- skill-name: location - Short description"
    """
    lines = []
    for skill in skills:
        desc = _get_skill_description(skill)
        # Truncate for sub-agent (shorter)
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(f"- {skill.name}: {skill.location} - {desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Docker mounts for user skills
# ---------------------------------------------------------------------------

def get_skill_mounts(skills: list[SkillInfo]) -> dict:
    """
    Build Docker volume mounts for user-uploaded skills.

    Uses SKILLS_CACHE_HOST_PATH (not SKILLS_CACHE_DIR) because Docker daemon
    runs on the host and needs host paths, while computer-use-orchestrator sees /data/skills-cache.

    Returns dict compatible with docker-py volumes parameter:
    {host_path: {"bind": container_path, "mode": "ro"}}
    """
    mounts = {}
    for skill in skills:
        if skill.category != "user":
            continue

        # Verify the skill is actually cached (check via container path)
        cache_dir = SKILLS_CACHE_DIR / skill.name
        if not (cache_dir.exists() and (cache_dir / "SKILL.md").exists()):
            continue

        # Use HOST path for Docker volume source
        host_path = str(SKILLS_CACHE_HOST_PATH / skill.name)
        container_path = f"/mnt/skills/user/{skill.name}"
        mounts[host_path] = {"bind": container_path, "mode": "ro"}

    return mounts
