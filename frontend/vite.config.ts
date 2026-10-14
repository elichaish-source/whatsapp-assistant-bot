import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // בפיתוח מקומי: מעביר בקשות API לשרת ה-FastAPI
    proxy: { "/api": "http://localhost:8000" },
  },
});
