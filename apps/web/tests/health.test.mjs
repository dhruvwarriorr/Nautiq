import test from "node:test";
import assert from "node:assert/strict";
import {dependencyNames, validateReport} from "../lib/health.mjs";
const report = () => ({status:"healthy", checked_at:new Date().toISOString(), dependencies:Object.fromEntries(dependencyNames.map(name => [name,{status:"healthy"}]))});
test("complete health report is accepted", () => assert.equal(validateReport(report()).status, "healthy"));
test("missing dependency cannot appear healthy", () => { const value = report(); delete value.dependencies.minio; assert.throws(() => validateReport(value)); });
test("failed dependency cannot appear healthy", () => { const value = report(); value.dependencies.redis.status = "unavailable"; assert.throws(() => validateReport(value)); value.status = "degraded"; assert.equal(validateReport(value).status,"degraded"); });
