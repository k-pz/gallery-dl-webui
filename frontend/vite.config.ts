import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig(() => {
  const apiPort = process.env.VITE_API_PORT ?? "8000";
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: `http://localhost:${apiPort}`,
          ws: true,
        },
      },
    },
    build: {
      rolldownOptions: {
        output: {
          manualChunks: (id) => {
            if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) {
              return "react";
            }
            if (id.includes("node_modules/@mantine")) {
              return "mantine";
            }
            if (id.includes("node_modules/@tanstack")) {
              return "tanstack";
            }
          },
        },
      },
    },
  };
});
