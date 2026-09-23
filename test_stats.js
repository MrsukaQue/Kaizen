const assert = require("node:assert/strict");
const stats = require("./public/js/stats.js");

const days = {
  "2026-09-20": { completed: ["a"], total: 1 },
  "2026-09-21": { completed: ["a"], total: 1 },
  "2026-09-22": { completed: ["a"], total: 1 },
  "2026-09-23": { completed: [], total: 1 }
};

assert.deepEqual(stats.dayProgress({ completed: ["a", "b"], total: 4 }), { completed: 2, total: 4, percent: 50 });
assert.deepEqual(stats.streaks(days, new Date("2026-09-23T12:00:00")), { current: 3, best: 3 });
assert.equal(stats.habitStreak(days, "a", new Date("2026-09-23T12:00:00")), 3);
assert.equal(stats.lastSevenDays(days, new Date("2026-09-23T12:00:00")).length, 7);
console.log("Statistics checks passed.");
