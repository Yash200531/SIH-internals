import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/patientIdentity.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
function identity({ role = "patient", facilities = ["facility"], provider = "clerk" } = {}) {
  const references = new Map([["notmid-consent-id", "previous-consent"], ["notmid-encounter-id", "previous-encounter"]]);
  const context = { exports: {}, process: { env: { NEXT_PUBLIC_AUTH_PROVIDER: provider } },
    localStorage: { removeItem: key => references.delete(key) },
    fetch: async () => ({ ok: true, json: async () => ({ role, user_id: "patient", tenant_id: "tenant", facility_ids: facilities }) }) };
  vm.runInNewContext(output.outputText, context);
  return { ...context.exports, references };
}

test("Clerk patient access cannot fall back to an old stored credential", async () => {
  const api = identity();
  await assert.rejects(api.patientAccessToken({ accessToken: "old-demo" }), /changed/);
});

test("binding clears prior intake references and retrieves fresh tokens without storing them", async () => {
  const api = identity();
  let counter = 0;
  await api.bindPatientIdentity(async () => `token-${++counter}`);
  const session = api.currentPatientIdentity();
  assert.equal(session.accessToken, "");
  assert.equal(api.references.size, 0);
  assert.equal(await api.patientAccessToken(session), "token-2");
  assert.equal(await api.patientAccessToken(session), "token-3");
});

test("a prior screen cannot acquire the next patient's token", async () => {
  const api = identity();
  const cleanup = await api.bindPatientIdentity(async () => "first");
  const previous = api.currentPatientIdentity();
  await api.bindPatientIdentity(async () => "second");
  cleanup();
  await assert.rejects(api.patientAccessToken(previous), /changed/);
  assert.equal(await api.patientAccessToken(api.currentPatientIdentity()), "second");
});

test("account switch during token refresh rejects the pending request", async () => {
  const api = identity();
  let resolve;
  let reads = 0;
  await api.bindPatientIdentity(async () => ++reads === 1 ? "initial" : new Promise(done => { resolve = done; }));
  const pending = api.patientAccessToken(api.currentPatientIdentity());
  api.clearPatientIdentity();
  resolve("late-token");
  await assert.rejects(pending, /changed/);
});

test("clinical roles and ambiguous facility selection cannot become patient access", async () => {
  for (const configuration of [{ role: "doctor" }, { facilities: [] }, { facilities: ["one", "two"] }]) {
    const api = identity(configuration);
    await assert.rejects(api.bindPatientIdentity(async () => "token"));
    assert.equal(api.currentPatientIdentity(), null);
  }
});
