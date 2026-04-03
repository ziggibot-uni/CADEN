import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      // Watch the shared color palette so Tailwind recompiles when it changes
      include: [path.resolve(__dirname, "../../caden-colors.js"), "src/**"],
    },
  },
});
