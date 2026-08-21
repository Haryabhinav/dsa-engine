import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets land in ../static/app and are served by FastAPI, so deployment
// stays a single Python process with no separate node server to run.
export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: { outDir: "../static/app", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:8777" } },
});
