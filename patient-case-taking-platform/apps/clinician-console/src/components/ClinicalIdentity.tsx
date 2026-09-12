"use client";

import { ClerkProvider, SignIn, useAuth } from "@clerk/nextjs";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { bindClinicalTokenReader, clerkEnabled, revokeClinicalSession, verifyClinicalSession } from "@/lib/clinicalSession";

function VerifiedClinicalSession({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn, sessionId, getToken, signOut } = useAuth();
  const pathname = usePathname();
  const [verifiedSession, setVerifiedSession] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !sessionId) return;
    const controller = new AbortController();
    const unbind = bindClinicalTokenReader(() => getToken());
    verifyClinicalSession(controller.signal).then(() => {
      if (!controller.signal.aborted) { setError(""); setVerifiedSession(sessionId); }
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) {
        setVerifiedSession(null);
        setError(failure instanceof Error ? failure.message : "Clinical access unavailable.");
      }
    });
    return () => { controller.abort(); unbind(); };
  }, [isLoaded, isSignedIn, sessionId, getToken, attempt]);

  async function leave() {
    setLeaving(true); setError(""); setVerifiedSession(null);
    try { await revokeClinicalSession(); await signOut({ redirectUrl: "/login" }); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Sign-out failed. Please retry."); }
    finally { setLeaving(false); }
  }

  if (!isLoaded) return <p role="status">Loading secure session…</p>;
  if (!isSignedIn) return <section className="dev-login-card"><h1>Sign in to your clinical workspace</h1>
    <SignIn routing="hash" forceRedirectUrl="/worklist" /></section>;
  return <>
    <div className="clinical-session-controls">
      <span>Clinical session</span>
      <button className="mk-button" onClick={leave} disabled={leaving}>{leaving ? "Signing out…" : "Sign out"}</button>
    </div>
    {error ? <section role="alert"><p>{error}</p><button className="mk-button" onClick={() => { setError(""); setAttempt(value => value + 1); }}>Retry verification</button></section>
      : verifiedSession !== sessionId || leaving ? <p role="status">Verifying facility access…</p>
      : pathname === "/login" ? <a className="mk-button" href="/worklist">Open clinical workspace</a> : children}
  </>;
}

export function ClinicalIdentity({ children }: { children: React.ReactNode }) {
  if (!clerkEnabled) return children;
  const publishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  if (!publishableKey) return <p role="alert">Clinical sign-in is not configured. Contact your administrator.</p>;
  return <ClerkProvider publishableKey={publishableKey} signInUrl="/login">
    <VerifiedClinicalSession>{children}</VerifiedClinicalSession>
  </ClerkProvider>;
}
