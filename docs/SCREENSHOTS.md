# Screenshots

Visual guide to Open Computer Use with Open WebUI.

## Live Browser Streaming

![Browser Viewer](screenshots/03-browser-viewer.png)

The AI opened openwebui.com via `playwright-cli` — you see the actual browser in real-time through CDP (Chrome DevTools Protocol) streaming. The chat on the left shows tool calls, the browser panel on the right shows the live page. You can watch the AI navigate, click, and fill forms.

## Claude Code Terminal

![Claude Code Terminal](screenshots/04-sub-agent-terminal.png)

Interactive Claude Code session inside the sandbox container. The AI is logged in and responding to prompts. This is a real TTY connection via WebSocket — you can type commands, interrupt execution, and resume sessions. Claude Code has access to all MCP servers and skills configured for the chat.

## File Preview

![File Preview](screenshots/02-file-preview.png)

The preview panel showing a generated Markdown file with skill descriptions. Files created by the AI appear here automatically — supports Word, Excel, PDF, images, code, and more. Dark theme, tabbed navigation (Files / Browser / Sub-agent).

## Sub-Agent Dashboard

![Sub-Agent Dashboard](screenshots/06-sub-agent-dashboard.png)

Claude Code monitoring panel: see running processes, previous sessions with resume capability, dangerous mode toggle. "Currently running: Claude Code" with a Stop button. Previous sessions show task descriptions with dates and Resume buttons.

## Document Creation

![Create Document](screenshots/01-create-document.png)

AI creating a Word document via tool calls. The model reads the SKILL.md, creates the file, and the preview panel auto-opens showing the document content inline.

## Chat Overview

![Chat Overview](screenshots/05-chat-overview.png)

Model listing its available skills and tools: docx, pdf, pptx, xlsx, bash_tool, create_file, str_replace, view, sub_agent, and more. Shows file handling paths and supported formats.
