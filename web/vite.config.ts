import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // Đọc cả .env ở thư mục gốc repo (không chỉ web/) để chạy `npm run dev` trực tiếp cũng nhận cấu hình.
  const env = { ...loadEnv(mode, fileURLToPath(new URL("..", import.meta.url)), ""), ...process.env };
  const api = env.API_URL ?? "http://localhost:8000";
  // Host ngoài (vd tunnel) được phép mở dev server — đặt trong .env, không ghi cứng vào repo.
  const allowedHosts = (env.DEV_ALLOWED_HOSTS ?? "")
    .split(",")
    .map((h) => h.trim())
    .filter(Boolean);

  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: {
      host: true,
      port: 5173,
      allowedHosts,
      proxy: { "/api": { target: api, changeOrigin: false } },
    },
    build: {
      chunkSizeWarningLimit: 1500,
    },
  };
});
