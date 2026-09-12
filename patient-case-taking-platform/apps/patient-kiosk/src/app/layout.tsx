import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MediKiosk — Patient Kiosk",
  description: "Voice-first clinical case-taking for primary care.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="hi">
      <body className="antialiased">{children}</body>
    </html>
  );
}
