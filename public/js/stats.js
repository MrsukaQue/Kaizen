(function (root) {
  const dateKey = date => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  };

  const addDays = (date, amount) => {
    const copy = new Date(date);
    copy.setDate(copy.getDate() + amount);
    return copy;
  };

  const percentage = (completed, total) => total ? Math.round(completed / total * 100) : 0;

  function dayProgress(day = {}) {
    const completed = day.completed?.length || 0;
    const total = day.total ?? 0;
    return { completed, total, percent: percentage(completed, total) };
  }

  function streaks(days, today = new Date()) {
    const successful = Object.keys(days).filter(key => dayProgress(days[key]).percent === 100 && days[key].total > 0).sort();
    let best = 0;
    let run = 0;
    let previous = null;

    successful.forEach(key => {
      const current = new Date(`${key}T12:00:00`);
      run = previous && Math.round((current - previous) / 86400000) === 1 ? run + 1 : 1;
      best = Math.max(best, run);
      previous = current;
    });

    let current = 0;
    let cursor = new Date(today);
    if (dayProgress(days[dateKey(cursor)]).percent < 100) cursor = addDays(cursor, -1);
    while (dayProgress(days[dateKey(cursor)]).percent === 100 && days[dateKey(cursor)]?.total > 0) {
      current++;
      cursor = addDays(cursor, -1);
    }
    return { current, best };
  }

  function habitStreak(days, habitId, today = new Date()) {
    let count = 0;
    let cursor = new Date(today);
    if (!days[dateKey(cursor)]?.completed?.includes(habitId)) cursor = addDays(cursor, -1);
    while (days[dateKey(cursor)]?.completed?.includes(habitId)) {
      count++;
      cursor = addDays(cursor, -1);
    }
    return count;
  }

  function lastSevenDays(days, today = new Date()) {
    return Array.from({ length: 7 }, (_, index) => {
      const date = addDays(today, index - 6);
      return { date, key: dateKey(date), ...dayProgress(days[dateKey(date)]) };
    });
  }

  const api = { dateKey, dayProgress, streaks, habitStreak, lastSevenDays };
  root.KaizenStats = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
