import assert from "node:assert/strict";
import test from "node:test";

import { findDraft, parseCallbackData } from "../src/index.js";

test("parseCallbackData accepts moderation buttons", () => {
  assert.deepEqual(parseCallbackData("publish:a603b981f525a23e"), {
    action: "publish",
    draftId: "a603b981f525a23e",
  });
  assert.deepEqual(parseCallbackData("skip:747b8a67f1c11459"), {
    action: "skip",
    draftId: "747b8a67f1c11459",
  });
});

test("parseCallbackData rejects unknown or malformed values", () => {
  assert.equal(parseCallbackData("delete:a603b981f525a23e"), null);
  assert.equal(parseCallbackData("publish:short"), null);
  assert.equal(parseCallbackData(null), null);
});

test("findDraft checks both id and moderation message", () => {
  const payload = {
    items: [
      {
        id: "a603b981f525a23e",
        review_message_id: 17,
        status: "pending",
      },
    ],
  };

  assert.equal(
    findDraft(payload, "a603b981f525a23e", 17)?.status,
    "pending",
  );
  assert.equal(findDraft(payload, "a603b981f525a23e", 18), null);
});
