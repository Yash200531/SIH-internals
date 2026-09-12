import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/patientPortal.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });

test("delayed unauthorized response clears only the session that sent the request", async () => {
  for (const switched of [false, true]) {
    const original = { patientId: "first", accessToken: "" };
    let current = original;
    let cleared = 0;
    let finish;
    const response = new Promise(resolve => { finish = resolve; });
    const context = { exports: {}, process: { env: {} }, fetch: () => response,
      sessionStorage: { removeItem: () => {} },
      require: () => ({ patientClerkEnabled: true,
        currentPatientIdentity: () => current,
        clearPatientIdentity: () => { cleared += 1; current = null; },
        patientAccessToken: async () => "signed-token",
      }) };
    vm.runInNewContext(output.outputText, context);
    const request = context.exports.getPatientDashboard(original);
    if (switched) current = { patientId: "second", accessToken: "" };
    finish({ status: 401, ok: false });
    await assert.rejects(request, /401/);
    assert.equal(cleared, switched ? 0 : 1);
    if (switched) assert.equal(current.patientId, "second");
  }
});
