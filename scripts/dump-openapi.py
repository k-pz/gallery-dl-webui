"""Dump the FastAPI app's OpenAPI schema to a JSON file.

Used by the docs build to seed the Redoc embed without booting a live server.
The app's lifespan is not entered — we only need `app.openapi()`, which is
synthesised from the registered routers + Pydantic models.

Usage:
    uv run python scripts/dump-openapi.py docs/reference/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.main import create_app


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: dump-openapi.py <output-path>", file=sys.stderr)
        return 2

    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)

    # serve_frontend=False keeps the SPA fallback route out of the schema so
    # the spec lists only `/api/*` endpoints, which is what consumers care
    # about. (The catch-all is `include_in_schema=False` already, but skipping
    # the mount avoids touching frontend/dist at all.)
    app = create_app(serve_frontend=False)
    schema = app.openapi()

    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
