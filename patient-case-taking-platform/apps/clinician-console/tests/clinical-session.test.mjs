import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/clinicalSession.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
function session(provider = "clerk", fetch = async () => ({ ok: true, json: async () => ({ role: "doctor", facility_ids: ["facility"] }) })) {
  const stored = new Map([["medikiosk.access_token", "old-demo-token"], ["medikiosk.clinician_role", "doctor"]]);
  const context = { exports: {}, process: { env: { NEXT_PUBLIC_AUTH_PROVIDER: provider } },
    window: { sessionStorage: { getItem: key => stored.get(key), removeItem: key => stored.delete(key) } }, fetch, AbortSignal };
  vm.runInNewContext(output.outputText, context);
  return { ...context.exports, stored };
}

test("Clerk never falls back to stored demo credentials, including when its reader expires", async () => {
  const api = session();
  await assert.rejects(api.clinicalAccessToken(), { status: 401 });
  api.bindClinicalTokenReader(async () => null);
  await assert.rejects(api.clinicalAccessToken(), { status: 401 });
});

test("each request obtains the current provider token and old cleanup cannot detach a new session", async () => {
  const api = session();
  let generation = 0;
  const cleanup = api.bindClinicalTokenReader(async () => `token-${++generation}`);
  assert.equal(await api.clinicalAccessToken(), "token-1");
  assert.equal(await api.clinicalAccessToken(), "token-2");
  api.bindClinicalTokenReader(async () => "replacement");
  cleanup();
  assert.equal(await api.clinicalAccessToken(), "replacement");
});

test("clinical display role requires an internal API grant", async () => {
  const api = session("clerk", async () => ({ ok: true, json: async () => ({ role: "patient", facility_ids: ["facility"] }) }));
  api.bindClinicalTokenReader(async () => "signed-token");
  assert.equal(api.clinicalRole(), null);
  await assert.rejects(api.verifyClinicalSession(), { status: 403 });
  assert.equal(api.clinicalRole(), null);
});

test("revocation failure is reported and successful revocation clears local credentials", async () => {
  let status = 503;
  const api = session("demo", async () => ({ ok: status === 200, status }));
  await assert.rejects(api.revokeClinicalSession(), { status: 503 });
  assert.equal(api.stored.get("medikiosk.access_token"), "old-demo-token");
  status = 200;
  await api.revokeClinicalSession();
  assert.equal(api.stored.size, 0);
});
