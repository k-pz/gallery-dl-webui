"""Generate per-domain Python reference stubs for mkdocstrings.

Invoked by `mkdocs-gen-files` at build time. Emits one Markdown page under
`reference/python/` per backend domain, each containing a `::: backend.<pkg>`
directive that `mkdocstrings` expands into a typed reference.

The DOMAINS table mirrors the wiki-era grouping from the deleted
`build-wiki.py` so the new site preserves the same per-domain page layout.
"""

from __future__ import annotations

import mkdocs_gen_files

DOMAINS: list[tuple[str, str, list[str]]] = [
    (
        "core",
        "Core (main, config, db)",
        [
            "backend.main",
            "backend.config",
            "backend.database",
            "backend.dependencies",
            "backend.exceptions",
        ],
    ),
    ("downloads", "Downloads", ["backend.downloads"]),
    ("targets", "Targets", ["backend.targets"]),
    ("library", "Library", ["backend.library"]),
    ("app-config", "App config", ["backend.app_config"]),
    ("output-dirs", "Output dirs", ["backend.output_dirs"]),
    ("health", "Health", ["backend.health"]),
]


for slug, title, packages in DOMAINS:
    with mkdocs_gen_files.open(f"reference/python/{slug}.md", "w") as fp:
        fp.write(f"# {title}\n\n")
        fp.write(f"Auto-generated from `{', '.join(packages)}`.\n\n")
        for pkg in packages:
            fp.write(f"::: {pkg}\n    options:\n      show_submodules: true\n\n")
