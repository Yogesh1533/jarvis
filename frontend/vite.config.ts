import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the HUD with hot reload and proxies the Python
// server (python -m jarvis web) for the API and the live socket.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
});
