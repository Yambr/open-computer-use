# Third-party dependencies & licensing

This project's source code is BUSL-1.1 (see [`LICENSE`](LICENSE)). The Docker image built from this repo bundles third-party software under various licenses, including but not limited to:

| Component | License | Notes |
| --- | --- | --- |
| PyMuPDF (`fitz`) | AGPL-3.0 OR Artifex Commercial | Bundled as a Python dep. If you build this image and host it as a public network service, AGPL-3.0 conveyance obligations may apply to **you** — including source-code disclosure. The maintainers of this repository do not host or distribute compiled images publicly and grant no sublicense to PyMuPDF. |
| extract-text | Anthropic Skill License (proprietary) | See [`vendor/extract-text/README.md`](vendor/extract-text/README.md) and [`skills/README.md`](skills/README.md). |
| Anthropic-authored skills (`docx`, `pdf`, `pptx`, `xlsx`, `file-reading`, `pdf-reading`) | Anthropic Skill License (proprietary) | See [`skills/README.md`](skills/README.md) for the full disclaimer and removal instructions. |
| GSD bundle ([`gsd-build/get-shit-done`](https://github.com/gsd-build/get-shit-done)) | Apache 2.0 (upstream) | Cloned at build time from upstream tag. |
| Superpowers bundle ([`obra/superpowers`](https://github.com/obra/superpowers)) | Apache 2.0 (upstream) | Cloned at build time from upstream tag. |
| Open WebUI base | BSD-3-Clause-with-additional-license-condition | Upstream; see [Open WebUI](https://github.com/open-webui/open-webui). |

**No warranties.** Source is provided "as is". Compliance with downstream licenses (AGPL conveyance, Anthropic Skill License, etc.) when you build, host, or redistribute the image is **your responsibility**. The repository maintainers do not act as a license clearinghouse and do not grant sublicenses to third-party components.
