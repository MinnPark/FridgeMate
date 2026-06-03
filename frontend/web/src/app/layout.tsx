import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FridgeMate AI",
  description: "추천이 아니라 검증과 실행까지 끝내는 End-to-End 자동화",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
