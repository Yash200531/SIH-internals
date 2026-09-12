import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { ClinicalIdentity } from "@/components/ClinicalIdentity";

export const metadata: Metadata = {
  title: "MediKiosk — Clinician Console",
  description: "Clinical case review and documentation platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="clinician-body">
        <ClinicalIdentity><div className="clinician-shell">
          <Sidebar />
          <div className="clinician-content">
            <header className="clinician-topbar">
              <div>
                <span className="mk-eyebrow">MediKiosk · Clinical workspace</span>
                <div className="facility-name">Patient intake and clinician review</div>
              </div>
              <div className="clinician-profile">
                <div className="profile-copy"><strong>Clinical access</strong><span>Records follow your session’s facility scope</span></div>
                <div className="profile-avatar" aria-hidden="true">MK</div>
              </div>
            </header>
            <main className="clinician-main">{children}</main>
          </div>
        </div></ClinicalIdentity>
      </body>
    </html>
  );
}
