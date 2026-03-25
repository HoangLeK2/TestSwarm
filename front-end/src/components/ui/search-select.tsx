'use client';

import { Input } from './input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from './select';
import { cn } from '@/lib/utils';

export interface SearchSelectOption {
  value: string;
  label: string;
}

interface SearchSelectProps<T extends string = string> {
  searchType: T;
  onSearchTypeChange: (value: T) => void;
  query: string;
  onQueryChange: (value: string) => void;
  options: SearchSelectOption[];
  placeholder?: string;
  selectClassName?: string;
  inputClassName?: string;
  className?: string;
}

export function SearchSelect<T extends string = string>({
  searchType,
  onSearchTypeChange,
  query,
  onQueryChange,
  options,
  placeholder,
  selectClassName,
  inputClassName,
  className
}: SearchSelectProps<T>) {
  return (
    <div className={cn('flex sm:flex-row sm:items-end', className)}>
      <Select value={searchType} onValueChange={onSearchTypeChange}>
        <SelectTrigger
          className={cn(
            'min-w-[150px] rounded rounded-r-none',
            selectClassName
          )}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        placeholder={placeholder}
        className={cn(
          'w-full min-w-[300px] rounded-l-none border-l-0',
          inputClassName
        )}
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
      />
    </div>
  );
}
