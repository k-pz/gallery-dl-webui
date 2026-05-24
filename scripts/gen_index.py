"""Render the docs-site landing page from the top-level README.

Invoked by `mkdocs-gen-files` at build time. Reads `README.md` from the repo
root, strips its leading H1 (MkDocs Material already shows the page title),
and rewrites links so the README's GitHub-relative paths resolve correctly
on the rendered docs site:

  [text](docs/foo.md)       → [text](foo.md)           (sibling MkDocs page)
  [text](some/other/path)   → absolute GitHub blob URL (file outside docs/)

Leaves absolute URLs and same-page anchors alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import mkdocs_gen_files

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB_BLOB = "https://github.com/k-pz/gallery-dl-webui/blob/main"

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _rewrite_link(match: re.Match[str]) -> str:
    text, target = match.group(1), match.group(2)
    if "://" in target or target.startswith(("#", "mailto:")):
        return match.group(0)
    if target.startswith("docs/"):
        return f"[{text}]({target.removeprefix('docs/')})"
    return f"[{text}]({GITHUB_BLOB}/{target.lstrip('/')})"


body = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
lines = body.splitlines()
if lines and lines[0].startswith("# "):
    lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
body = _LINK_RE.sub(_rewrite_link, "\n".join(lines))

with mkdocs_gen_files.open("index.md", "w") as fp:
    fp.write("# gallery-dl-webui\n\n")
    fp.write(body)
    if not body.endswith("\n"):
        fp.write("\n")
