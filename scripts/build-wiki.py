"""Generate the wiki markdown into an output directory.

Pages emitted:

  Home.md                ← README.md
  <Title>.md             ← docs/<slug>.md (one wiki page per file in docs/)
  HTTP-API.md            ← rendered from `create_app().openapi()`
  Python-<Domain>.md     ← `pydoc-markdown -p backend.<domain>` per domain
  _Sidebar.md            ← navigation index

The output directory is treated as a working copy of the `.wiki.git` repo:
files are overwritten in place, no clean is performed (the workflow runs
`git diff --quiet` to skip empty commits, and stale files are removed
explicitly via `git rm` below).

Usage: build-wiki.py <output-dir>
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.main import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_SRC = REPO_ROOT / "backend" / "src"
DOCS_DIR = REPO_ROOT / "docs"

# Per-domain grouping for the Python API reference. Order matches the sidebar.
# Each entry: (page slug without extension, sidebar title, list of packages).
DOMAINS: list[tuple[str, str, list[str]]] = [
    ("Python-Core", "Core (main, config, db)", [
        "backend.main",
        "backend.config",
        "backend.database",
        "backend.dependencies",
        "backend.exceptions",
    ]),
    ("Python-Downloads", "Downloads", ["backend.downloads"]),
    ("Python-Targets", "Targets", ["backend.targets"]),
    ("Python-Library", "Library", ["backend.library"]),
    ("Python-App-Config", "App config", ["backend.app_config"]),
    ("Python-Output-Dirs", "Output dirs", ["backend.output_dirs"]),
    ("Python-Health", "Health", ["backend.health"]),
]

# One wiki page per file in docs/, in sidebar order.
# Each entry: (source file under docs/, wiki page slug, sidebar title).
DOC_PAGES: list[tuple[str, str, str]] = [
    ("architecture.md", "Architecture", "Architecture"),
    ("backend.md", "Backend", "Backend"),
    ("pipeline.md", "Pipeline", "Download pipeline"),
    ("frontend.md", "Frontend", "Frontend"),
    ("lifecycles.md", "Lifecycles", "Lifecycles"),
    ("testing.md", "Testing", "Testing"),
    ("deployment.md", "Deployment", "Deployment"),
    ("decisions.md", "Decisions", "Design decisions"),
]

# Hand-rolled pages (Home from README, HTTP-API from OpenAPI).
TOP_PAGES: list[tuple[str, str]] = [
    ("Home", "Home"),
    ("HTTP-API", "HTTP API (OpenAPI)"),
]

# Map of repo-relative paths → wiki page slug, for link rewriting. Links in
# the source markdown are resolved relative to the source file's directory,
# then looked up here. Anchors (#section) are preserved by the rewriter.
DOC_LINK_MAP: dict[str, str] = {f"docs/{src}": slug for src, slug, _ in DOC_PAGES}
DOC_LINK_MAP["README.md"] = "Home"

# Files we manage. Anything else in the wiki directory is left alone.
MANAGED_FILES = (
    [f"{slug}.md" for slug, _ in TOP_PAGES]
    + [f"{slug}.md" for _, slug, _ in DOC_PAGES]
    + [f"{slug}.md" for slug, _, _ in DOMAINS]
    + ["_Sidebar.md", "_Footer.md", "api-spec.json"]
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path.relative_to(REPO_ROOT)}")


def _rewrite_doc_links(body: str, source: Path) -> str:
    """Rewrite inter-doc markdown links to wiki page slugs.

    Links in the source body are resolved relative to `source`'s directory,
    then looked up in `DOC_LINK_MAP`. So a `[Backend](backend.md)` link in
    `docs/architecture.md` becomes `[Backend](Backend)`, and a
    `[`docs/backend.md`](docs/backend.md)` link in `README.md` becomes
    `[`docs/backend.md`](Backend)`. Links to files not in the map (external
    URLs, code paths, etc.) are left alone.
    """
    source_dir = source.parent

    def repl(m: re.Match[str]) -> str:
        text, target = m.group(1), m.group(2)
        if "#" in target:
            path, anchor = target.split("#", 1)
            anchor = "#" + anchor
        else:
            path, anchor = target, ""
        if not path.endswith(".md"):
            return m.group(0)
        try:
            resolved = (source_dir / path).resolve()
            rel = resolved.relative_to(REPO_ROOT)
        except (OSError, ValueError):
            return m.group(0)
        key = str(rel).replace("\\", "/")
        slug = DOC_LINK_MAP.get(key)
        if slug is None:
            return m.group(0)
        return f"[{text}]({slug}{anchor})"

    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", repl, body)


def copy_top_level_doc(src: Path, dst: Path, *, title: str) -> None:
    body = src.read_text(encoding="utf-8")
    # Strip the leading H1 — wiki pages use the filename as the title and a
    # second H1 would render two stacked titles.
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    body = _rewrite_doc_links("\n".join(lines), src)
    write(dst, f"# {title}\n\n" + body)


def render_doc_pages(out_dir: Path) -> None:
    print("==> Topic docs (docs/*.md)")
    for src_name, slug, title in DOC_PAGES:
        src = DOCS_DIR / src_name
        if not src.is_file():
            raise FileNotFoundError(f"missing docs page: {src}")
        copy_top_level_doc(src, out_dir / f"{slug}.md", title=title)


def run_pydoc_markdown(packages: list[str]) -> str:
    cmd = ["pydoc-markdown", "-I", str(BACKEND_SRC)]
    for p in packages:
        cmd += ["-p", p]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def render_python_pages(out_dir: Path) -> None:
    print("==> Python API reference (pydoc-markdown)")
    for slug, title, packages in DOMAINS:
        body = run_pydoc_markdown(packages)
        page = (
            f"# {title}\n\n"
            f"Auto-generated from `{', '.join(packages)}`.\n\n"
            f"---\n\n"
            f"{body}"
        )
        write(out_dir / f"{slug}.md", page)


# ---------- OpenAPI → Markdown -------------------------------------------


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _resolve_ref(ref: str, spec: dict[str, Any]) -> dict[str, Any]:
    # Only handles "#/components/schemas/Foo" — sufficient for FastAPI output.
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        node = node[part]
    return node


def _schema_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return f"[`{name}`](#schema-{name.lower()})"
    if "anyOf" in schema:
        return " \\| ".join(_schema_type(s) for s in schema["anyOf"])
    if "oneOf" in schema:
        return " \\| ".join(_schema_type(s) for s in schema["oneOf"])
    if "allOf" in schema:
        return " & ".join(_schema_type(s) for s in schema["allOf"])
    t = schema.get("type", "any")
    if t == "array":
        return f"{_schema_type(schema.get('items', {}))}[]"
    fmt = schema.get("format")
    if fmt:
        return f"{t} ({fmt})"
    return t


def _render_param_table(parameters: list[dict[str, Any]]) -> str:
    if not parameters:
        return ""
    rows = ["| Name | In | Type | Required | Description |", "|---|---|---|---|---|"]
    for p in parameters:
        rows.append(
            "| `{name}` | {loc} | {type} | {req} | {desc} |".format(
                name=p["name"],
                loc=p.get("in", ""),
                type=_schema_type(p.get("schema", {})),
                req="yes" if p.get("required") else "no",
                desc=_md_escape(p.get("description", "")),
            )
        )
    return "\n".join(rows) + "\n"


def _render_responses(responses: dict[str, Any]) -> str:
    rows = ["| Status | Body | Description |", "|---|---|---|"]
    for code in sorted(responses):
        resp = responses[code]
        media = resp.get("content", {}).get("application/json", {})
        body = _schema_type(media.get("schema", {})) if media else "—"
        rows.append(
            "| `{code}` | {body} | {desc} |".format(
                code=code,
                body=body,
                desc=_md_escape(resp.get("description", "")),
            )
        )
    return "\n".join(rows) + "\n"


def _render_request_body(body: dict[str, Any] | None) -> str:
    if not body:
        return ""
    media = body.get("content", {}).get("application/json", {})
    if not media:
        return ""
    schema = media.get("schema", {})
    required = " (required)" if body.get("required") else ""
    return f"\n**Request body**{required}: {_schema_type(schema)}\n"


def _render_operation(method: str, path: str, op: dict[str, Any]) -> str:
    title = op.get("summary") or op.get("operationId") or f"{method.upper()} {path}"
    parts = [
        f"#### `{method.upper()} {path}`",
        "",
        f"_{title}_" if op.get("summary") else "",
    ]
    if op.get("description"):
        parts += ["", op["description"]]
    if op.get("parameters"):
        parts += ["", "**Parameters**", "", _render_param_table(op["parameters"])]
    rb = _render_request_body(op.get("requestBody"))
    if rb:
        parts += [rb]
    parts += ["", "**Responses**", "", _render_responses(op.get("responses", {}))]
    return "\n".join(p for p in parts if p is not None) + "\n"


def _render_schema(name: str, schema: dict[str, Any]) -> str:
    parts = [f'### <a id="schema-{name.lower()}"></a>`{name}`', ""]
    if schema.get("description"):
        parts += [schema["description"], ""]
    if schema.get("enum"):
        values = ", ".join(f"`{v}`" for v in schema["enum"])
        parts += [f"**Enum:** {values}", ""]
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    if props:
        rows = ["| Property | Type | Required | Description |", "|---|---|---|---|"]
        for pname, pschema in props.items():
            rows.append(
                "| `{name}` | {type} | {req} | {desc} |".format(
                    name=pname,
                    type=_schema_type(pschema),
                    req="yes" if pname in required else "no",
                    desc=_md_escape(pschema.get("description", "")),
                )
            )
        parts += ["\n".join(rows), ""]
    return "\n".join(parts) + "\n"


def render_http_api(out_dir: Path) -> None:
    print("==> HTTP API (OpenAPI → markdown)")
    app = create_app(serve_frontend=False)
    spec = app.openapi()

    # Side-channel: keep the raw spec next to the page so a wiki reader can
    # still import it into Postman / Insomnia / Swagger Editor.
    write(out_dir / "api-spec.json", json.dumps(spec, indent=2, sort_keys=True))

    paths = spec.get("paths", {})
    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, methods in sorted(paths.items()):
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            tag = (op.get("tags") or ["misc"])[0]
            by_tag.setdefault(tag, []).append((method, path, op))

    out = [
        "# HTTP API",
        "",
        f"Generated from the live FastAPI app — **OpenAPI {spec.get('openapi', '?')}**, "
        f"`{spec.get('info', {}).get('title', '')}` "
        f"v{spec.get('info', {}).get('version', '0.0.0')}.",
        "",
        f"Raw spec: [`api-spec.json`](api-spec.json) (commit it to your API "
        f"client of choice).",
        "",
    ]

    out += ["## Endpoints", ""]
    for tag in sorted(by_tag):
        out += [f"### {tag}", ""]
        for method, path, op in by_tag[tag]:
            out += [_render_operation(method, path, op)]

    schemas = (spec.get("components") or {}).get("schemas") or {}
    if schemas:
        out += ["## Schemas", ""]
        for name in sorted(schemas):
            out += [_render_schema(name, schemas[name])]

    write(out_dir / "HTTP-API.md", "\n".join(out))


# ---------- Sidebar -------------------------------------------------------


def render_sidebar(out_dir: Path) -> None:
    print("==> Sidebar")
    lines = ["# Contents", "", "- [Home](Home)"]
    lines += ["", "## Architecture & internals", ""]
    for _, slug, title in DOC_PAGES:
        lines.append(f"- [{title}]({slug})")
    lines += ["", "## API reference", "", "- [HTTP API (OpenAPI)](HTTP-API)"]
    lines += ["", "### Python", ""]
    for slug, title, _ in DOMAINS:
        lines.append(f"- [{title}]({slug})")
    write(out_dir / "_Sidebar.md", "\n".join(lines))

    footer = (
        "_Auto-generated from "
        f"[`{REPO_ROOT.name}@main`](https://github.com/k-pz/gallery-dl-webui) by "
        "[`scripts/build-wiki.py`](https://github.com/k-pz/gallery-dl-webui/blob/main/scripts/build-wiki.py)._"
    )
    write(out_dir / "_Footer.md", footer)


# ---------- Main ----------------------------------------------------------


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: build-wiki.py <output-dir>", file=sys.stderr)
        return 2

    out_dir = Path(argv[1]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"==> Building wiki into {out_dir}")

    copy_top_level_doc(REPO_ROOT / "README.md", out_dir / "Home.md", title="gallery-dl-webui")
    render_doc_pages(out_dir)
    render_http_api(out_dir)
    render_python_pages(out_dir)
    render_sidebar(out_dir)

    print("\n==> Managed files:")
    for name in MANAGED_FILES:
        marker = "✓" if (out_dir / name).exists() else "✗"
        print(f"   {marker} {name}")

    print("\n==> Done.")
    # Silence unused-import lint for shutil (kept for future use: e.g. asset copy).
    _ = shutil
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
