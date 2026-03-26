import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ScholarBridge",
  description: "Connecting non-profits with academic research",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
