import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Standalone app — builds to frontend/dist, served independently of the
// backend (see src/lib/api.ts's API_BASE / VITE_API_BASE). The dev-server
// proxy below is just a same-origin convenience for `npm run dev`; it plays
// no role in a built/deployed frontend, which talks to the backend directly
// over CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8010",
    },
  },
});
