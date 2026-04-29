import path from "path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  /** dev-api.mjs ile ayni; .env icinde DEV_API_PORT=... kullanilabilir */
  const panelApiPort = env.DEV_API_PORT || process.env.DEV_API_PORT || "8001";

  return {
  server: {
    host: "::",
    port: 8080,
    // Ayni agdaki telefon/tablet'ten http://<PC-IP>:8080 acildiginde dogrudan localhost:API_PORT
    // istemciye gider ve "Failed to fetch" olur; /api Vite uzerinden backend'e proxylanir.
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${panelApiPort}`,
        changeOrigin: true,
      },
    },
    hmr: {
      overlay: false,
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
};
});
