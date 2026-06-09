import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to the BenchBot API. In dev it defaults to
// http://localhost:8000 (see src/api.ts); override with VITE_API_URL.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
