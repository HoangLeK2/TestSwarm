'use client';

import * as React from 'react';
import { endOfDay, startOfDay, subDays } from 'date-fns';

export type DateRangeValue = {
  from: Date;
  to: Date | undefined;
};

/** Default range: last 30 calendar days through end of today. */
export const DEFAULT_DATE_RANGE: DateRangeValue = {
  from: startOfDay(subDays(new Date(), 29)),
  to: endOfDay(new Date())
};

type DateRangeContextValue = {
  dateRange: DateRangeValue;
  setDateRange: React.Dispatch<React.SetStateAction<DateRangeValue>>;
};

const DateRangeContext = React.createContext<DateRangeContextValue | null>(
  null
);

export function DateRangeProvider({ children }: { children: React.ReactNode }) {
  const [dateRange, setDateRange] =
    React.useState<DateRangeValue>(DEFAULT_DATE_RANGE);

  const value = React.useMemo(() => ({ dateRange, setDateRange }), [dateRange]);

  return (
    <DateRangeContext.Provider value={value}>
      {children}
    </DateRangeContext.Provider>
  );
}

export function useDateRange(): DateRangeContextValue {
  const ctx = React.useContext(DateRangeContext);
  if (!ctx) {
    throw new Error('useDateRange must be used within DateRangeProvider');
  }
  return ctx;
}
