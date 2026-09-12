import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
const source = fs.readFileSync(new URL("../src/lib/questionnaires.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
const context = { exports: {} };
vm.runInNewContext(output.outputText, context);
const { describeAnswers, ALLOPATHIC_HISTORY } = context.exports;

test("confirmed choices retain readable meaning in both supported languages", () => {
  assert.equal(describeAnswers(ALLOPATHIC_HISTORY, { cc_main: "breathing" }, "en").cc_main, "Breathing Difficulty");
  assert.equal(describeAnswers(ALLOPATHIC_HISTORY, { cc_main: "breathing" }, "hi").cc_main, "सांस लेने में तकलीफ");
});

test("multi-choice answers translate and free speech remains unchanged", () => {
  const result = describeAnswers(ALLOPATHIC_HISTORY, {
    med_names: ["bp_medicine", "sugar_medicine"],
    cc_main: "I cannot breathe",
    cc_severity: "8",
  }, "en");
  assert.equal(result.med_names, "BP medicine, Sugar/Diabetes medicine");
  assert.equal(result.cc_main, "I cannot breathe");
  assert.equal(result.cc_severity, "8");
});
