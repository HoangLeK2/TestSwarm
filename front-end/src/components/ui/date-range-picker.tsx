/* eslint-disable max-lines */
'use client';

import React, { type FC, useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { Calendar } from '@/components/ui/calendar';
// import { DateInput } from '@/components/ui/date-input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import {
  ChevronUpIcon,
  ChevronDownIcon,
  CheckIcon
} from '@radix-ui/react-icons';
import { cn } from '@/lib/utils';
import { format } from 'date-fns';
import { CalendarIcon } from 'lucide-react';
import { useTranslations } from 'next-intl';

export interface DateRangePickerProps {
  /** Click handler for applying the updates from DateRangePicker. */
  onUpdate?: (values: { range: DateRange; rangeCompare?: DateRange }) => void;
  /** Value change handler for direct integration */
  onValueChange?: (value: DateRange) => void;
  /** Clear handler */
  onClear?: () => void;
  /** Current value */
  value?: DateRange;
  /** Initial value for start date */
  initialDateFrom?: Date | string;
  /** Initial value for end date */
  initialDateTo?: Date | string;
  /** Initial value for start date for compare */
  initialCompareFrom?: Date | string;
  /** Initial value for end date for compare */
  initialCompareTo?: Date | string;
  /** Alignment of popover */
  align?: 'start' | 'center' | 'end';
  /** Option for locale */
  locale?: string | any;
  /** Option for showing compare feature */
  showCompare?: boolean;
  /** Placeholder text */
  placeholder?: string;
  /** Size of the button */
  size?: 'default' | 'sm' | 'lg';
  /** Additional className */
  className?: string;
}

const formatDate = (date: Date, locale: string | any = 'en-us'): string => {
  // Handle date-fns locale object
  const localeString = typeof locale === 'string' ? locale : 'en-us';
  return date.toLocaleDateString(localeString, {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  });
};

const getDateAdjustedForTimezone = (dateInput: Date | string): Date => {
  if (typeof dateInput === 'string') {
    // Split the date string to get year, month, and day parts
    const parts = dateInput.split('-').map((part) => parseInt(part, 10));
    // Create a new Date object using the local timezone
    // Note: Month is 0-indexed, so subtract 1 from the month part
    const date = new Date(parts[0], parts[1] - 1, parts[2]);
    return date;
  } else {
    // If dateInput is already a Date object, return it directly
    return dateInput;
  }
};

interface DateRange {
  from: Date;
  to: Date | undefined;
}

interface Preset {
  name: string;
  label: string;
}

// Define presets - will be localized later if needed
const getPresets = (t: any): Preset[] => [
  { name: 'today', label: t('today') },
  { name: 'yesterday', label: t('yesterday') },
  { name: 'last7', label: t('last7Days') },
  { name: 'last14', label: t('last14Days') },
  { name: 'last30', label: t('last30Days') },
  { name: 'thisWeek', label: t('thisWeek') },
  { name: 'lastWeek', label: t('lastWeek') },
  { name: 'thisMonth', label: t('thisMonth') },
  { name: 'lastMonth', label: t('lastMonth') }
];

