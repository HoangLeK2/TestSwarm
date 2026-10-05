'use client';

import { useId } from 'react';
import { useTranslations } from 'next-intl';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  CAPTURE_MODES,
  readCaptureMode,
  writeCaptureMode,
  type CaptureMode
} from '../lib/campaign-editor-variables';

export function CaptureModeSettings({
  variables,
  onChange,
  disabled = false
}: {
  variables: Record<string, unknown>;
  onChange: (variables: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const t = useTranslations('campaignsFeature.captureModeSettings');
  const id = useId();
  const mode = readCaptureMode(variables);

  return (
    <div className='space-y-2'>
      <Label htmlFor={`${id}-capture-mode`}>{t('label')}</Label>
      <Select
        value={mode}
        onValueChange={(next) =>
          onChange(writeCaptureMode(variables, next as CaptureMode))
        }
        disabled={disabled}
      >
        <SelectTrigger id={`${id}-capture-mode`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {CAPTURE_MODES.map((value) => (
            <SelectItem key={value} value={value}>
              {t(`options.${value}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className='text-[11px] text-muted-foreground'>{t('hint')}</p>
    </div>
  );
}
