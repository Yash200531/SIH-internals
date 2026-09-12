import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MediKiosk — Clinician Console",
  description: "Clinical case review and documentation platform",
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <main className="min-h-screen bg-gray-50">{children}</main>;
}
