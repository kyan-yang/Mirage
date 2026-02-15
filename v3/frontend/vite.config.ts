import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/generate": {
        target: "https://kevinthomas--scenario-gen-viewer.modal.run",
        changeOrigin: true,
        secure: true,
      },
      "/runs": {
        target: "https://kevinthomas--scenario-gen-viewer.modal.run",
        changeOrigin: true,
        secure: true,
      },
      "/health": {
        target: "https://kevinthomas--scenario-gen-viewer.modal.run",
        changeOrigin: true,
        secure: true,
      },
    },
  },
});
