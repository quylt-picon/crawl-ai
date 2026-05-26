import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    allowedHosts: ["dd-quylt.local"],
    proxy: {
      "/api": {
        target: "http://dd-quylt.local:8080",
        changeOrigin: true,
      },
    },
  },
});
