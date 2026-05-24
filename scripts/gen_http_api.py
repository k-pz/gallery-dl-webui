"""Render the FastAPI OpenAPI schema into a Markdown reference page.

Invoked by `mkdocs-gen-files` at build time. Writes two files into the
docs tree:

  reference/http-api.md   ← human-readable endpoint + schema reference
  reference/api-spec.json ← raw OpenAPI spec (importable into Postman etc.)

The rendering helpers cover per-tag grouping, schema $ref anchor cross-refs,
and anyOf/oneOf/allOf union handling.
"""

from __future__ import annotations

import json
from typing import Any

import mkdocs_gen_files

from backend.main import create_app


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


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


app = create_app(serve_frontend=False)
spec = app.openapi()

with mkdocs_gen_files.open("reference/api-spec.json", "w") as fp:
    json.dump(spec, fp, indent=2, sort_keys=True)

paths = spec.get("paths", {})
by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
for path, methods in sorted(paths.items()):
    for method, op in methods.items():
        if method.lower() not in {"get", "post", "put", "patch", "delete"}:
            continue
        tag = (op.get("tags") or ["misc"])[0]
        by_tag.setdefault(tag, []).append((method, path, op))

out: list[str] = [
    "# HTTP API",
    "",
    (
        f"Generated from the live FastAPI app — **OpenAPI {spec.get('openapi', '?')}**, "
        f"`{spec.get('info', {}).get('title', '')}` "
        f"v{spec.get('info', {}).get('version', '0.0.0')}."
    ),
    "",
    "Raw spec: [`api-spec.json`](api-spec.json) (commit it to your API "
    "client of choice).",
    "",
    "## Endpoints",
    "",
]

for tag in sorted(by_tag):
    out += [f"### {tag}", ""]
    for method, path, op in by_tag[tag]:
        out += [_render_operation(method, path, op)]

schemas = (spec.get("components") or {}).get("schemas") or {}
if schemas:
    out += ["## Schemas", ""]
    for name in sorted(schemas):
        out += [_render_schema(name, schemas[name])]

with mkdocs_gen_files.open("reference/http-api.md", "w") as fp:
    fp.write("\n".join(out) + "\n")
