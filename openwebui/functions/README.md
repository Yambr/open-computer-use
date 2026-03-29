# OpenWebUI Functions

Collection of Functions for integrating AI Computer Use with OpenWebUI.

## Computer Link Filter

**File**: `computer_link_filter.py`

### Description

A Filter function that:
1. ✅ Injects a system prompt with the file URL (AI immediately generates correct links)
2. ✅ Adds a "Download all as archive" button under messages with files

### How It Works (v3.0.0)

```
inlet() → Injects file_base_url and archive_url into the prompt
          ↓
AI      → Immediately generates correct HTTP links
          ↓
outlet() → Adds "Download archive" button
          ↓
User    → Clicks → File Server → Downloads file
```

**Key difference in v3.0.0**: AI receives the file server URL in the system prompt and immediately generates working links. No post-processing needed to replace `computer://`.

### Installation

1. Open OpenWebUI → **Workspace** → **Functions**
2. Click **"+ Add Function"**
3. Copy the contents of `computer_link_filter.py`
4. Paste into the editor and save
5. Enable the function globally or for specific models

### Settings (Valves)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `FILE_SERVER_URL` | `http://localhost:8081` | File server address |
| `ENABLE_ARCHIVE_BUTTON` | `true` | Add archive button |
| `ARCHIVE_BUTTON_TEXT` | `📦 Download all files as archive` | Button text |
| `INJECT_SYSTEM_PROMPT` | `true` | Inject system prompt |

### Example Output

#### AI generates directly:

```
Your report is ready!

[Download report.docx](http://localhost:8081/files/abc123/report.docx)
[Download presentation.pptx](http://localhost:8081/files/abc123/presentation.pptx)
```

#### After outlet() (button added):

```
Your report is ready!

[Download report.docx](http://localhost:8081/files/abc123/report.docx)
[Download presentation.pptx](http://localhost:8081/files/abc123/presentation.pptx)

---
[📦 Download all files as archive](http://localhost:8081/files/abc123/archive)
```

### What Gets Injected into the Prompt

AI receives the following information:
- `file_base_url`: URL for files (`{FILE_SERVER_URL}/files/{chat_id}/`)
- `archive_url`: URL for downloading the archive
- Mapping: `/mnt/user-data/outputs/` → `{file_base_url}/`
- Usage examples

### Requirements

- OpenWebUI >= 0.5.17
- File-server running and accessible
- Computer Use Tools configured with ID `ai_computer_use`

### Compatibility

Works with:
- ✅ Computer Use Tools v2.0.0+
- ✅ File Server v1.0.0+
- ✅ OpenWebUI 0.5.17+

---

## Additional Functions

*(more to be added later)*
