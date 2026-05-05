import test from "node:test";
import assert from "node:assert/strict";

import { getLocalPostgresTarget, isDemoModeEnabled } from "./dev-api-helpers.mjs";

test("isDemoModeEnabled accepts common true values", () => {
  for (const value of ["1", "true", "yes", "on", " TRUE "]) {
    assert.equal(isDemoModeEnabled(value), true);
  }
});

test("isDemoModeEnabled rejects false and empty values", () => {
  for (const value of ["0", "false", "no", "", undefined]) {
    assert.equal(isDemoModeEnabled(value), false);
  }
});

test("getLocalPostgresTarget extracts local postgres host and port", () => {
  assert.deepEqual(
    getLocalPostgresTarget("postgresql://semas:12345@localhost:5432/agent_db"),
    { host: "localhost", port: 5432 },
  );
  assert.deepEqual(
    getLocalPostgresTarget("postgresql://semas:12345@127.0.0.1/agent_db"),
    { host: "127.0.0.1", port: 5432 },
  );
});

test("getLocalPostgresTarget ignores non-local or invalid database URLs", () => {
  assert.equal(getLocalPostgresTarget("postgresql://db.example.com:5432/agent_db"), null);
  assert.equal(getLocalPostgresTarget("not-a-url"), null);
});
