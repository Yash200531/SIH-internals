import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest, type NextFetchEvent } from "next/server";

export default function proxy(request: NextRequest, event: NextFetchEvent) {
  if (process.env.NEXT_PUBLIC_AUTH_PROVIDER !== "clerk") return NextResponse.next();
  const audience = process.env.CLERK_AUDIENCE;
  const authorizedParties = (process.env.CLERK_AUTHORIZED_PARTIES ?? "").split(",").map(value => value.trim()).filter(Boolean);
  if (!audience || !authorizedParties.length || !process.env.CLERK_SECRET_KEY || !process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return new NextResponse("Clinical sign-in is not configured. Contact your administrator.", {
      status: 503, headers: { "Cache-Control": "private, no-store" },
    });
  }
  return clerkMiddleware(async (auth, req) => {
    const session = await auth();
    // Clerk permits tokens without aud by default; this platform requires an
    // exact single application audience, matching the FastAPI boundary.
    if (session.userId && session.sessionClaims?.aud !== audience) {
      return new NextResponse("Session belongs to a different application.", {
        status: 401, headers: { "Cache-Control": "private, no-store" },
      });
    }
    if (req.nextUrl.pathname !== "/login") await auth.protect();
  }, { audience, authorizedParties, signInUrl: "/login" })(request, event);
}

export const config = {
  matcher: ["/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)", "/(api|trpc)(.*)"],
};
