'use client';

import { useTranslations } from 'next-intl';
import { usePlatformCapabilities } from '../../hooks/use-platform-capabilities';
import { F } from './step-panel-primitives';

type Option = {
  value: string;
  label: string;
  supported: boolean;
  coverage: string;
};

type Props = {
  /** Current value; falls back to facebook, matching the backend default. */
  value?: string;
  onChange: (platform: string) => void;
  /** Step type to check support against — omit when checking an entity instead. */
  stepType?: string;
  /** Extract entity to check support against. */
  entity?: string;
  label?: string;
};

/**
 * Platform picker for a platform-neutral node.
 *
 * Platforms that do not implement the step are listed but disabled: the user
 * can see the node is meant to work everywhere without being able to pick a
 * combination that would fail at runtime.
 */
export function PlatformSelect({
  value,
  onChange,
  stepType,
  entity,
  label
}: Props) {
  const t = useTranslations('campaignsFeature.stepEditor.platformSelect');
  const { optionsForStep, optionsForEntity, isLoading, isError } =
    usePlatformCapabilities();

  const options: Option[] = entity
    ? optionsForEntity(entity)
    : stepType
      ? optionsForStep(stepType)
      : [];

  const current = value ?? 'facebook';
  const supported = options.filter((o) => o.supported);

  // Never hide the current value, even if the backend stopped supporting it —
  // otherwise editing an old scenario would silently rewrite its platform.
  const hasCurrent = options.some((o) => o.value === current);

  return (
    <F label={label ?? t('label')}>
      <select
        className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
        value={current}
        disabled={isLoading || isError}
        onChange={(e) => onChange(e.target.value)}
      >
        {!hasCurrent && <option value={current}>{current}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={!o.supported}>
            {o.label}
            {o.supported ? '' : t('unsupportedSuffix')}
          </option>
        ))}
      </select>
      {isError && (
        <p className='mt-1 text-[11px] text-muted-foreground'>
          {t('loadError', { platform: current })}
        </p>
      )}
      {!isLoading && !isError && supported.length === 1 && (
        <p className='mt-1 text-[11px] text-muted-foreground'>
          {t('onlySupported', { platform: supported[0].label })}
        </p>
      )}
    </F>
  );
}
