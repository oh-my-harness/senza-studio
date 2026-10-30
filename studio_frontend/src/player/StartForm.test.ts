// isStartReady —— 开始按钮就绪判定：契约声明 optional 的字段可留空。
import { describe, expect, it } from "vitest";
import { isStartReady } from "./StartForm";

const storyGmFields = [
  { name: "player_input", optional: false },
  { name: "campaign_id", optional: true },
  { name: "dice_result", optional: true },
  { name: "input_type", optional: true },
  { name: "story_bible", optional: true },
];

describe("StartForm.isStartReady — optional entry fields", () => {
  it("enables start with only the required field filled", () => {
    expect(
      isStartReady(storyGmFields, {
        player_input: "Start a new campaign. I approach the innkeeper.",
      }),
    ).toBe(true);
  });

  it("keeps the required field mandatory even when optionals are filled", () => {
    expect(
      isStartReady(storyGmFields, {
        player_input: "",
        campaign_id: "default",
        dice_result: "12",
        input_type: "action",
        story_bible: "once upon a time",
      }),
    ).toBe(false);
  });

  it("keeps legacy agents fully mandatory (no optional metadata)", () => {
    const legacy = [{ name: "a" }, { name: "b" }];
    expect(isStartReady(legacy, { a: "1", b: "2" })).toBe(true);
    expect(isStartReady(legacy, { a: "1" })).toBe(false);
  });

  it("ignores surrounding whitespace on required fields", () => {
    expect(isStartReady(storyGmFields, { player_input: "   " })).toBe(false);
  });
});
