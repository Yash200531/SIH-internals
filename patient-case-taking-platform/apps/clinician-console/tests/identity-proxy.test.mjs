import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/proxy.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
function proxy({ audience = "clinician-app", configured = true } = {}) {
  let protectedRoute = false;
  let options;
  class NextResponse extends Response { static next() { return new Response(null); } }
  const context = { exports: {}, process: { env: { NEXT_PUBLIC_AUTH_PROVIDER: "clerk",
    CLERK_AUDIENCE: "clinician-app", CLERK_AUTHORIZED_PARTIES: "https://staff.example.test",
    CLERK_SECRET_KEY: configured ? "synthetic" : "", NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "synthetic" } },
    require: name => name === "next/server" ? { NextResponse } : {
      clerkMiddleware: (handler, config) => {
        options = config;
        const auth = async () => ({ userId: "user_test", sessionClaims: { aud: audience } });
        auth.protect = async () => { protectedRoute = true; };
        return request => handler(auth, request);
      },
    } };
  vm.runInNewContext(output.outputText, context);
  return { run: pathname => context.exports.default({ nextUrl: { pathname } }, {}),
    protected: () => protectedRoute, options: () => options };
}

test("unconfigured Clerk returns unavailable without invoking the SDK", async () => {
  const boundary = proxy({ configured: false });
  assert.equal((await boundary.run("/worklist")).status, 503);
  assert.equal(boundary.options(), undefined);
});

test("missing, array and patient audiences are rejected even after SDK authentication", async () => {
  for (const audience of [null, ["clinician-app"], "patient-app"]) {
    const boundary = proxy({ audience });
    const response = await boundary.run("/worklist");
    assert.equal(response.status, 401);
    assert.equal(response.headers.get("Cache-Control"), "private, no-store");
  }
});

test("clinical route protection receives pinned audience and origins", async () => {
  const boundary = proxy();
  await boundary.run("/worklist");
  assert.equal(boundary.protected(), true);
  assert.equal(boundary.options().audience, "clinician-app");
  assert.equal(boundary.options().authorizedParties.join(), "https://staff.example.test");
});
