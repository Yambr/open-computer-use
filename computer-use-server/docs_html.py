"""Root documentation page HTML — loaded from static/docs.html."""

import os

_HTML_PATH = os.path.join(os.path.dirname(__file__), "static", "docs.html")

def get_root_html() -> str:
    """Load root docs HTML from file."""
    with open(_HTML_PATH, "r", encoding="utf-8") as f:
        return f.read()
