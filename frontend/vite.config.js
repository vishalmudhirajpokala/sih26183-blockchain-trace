import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    /**
     * The `@/` prefix.
     *
     * Every file under `src/` imports its neighbours as `@/components/...`,
     * `@/lib/...`, `@/hooks/...`, which is what `components.json` and
     * `jsconfig.json` both declare. Vite does not read `jsconfig.json` paths on
     * its own — without this alias the whole component layer fails to resolve.
     * It is resolved from `import.meta.url` rather than `__dirname` so it holds
     * on any platform, and from the URL rather than a relative path so it does
     * not depend on the process working directory.
     */
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
