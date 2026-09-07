'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { AlertTriangle, Crop as CropIcon, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { FlowStep } from '../scenario-steps/types';
import { ImageTemplateDialog } from './image-template-dialog';
import {
  forgetImageTemplateUrl,
  useImageTemplateScenario,
  useImageTemplateUrl
} from './image-template-scenario';

type Props = {
  step: FlowStep;
  update: (patch: Record<string, unknown>) => void;
  onRequestCropImage?: () => Promise<{
    templateKey: string;
    screenW?: number;
    screenH?: number;
    preview: string;
    warning: string;
  } | null>;
};

function Field({
  label,
  hint,
  children
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className='block space-y-1'>
      <span className='text-[10px] font-medium text-muted-foreground'>
        {label}
      </span>
      {children}
      {hint && (
        <span className='block text-[10px] text-muted-foreground'>{hint}</span>
      )}
    </label>
  );
}

export function VerifyScreenFields({
  step,
  update,
  onRequestCropImage: cropFromProp
}: Props) {
  const t = useTranslations('campaignsFeature.stepEditor.verifyScreen');
  const { scenarioId, requestCropImage: cropFromContext } =
    useImageTemplateScenario();
  const onRequestCropImage = cropFromProp ?? cropFromContext;
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string>('');
  const [warning, setWarning] = useState<string>('');
  const [localCropOpen, setLocalCropOpen] = useState(false);

  const templateKey = step.template_key as string | undefined;
  const hasTemplate = Boolean(templateKey);
  const hasLegacyScreenshot = Boolean(String(step.screenshot ?? '').trim());
  const {
    url: storedUrl,
    failed: storedFailed,
    forget: forgetStoredUrl
  } = useImageTemplateUrl(templateKey);

  const applyPick = (picked: {
    templateKey: string;
    screenW?: number;
    screenH?: number;
    preview: string;
    warning: string;
  }) => {
    update({
      template_key: picked.templateKey,
      template_screen_w: picked.screenW,
      template_screen_h: picked.screenH,
      screenshot: undefined
    });
    if (scenarioId) forgetImageTemplateUrl(scenarioId, picked.templateKey);
    setPreview(picked.preview);
    setWarning(picked.warning);
  };

  const handleCrop = async () => {
    if (!onRequestCropImage) {
      setLocalCropOpen(true);
      return;
    }
    setBusy(true);
    try {
      const picked = await onRequestCropImage();
      if (picked) applyPick(picked);
    } finally {
      setBusy(false);
    }
  };

  const canCrop = Boolean(onRequestCropImage) || Boolean(scenarioId);
  const shownImage = preview || storedUrl;

  return (
    <div className='space-y-3'>
      <div className='rounded-md border bg-muted/20 p-2.5'>
        <div className='flex items-center justify-between gap-2'>
          <div className='min-w-0'>
            <p className='text-xs font-medium text-foreground'>
              {t('referenceImage')}
            </p>
            <p className='mt-0.5 text-[11px] leading-relaxed text-muted-foreground'>
              {t('referenceHint')}
            </p>
          </div>
          <Button
            type='button'
            size='sm'
            variant='outline'
            className='h-8 shrink-0 gap-1.5 border-sky-400/50 text-[11px] text-sky-800 hover:bg-sky-50 dark:text-sky-300 dark:hover:bg-sky-950/30'
            onClick={handleCrop}
            disabled={busy || !canCrop}
            title={canCrop ? undefined : t('noScenarioTitle')}
          >
            {busy ? (
              <Loader2 className='size-3 animate-spin' />
            ) : (
              <CropIcon className='size-3' />
            )}
            {hasTemplate || hasLegacyScreenshot
              ? t('cropAgain')
              : onRequestCropImage
                ? t('cropFromScreen')
                : t('cropFromFile')}
          </Button>
        </div>

        {!canCrop && (
          <p className='mt-2 text-[10px] text-muted-foreground'>
            {t('noScenarioHint')}
          </p>
        )}

        {!onRequestCropImage && scenarioId && (
          <ImageTemplateDialog
            open={localCropOpen}
            onOpenChange={setLocalCropOpen}
            scenarioId={scenarioId}
            frameDataUrl={null}
            allowFilePick
            copyScope='verifyScreen'
            onPicked={applyPick}
          />
        )}

        {shownImage && (
          // eslint-disable-next-line @next/next/no-img-element -- data URL / presigned object-storage URL
          <img
            src={shownImage}
            alt={t('imageAlt')}
            className='mt-2 max-h-32 rounded border object-contain'
            onError={() => {
              if (!preview) forgetStoredUrl();
            }}
          />
        )}

        {hasTemplate && !shownImage && storedFailed && (
          <p className='mt-2 text-[10px] text-muted-foreground'>
            {t('loadFailed')}
          </p>
        )}

        {!hasTemplate && !hasLegacyScreenshot && (
          <p className='mt-2 text-[10px] text-destructive'>{t('missing')}</p>
        )}

        {hasLegacyScreenshot && !hasTemplate && (
          <p className='mt-2 rounded border border-amber-400/50 bg-amber-50 p-2 text-[10px] text-amber-800 dark:bg-amber-950/30 dark:text-amber-300'>
            {t('legacyScreenshotHint')}
          </p>
        )}

        {warning && (
          <p className='mt-2 flex items-start gap-1.5 rounded border border-amber-400/50 bg-amber-50 p-2 text-[10px] text-amber-800 dark:bg-amber-950/30 dark:text-amber-300'>
            <AlertTriangle className='mt-0.5 size-3 shrink-0' />
            {warning}
          </p>
        )}
      </div>

      <div className='grid grid-cols-3 gap-2'>
        <Field label={t('ssimThreshold')} hint={t('ssimThresholdHint')}>
          <Input
            type='number'
            min={0}
            max={1}
            step={0.01}
            className='h-8 text-xs'
            value={step.ssim_threshold ?? 0.75}
            onChange={(e) =>
              update({ ssim_threshold: Number(e.target.value) || 0.75 })
            }
          />
        </Field>
        <Field label={t('timeout')}>
          <Input
            type='number'
            min={0.1}
            step={0.1}
            className='h-8 text-xs'
            value={step.timeout ?? 8}
            onChange={(e) =>
              update({ timeout: Math.max(0.1, Number(e.target.value) || 0.1) })
            }
          />
        </Field>
        <Field label={t('poll')}>
          <Input
            type='number'
            min={0.1}
            step={0.1}
            className='h-8 text-xs'
            value={step.poll ?? 0.5}
            onChange={(e) =>
              update({ poll: Math.max(0.1, Number(e.target.value) || 0.1) })
            }
          />
        </Field>
      </div>
    </div>
  );
}
