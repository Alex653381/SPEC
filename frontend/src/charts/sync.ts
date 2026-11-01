export interface ZoomWindow {
  start: string | null;
  end: string | null;
}

export function dateToIndex(dates: string[], date: string | null): number {
  if (date === null) return -1;
  return dates.indexOf(date);
}

export function zoomPercentFor(dates: string[], window: ZoomWindow): { start: number; end: number } {
  if (dates.length === 0 || window.start === null || window.end === null) {
    return { start: 0, end: 100 };
  }
  if (dates.length === 1) return { start: 0, end: 100 };

  let startIndex = 0;
  let endIndex = dates.length - 1;
  for (let index = 0; index < dates.length; index += 1) {
    if (dates[index] >= window.start) {
      startIndex = index;
      break;
    }
  }
  for (let index = dates.length - 1; index >= 0; index -= 1) {
    if (dates[index] <= window.end) {
      endIndex = index;
      break;
    }
  }
  if (endIndex < startIndex) endIndex = startIndex;
  const span = dates.length - 1;
  return {
    start: (startIndex / span) * 100,
    end: (endIndex / span) * 100,
  };
}

export function visibleDates(dates: string[], startPercent: number, endPercent: number): ZoomWindow {
  if (dates.length === 0) return { start: null, end: null };
  if (dates.length === 1) return { start: dates[0], end: dates[0] };
  const span = dates.length - 1;
  const startIndex = Math.max(0, Math.round((startPercent / 100) * span));
  const endIndex = Math.min(span, Math.round((endPercent / 100) * span));
  return { start: dates[startIndex], end: dates[endIndex] };
}
