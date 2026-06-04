'use client';

import { useTranslations } from 'next-intl';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { cn } from '@/lib/utils';

export type ImportResolveMode = 'reject' | 'create_stub';

export function ImportResolveModeField({
  value,
  onChange,
  disabled
}: {
  value: ImportResolveMode;
  onChange: (value: ImportResolveMode) => void;
  disabled?: boolean;
}) {
  const t = useTranslations('orgScenariosFeature.importDialog');

  const options: {
    value: ImportResolveMode;
    title: string;
    description: string;
    recommended?: boolean;
  }[] = [
    {
      value: 'create_stub',
      title: t('resolveCreateStubTitle'),
      description: t('resolveCreateStubDesc'),
      recommended: true
    },
    {
      value: 'reject',
      title: t('resolveRejectTitle'),
      description: t('resolveRejectDesc')
    }
  ];

  return (
    <div className='space-y-3 rounded-lg border bg-muted/30 p-3'>
      <div className='space-y-1'>
        <p className='text-sm font-medium text-foreground'>
          {t('resolveSectionTitle')}
        </p>
        <p className='text-xs leading-relaxed text-muted-foreground'>
          {t('resolveSectionIntro')}
        </p>
      </div>
      <RadioGroup
        value={value}
        disabled={disabled}
        onValueChange={(next) => onChange(next as ImportResolveMode)}
        className='gap-2'
      >
        {options.map((option) => (
          <Label
            key={option.value}
            htmlFor={`import-resolve-${option.value}`}
            className={cn(
              'flex cursor-pointer gap-3 rounded-md border bg-background p-3 transition-colors',
              'hover:bg-muted/40',
              value === option.value && 'border-primary ring-1 ring-primary/30',
              disabled && 'cursor-not-allowed opacity-60'
            )}
          >
            <RadioGroupItem
              id={`import-resolve-${option.value}`}
              value={option.value}
              className='mt-0.5'
            />
            <span className='min-w-0 flex-1 space-y-1'>
              <span className='flex flex-wrap items-center gap-2 text-sm font-medium'>
                {option.title}
                {option.recommended ? (
                  <span className='rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-normal text-primary'>
                    {t('resolveRecommended')}
                  </span>
                ) : null}
              </span>
              <span className='block text-xs leading-relaxed text-muted-foreground'>
                {option.description}
              </span>
            </span>
          </Label>
        ))}
      </RadioGroup>
    </div>
  );
}