/** The DateRangePicker component allows a user to select a range of dates */
export const DateRangePicker: FC<DateRangePickerProps> & {
  filePath: string;
} = ({
  initialDateFrom = new Date(new Date().setHours(0, 0, 0, 0)),
  initialDateTo,
  initialCompareFrom,
  initialCompareTo,
  onUpdate,
  onValueChange,
  onClear,
  value,
  align = 'end',
  locale = 'en-US',
  showCompare = true,
  placeholder,
  size = 'lg',
  className
}): React.ReactNode => {
  const t = useTranslations('common.datePicker');
  const [isOpen, setIsOpen] = useState(false);

  const [range, setRange] = useState<DateRange>(
    value || {
      from: getDateAdjustedForTimezone(initialDateFrom),
      to: initialDateTo
        ? getDateAdjustedForTimezone(initialDateTo)
        : getDateAdjustedForTimezone(initialDateFrom)
    }
  );
  const [rangeCompare, setRangeCompare] = useState<DateRange | undefined>(
    initialCompareFrom
      ? {
          from: new Date(new Date(initialCompareFrom).setHours(0, 0, 0, 0)),
          to: initialCompareTo
            ? new Date(new Date(initialCompareTo).setHours(0, 0, 0, 0))
            : new Date(new Date(initialCompareFrom).setHours(0, 0, 0, 0))
        }
      : undefined
  );

  // Refs to store the values of range and rangeCompare when the date picker is opened
  const openedRangeRef = useRef<DateRange | undefined>(range);
  const openedRangeCompareRef = useRef<DateRange | undefined>(rangeCompare);

  const [selectedPreset, setSelectedPreset] = useState<string | undefined>(
    undefined
  );

  const [isSmallScreen, setIsSmallScreen] = useState(
    typeof window !== 'undefined' ? window.innerWidth < 960 : false
  );

  useEffect(() => {
    const handleResize = (): void => {
      setIsSmallScreen(window.innerWidth < 960);
    };

    window.addEventListener('resize', handleResize);

    // Clean up event listener on unmount
    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  const getPresetRange = (presetName: string): DateRange => {
    const presets = getPresets(t);
    const preset = presets.find(({ name }) => name === presetName);
    if (!preset) throw new Error(`Unknown date range preset: ${presetName}`);
    const from = new Date();
    const to = new Date();
    const first = from.getDate() - from.getDay();

    switch (preset.name) {
      case 'today':
        from.setHours(0, 0, 0, 0);
        to.setHours(23, 59, 59, 999);
        break;
      case 'yesterday':
        from.setDate(from.getDate() - 1);
        from.setHours(0, 0, 0, 0);
        to.setDate(to.getDate() - 1);
        to.setHours(23, 59, 59, 999);
        break;
      case 'last7':
        from.setDate(from.getDate() - 6);
        from.setHours(0, 0, 0, 0);
        to.setHours(23, 59, 59, 999);
        break;
      case 'last14':
        from.setDate(from.getDate() - 13);
        from.setHours(0, 0, 0, 0);
        to.setHours(23, 59, 59, 999);
        break;
      case 'last30':
        from.setDate(from.getDate() - 29);
        from.setHours(0, 0, 0, 0);
        to.setHours(23, 59, 59, 999);
        break;
      case 'thisWeek':
        from.setDate(first);
        from.setHours(0, 0, 0, 0);
        to.setHours(23, 59, 59, 999);
        break;
      case 'lastWeek':
        from.setDate(from.getDate() - 7 - from.getDay());
        to.setDate(to.getDate() - to.getDay() - 1);
        from.setHours(0, 0, 0, 0);
        to.setHours(23, 59, 59, 999);
        break;
      case 'thisMonth':
        from.setDate(1);
        from.setHours(0, 0, 0, 0);
        to.setHours(23, 59, 59, 999);
        break;
      case 'lastMonth':
        from.setMonth(from.getMonth() - 1);
        from.setDate(1);
        from.setHours(0, 0, 0, 0);
        to.setDate(0);
        to.setHours(23, 59, 59, 999);
        break;
    }

    return { from, to };
  };

  const setPreset = (preset: string): void => {
    const range = getPresetRange(preset);
    setRange(range);
    onValueChange?.(range);
    if (rangeCompare) {
      const rangeCompare = {
        from: new Date(
          range.from.getFullYear() - 1,
          range.from.getMonth(),
          range.from.getDate()
        ),
        to: range.to
          ? new Date(
              range.to.getFullYear() - 1,
              range.to.getMonth(),
              range.to.getDate()
            )
          : undefined
      };
      setRangeCompare(rangeCompare);
    }
  };

  const checkPreset = (): void => {
    const presets = getPresets(t);
    for (const preset of presets) {
      const presetRange = getPresetRange(preset.name);

      const normalizedRangeFrom = new Date(range.from);
      normalizedRangeFrom.setHours(0, 0, 0, 0);
      const normalizedPresetFrom = new Date(
        presetRange.from.setHours(0, 0, 0, 0)
      );

      const normalizedRangeTo = new Date(range.to ?? 0);
      normalizedRangeTo.setHours(0, 0, 0, 0);
      const normalizedPresetTo = new Date(
        presetRange.to?.setHours(0, 0, 0, 0) ?? 0
      );

      if (
        normalizedRangeFrom.getTime() === normalizedPresetFrom.getTime() &&
        normalizedRangeTo.getTime() === normalizedPresetTo.getTime()
      ) {
        setSelectedPreset(preset.name);
        return;
      }
    }

    setSelectedPreset(undefined);
  };

  const resetValues = (): void => {
    setRange({
      from:
        typeof initialDateFrom === 'string'
          ? getDateAdjustedForTimezone(initialDateFrom)
          : initialDateFrom,
      to: initialDateTo
        ? typeof initialDateTo === 'string'
          ? getDateAdjustedForTimezone(initialDateTo)
          : initialDateTo
        : typeof initialDateFrom === 'string'
          ? getDateAdjustedForTimezone(initialDateFrom)
          : initialDateFrom
    });
    setRangeCompare(
      initialCompareFrom
        ? {
            from:
              typeof initialCompareFrom === 'string'
                ? getDateAdjustedForTimezone(initialCompareFrom)
                : initialCompareFrom,
            to: initialCompareTo
              ? typeof initialCompareTo === 'string'
                ? getDateAdjustedForTimezone(initialCompareTo)
                : initialCompareTo
              : typeof initialCompareFrom === 'string'
                ? getDateAdjustedForTimezone(initialCompareFrom)
                : initialCompareFrom
          }
        : undefined
    );
  };

  useEffect(() => {
    checkPreset();
  }, [range]);

  // Sync range state with value prop
  useEffect(() => {
    if (value && (value.from !== range.from || value.to !== range.to)) {
      setRange(value);
    }
  }, [value]);

  const PresetButton = ({
    preset,
    label,
    isSelected
  }: {
    preset: string;
    label: string;
    isSelected: boolean;
  }): React.ReactNode => (
    <Button
      className={cn(isSelected && 'pointer-events-none')}
      variant='ghost'
      onClick={() => {
        setPreset(preset);
      }}
    >
      <>
        <span className={cn('pr-2 opacity-0', isSelected && 'opacity-70')}>
          <CheckIcon width={18} height={18} />
        </span>
        {label}
      </>
    </Button>
  );

  // Helper function to check if two date ranges are equal
  const areRangesEqual = (a?: DateRange, b?: DateRange): boolean => {
    if (!a || !b) return a === b; // If either is undefined, return true if both are undefined
    return (
      a.from.getTime() === b.from.getTime() &&
      (!a.to || !b.to || a.to.getTime() === b.to.getTime())
    );
  };

  useEffect(() => {
    if (isOpen) {
      openedRangeRef.current = range;
      openedRangeCompareRef.current = rangeCompare;
    }
  }, [isOpen]);

  return (
    <Popover
      modal={true}
      open={isOpen}
      onOpenChange={(open: boolean) => {
        if (!open) {
          resetValues();
        }
        setIsOpen(open);
      }}
    >
      <PopoverTrigger asChild className='w-auto'>
        <Button
          size={size}
          variant='outline'
          className={cn('flex items-center gap-4', className)}
        >
          <CalendarIcon className='mr-2' />
          <div className='text-right'>
            <div className='py-1'>
              <div>
                {range.from && range.to
                  ? `${format(range.from, 'P', { locale })} - ${format(range.to, 'P', { locale })}`
                  : placeholder ||
                    `${format(range.from, 'P', { locale })}${
                      range.to != null
                        ? ' - ' + format(range.to, 'P', { locale })
                        : ''
                    }`}
              </div>
            </div>
            {rangeCompare != null && (
              <div className='-mt-1 text-xs opacity-60'>
                <>
                  vs. {format(rangeCompare.from, 'P', { locale })}
                  {rangeCompare.to != null
                    ? ` - ${format(rangeCompare.to, 'P', { locale })}`
                    : ''}
                </>
              </div>
            )}
          </div>
          <div className='scale-125 duration-300'>
            {isOpen ? (
              <ChevronUpIcon width={24} />
            ) : (
              <ChevronDownIcon width={24} />
            )}
          </div>
        </Button>
      </PopoverTrigger>
      <PopoverContent align={align} className='w-auto'>
        <div className='flex py-2'>
          <div className='flex'>
            <div className='flex flex-col'>
              <div className='flex flex-col items-center justify-end gap-2 px-3 pb-4 lg:flex-row lg:items-start lg:pb-0'>
                {showCompare && (
                  <div className='flex items-center space-x-2 py-1 pr-4'>
                    <Switch
                      defaultChecked={Boolean(rangeCompare)}
                      onCheckedChange={(checked: boolean) => {
                        if (checked) {
                          if (!range.to) {
                            setRange({
                              from: range.from,
                              to: range.from
                            });
                          }
                          setRangeCompare({
                            from: new Date(
                              range.from.getFullYear(),
                              range.from.getMonth(),
                              range.from.getDate() - 365
                            ),
                            to: range.to
                              ? new Date(
                                  range.to.getFullYear() - 1,
                                  range.to.getMonth(),
                                  range.to.getDate()
                                )
                              : new Date(
                                  range.from.getFullYear() - 1,
                                  range.from.getMonth(),
                                  range.from.getDate()
                                )
                          });
                        } else {
                          setRangeCompare(undefined);
                        }
                      }}
                      id='compare-mode'
                    />
                    <Label htmlFor='compare-mode'>Compare</Label>
                  </div>
                )}
                {/* <div className='flex flex-col gap-2'>
                  <div className='flex gap-2'>
                    <DateInput
                      value={range.from}
                      onChange={(date) => {
                        const toDate =
                          range.to == null || date > range.to ? date : range.to;
                        setRange((prevRange) => ({
                          ...prevRange,
                          from: date,
                          to: toDate
                        }));
                      }}
                    />
                    <div className='py-1'>-</div>
                    <DateInput
                      value={range.to}
                      onChange={(date) => {
                        const fromDate = date < range.from ? date : range.from;
                        setRange((prevRange) => ({
                          ...prevRange,
                          from: fromDate,
                          to: date
                        }));
                      }}
                    />
                  </div>
                  {rangeCompare != null && (
                    <div className='flex gap-2'>
                      <DateInput
                        value={rangeCompare?.from}
                        onChange={(date) => {
                          if (rangeCompare) {
                            const compareToDate =
                              rangeCompare.to == null || date > rangeCompare.to
                                ? date
                                : rangeCompare.to;
                            setRangeCompare((prevRangeCompare) => ({
                              ...prevRangeCompare,
                              from: date,
                              to: compareToDate
                            }));
                          } else {
                            setRangeCompare({
                              from: date,
                              to: new Date()
                            });
                          }
                        }}
                      />
                      <div className='py-1'>-</div>
                      <DateInput
                        value={rangeCompare?.to}
                        onChange={(date) => {
                          if (rangeCompare && rangeCompare.from) {
                            const compareFromDate =
                              date < rangeCompare.from
                                ? date
                                : rangeCompare.from;
                            setRangeCompare({
                              ...rangeCompare,
                              from: compareFromDate,
                              to: date
                            });
                          }
                        }}
                      />
                    </div>
                  )}
                </div> */}
              </div>
              {isSmallScreen && (
                <Select
                  defaultValue={selectedPreset}
                  onValueChange={(value) => {
                    setPreset(value);
                  }}
                >
                  <SelectTrigger className='mx-auto mb-2 w-[180px]'>
                    <SelectValue placeholder='Select...' />
                  </SelectTrigger>
                  <SelectContent>
                    {getPresets(t).map((preset) => (
                      <SelectItem key={preset.name} value={preset.name}>
                        {preset.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <div>
                <Calendar
                  mode='range'
                  onSelect={(value: { from?: Date; to?: Date } | undefined) => {
                    if (value?.from != null) {
                      setRange({ from: value.from, to: value?.to });
                    }
                  }}
                  selected={range}
                  numberOfMonths={isSmallScreen ? 1 : 2}
                  defaultMonth={
                    new Date(
                      new Date().setMonth(
                        new Date().getMonth() - (isSmallScreen ? 0 : 1)
                      )
                    )
                  }
                  locale={locale}
                />
              </div>
            </div>
          </div>
          {!isSmallScreen && (
            <div className='flex flex-col items-end gap-1 pb-6 pl-6 pr-2'>
              <div className='flex w-full flex-col items-end gap-1 pb-6 pl-6 pr-2'>
                {getPresets(t).map((preset) => (
                  <PresetButton
                    key={preset.name}
                    preset={preset.name}
                    label={preset.label}
                    isSelected={selectedPreset === preset.name}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
        <div className='flex justify-end gap-2 py-2 pr-4'>
          {onClear && (
            <Button
              onClick={() => {
                setIsOpen(false);
                onClear();
              }}
              variant='ghost'
            >
              {t('clear')}
            </Button>
          )}
          {/* <Button
            onClick={() => {
              setIsOpen(false);
              resetValues();
            }}
            variant='ghost'
          >
            {t('cancel')}
          </Button> */}
          <Button
            onClick={() => {
              setIsOpen(false);
              if (
                !areRangesEqual(range, openedRangeRef.current) ||
                !areRangesEqual(rangeCompare, openedRangeCompareRef.current)
              ) {
                onUpdate?.({ range, rangeCompare });
                onValueChange?.(range);
              }
            }}
            variant='default'
          >
            {t('confirm')}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};

DateRangePicker.displayName = 'DateRangePicker';
DateRangePicker.filePath =
  'libs/shared/ui-kit/src/lib/date-range-picker/date-range-picker.tsx';
