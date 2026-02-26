import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 3009,
    allowedHosts: ["j19hah46.run.complete.dev", "all"],
    hmr: {
      protocol: "wss",
      host: "j19hah46.run.complete.dev",
      clientPort: 443,
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 3009,
    allowedHosts: ["j19hah46.run.complete.dev", "all"],
  },
});
