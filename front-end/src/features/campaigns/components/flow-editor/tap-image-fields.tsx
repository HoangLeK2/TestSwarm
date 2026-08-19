'use client';

/** Editor fields for a tap_image step: the cropped template plus match tuning. */
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

export function TapImageFields({
  step,
  update,
  onRequestCropImage: cropFromProp
}: Props) {
  const t = useTranslations('campaignsFeature.stepEditor.tapImage');
  const { scenarioId, requestCropImage: cropFromContext } =
    useImageTemplateScenario();
  // Prop first so the graph detail panel keeps its explicit wiring; the context
  // covers the step-list editor, which has no prop path down to here.
  const onRequestCropImage = cropFromProp ?? cropFromContext;
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string>('');
  const [warning, setWarning] = useState<string>('');
  const [localCropOpen, setLocalCropOpen] = useState(false);

  const templateKey = step.template_key as string | undefined;
  const hasTemplate = Boolean(templateKey);

  // The crop preview is a data URL that only exists in the render right after
  // cropping. Reopening the step has to read the template back from object
  // storage, otherwise an attached template shows as a blank panel.
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
      template_screen_h: picked.screenH
    });
    // Re-cropping can reuse a key seen earlier in this session (the backend
    // addresses templates by content hash); drop any stale entry so the cards
    // repoint at the new object.
    if (scenarioId) forgetImageTemplateUrl(scenarioId, picked.templateKey);
    setPreview(picked.preview);
    setWarning(picked.warning);
  };

  const handleCrop = async () => {
    // Without a live mirror there is no frame to grab, so fall back to the
    // in-place dialog where the user supplies the screenshot themselves.
    if (!onRequestCropImage) {
      setLocalCropOpen(true);
      return;
    }
    setBusy(true);
    try {
      const picked = await onRequestCropImage();
      if (!picked) return;
      applyPick(picked);
    } finally {
      setBusy(false);
    }
  };

  // Never hide this button. An image step without a template is broken, and a
  // control that silently disappears reads as a missing feature — say what is
  // blocking instead.
  const canCrop = Boolean(onRequestCropImage) || Boolean(scenarioId);
  const shownImage = preview || storedUrl;

  return (
    <div className='space-y-2'>
      <Button
        size='sm'
        variant='outline'
        className='h-7 w-full gap-1.5 border-sky-400/50 text-[10px] text-sky-800 hover:bg-sky-50 dark:text-sky-300 dark:hover:bg-sky-950/30'
        onClick={handleCrop}
        disabled={busy || !canCrop}
        title={canCrop ? undefined : t('noScenarioTitle')}
      >
        {busy ? (
          <Loader2 size={12} className='animate-spin' />
        ) : (
          <CropIcon size={12} />
        )}
        {hasTemplate
          ? t('cropAgain')
          : onRequestCropImage
            ? t('cropFromScreen')
            : t('cropFromFile')}
      </Button>

      {!canCrop && (
        <p className='text-[10px] text-muted-foreground'>
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
          onPicked={applyPick}
        />
      )}

      {shownImage && (
        // eslint-disable-next-line @next/next/no-img-element -- data URL / presigned object-storage URL
        <img
          src={shownImage}
          alt={t('imageAlt')}
          className='max-h-28 rounded border object-contain'
          onError={() => {
            if (!preview) forgetStoredUrl();
          }}
        />
      )}

      {hasTemplate && !shownImage && storedFailed && (
        <p className='text-[10px] text-muted-foreground'>{t('loadFailed')}</p>
      )}

      {warning && (
        <p className='flex items-start gap-1.5 rounded border border-amber-400/50 bg-amber-50 p-2 text-[10px] text-amber-800 dark:bg-amber-950/30 dark:text-amber-300'>
          <AlertTriangle size={12} className='mt-0.5 shrink-0' />
          {warning}
        </p>
      )}

      {!hasTemplate && (
        <p className='text-[10px] text-destructive'>{t('missing')}</p>
      )}

      <Field label={t('threshold')} hint={t('thresholdHint')}>
        <Input
          type='number'
          min={0}
          max={1}
          step={0.05}
          className='h-8 text-xs'
          value={step.threshold ?? 0.8}
          onChange={(e) =>
            update({ threshold: parseFloat(e.target.value) || 0.8 })
          }
        />
      </Field>

      <div className='grid grid-cols-2 gap-2'>
        <Field label={t('timeout')}>
          <Input
            type='number'
            min={0.1}
            max={60}
            step={0.5}
            className='h-8 text-xs'
            value={step.timeout ?? 8}
            onChange={(e) =>
              update({ timeout: parseFloat(e.target.value) || 8 })
            }
          />
        </Field>
        <Field label={t('poll')}>
          <Input
            type='number'
            min={0.1}
            max={10}
            step={0.1}
            className='h-8 text-xs'
            value={step.poll ?? 0.5}
            onChange={(e) =>
              update({ poll: parseFloat(e.target.value) || 0.5 })
            }
          />
        </Field>
      </div>

      <Field label={t('scale')} hint={t('scaleHint')}>
        <Input
          type='number'
          min={0.05}
          max={1}
          step={0.05}
          className='h-8 text-xs'
          value={step.scale ?? 0.25}
          onChange={(e) =>
            update({ scale: parseFloat(e.target.value) || 0.25 })
          }
        />
      </Field>
    </div>
  );
}
