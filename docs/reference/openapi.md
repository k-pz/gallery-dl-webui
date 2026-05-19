---
title: HTTP API
---

# HTTP API

The backend exposes a JSON HTTP API under `/api`. The spec below is the
`openapi.json` produced by FastAPI's introspection of the live app — it is
re-generated on every docs build (see `scripts/dump-openapi.py`).

<redoc spec-url="openapi.json" hide-download-button></redoc>

<script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>

<style>
  /* Redoc inherits Material's font; widen its column on desktop so route
     signatures and the schema panel both have room. */
  redoc { --redoc-margin: 0; }
  .md-content__inner > redoc { display: block; }
  .md-typeset h1 + redoc { margin-top: 1rem; }
</style>
