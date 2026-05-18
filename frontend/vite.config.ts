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
  };
});
