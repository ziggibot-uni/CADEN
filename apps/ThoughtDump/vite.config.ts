import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5174,
    strictPort: true,
    watch: {
      include: [path.resolve(__dirname, "../../caden-colors.js"), "src/**"],
    },
  },
});
