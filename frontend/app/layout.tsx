import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PackCheck AI | Legal Metrology Compliance Prototype",
  description: "SIH 2026 Problem Statement 26034 prototype",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
