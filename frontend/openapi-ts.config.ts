import { defineConfig } from "@hey-api/openapi-ts";

// Same port override the vite proxy honours, so codegen works against a
// backend started on a non-default port (e.g. the e2e server on 8765).
const apiPort = process.env.VITE_API_PORT ?? "8000";

export default defineConfig({
  input: `http://localhost:${apiPort}/openapi.json`,
  output: "src/api",
  plugins: ["@hey-api/client-fetch", "@tanstack/react-query"],
});
