import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/kioskSession.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });

test("intake start uses verified credential and server-owned encounter/session identifiers", async () => {
  const stored = new Map();
  let request;
  const context = { exports: {}, process: { env: {} }, crypto: { randomUUID: () => "request-key" },
    localStorage: { setItem: (key, value) => stored.set(key, value) },
    require: name => name === "./patientPortal" ? {
      readPatientSession: () => ({ facilityId: "assigned-facility" }),
      createDemoPatientSession: () => { throw new Error("Demo must not be used in Clerk mode"); },
    } : { patientClerkEnabled: true, patientAccessToken: async () => "current-token" },
    fetch: async (url, init) => { request = { url, ...init }; return {
      ok: true, json: async () => ({ id: "server-session", encounter_id: "server-encounter" }),
    }; } };
  vm.runInNewContext(output.outputText, context);
  const result = await context.exports.startLocalKioskSession("hi");
  assert.equal(result.sessionId, "server-session");
  assert.equal(result.encounterId, "server-encounter");
  assert.equal(stored.get("notmid-encounter-id"), "server-encounter");
  assert.equal(request.headers.Authorization, "Bearer current-token");
  assert.equal(request.headers["Idempotency-Key"], "request-key");
  assert.deepEqual(JSON.parse(request.body), { facility_id: "assigned-facility", language: "hi" });
  assert.equal(request.url, "http://localhost:8000/api/v1/patient-portal/me/sessions");
});
