import type { Config } from "tailwindcss";

// Design tokens — port từ trang /tai-lieu (tông tài liệu pháp lý: nền giấy mát, mực slate, nhấn xanh-ngọc).
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F4F6F7",
        surface: "#FFFFFF",
        ink: "#15212B",
        muted: "#5C6B77",
        accent: "#0E6E5B",
        "accent-d": "#0A5446",
        tint: "#E6F1ED",
        line: "#E1E7EA",
      },
      fontFamily: {
        serif: ['Georgia', '"Iowan Old Style"', '"Times New Roman"', "serif"],
        sans: ["system-ui", "-apple-system", '"Segoe UI"', "Roboto", "Helvetica", "Arial", "sans-serif"],
        mono: ["ui-monospace", '"SF Mono"', "Menlo", "Consolas", "monospace"],
      },
      maxWidth: { reading: "840px" },
    },
  },
  plugins: [],
};
export default config;
