import { quasar, transformAssetUrls } from "@quasar/vite-plugin"
import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vite"
import eslint from "vite-plugin-eslint"

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue({
      template: { transformAssetUrls },
      reactivityTransform: true,
    }),
    quasar({
      sassVariables: "src/quasar-variables.sass",
    }),
    eslint(),
  ],
})
