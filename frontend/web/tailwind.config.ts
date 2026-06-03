import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 발표 데모 화면의 다크 그린 테마.
        ink: {
          900: "#0e1410", // 가장 어두운 배경
          800: "#131b15",
          700: "#1a241c", // 카드(다크) 배경
          600: "#22301f",
        },
        lime: {
          accent: "#c4f542", // 강조(진행 중, CTA)
        },
        gold: "#f5c542", // 쿠팡 담기 버튼 / 아바타
      },
      fontFamily: {
        sans: [
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Apple SD Gothic Neo",
          "Noto Sans KR",
          "sans-serif",
        ],
      },
      keyframes: {
        pulseGlow: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
      },
      animation: {
        pulseGlow: "pulseGlow 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
