import tailwindcss from "@tailwindcss/vite";
import { reactRouter } from "@react-router/dev/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [tailwindcss(), reactRouter()],
  resolve: { tsconfigPaths: true },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: "charts-vendor", test: /node_modules[\\/](recharts|d3-|victory-vendor)/, includeDependenciesRecursively: true, priority: 20 },
            { name: "topology-vendor", test: /node_modules[\\/]@xyflow/, includeDependenciesRecursively: true, priority: 20 },
          ],
        },
      },
    },
  },
  server: { port: 5173 },
});
