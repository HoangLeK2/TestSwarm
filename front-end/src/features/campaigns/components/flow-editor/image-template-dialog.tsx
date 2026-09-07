'use client';

/**
 * Crop a region of a device screen to use as a tap_image template.
 *
 * The frame comes from the mirror that is already on screen (canvas/video
 * pixels), not from a backend screenshot call — since media moved to go2rtc the
 * backend has no frame of its own to hand back. Where no mirror exists (the
 * campaign scenario editor), `allowFilePick` lets the user hand in a screenshot
 * from disk instead.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import {
  AlertTriangle,
  Crop as CropIcon,
  Image as ImageIcon,
  Loader2
} from 'lucide-react';

import {
  ImageCrop,
  ImageCropApply,
  ImageCropContent,
  ImageCropReset
} from '@/components/ui/shadcn-io/image-crop';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { orgScenariosApi } from '@/features/org-scenarios/services/api';

export type ImageTemplatePick = {
  templateKey: string;
  screenW?: number;
  screenH?: number;
  /** Data URL of the crop, so the node can show a thumbnail without a fetch. */
  preview: string;
  warning: string;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scenarioId: string;
  /** Full-frame PNG data URL captured from the mirror, or null when unavailable. */
  frameDataUrl: string | null;
  onPicked: (pick: ImageTemplatePick) => void;
  /**
   * Let the user supply the source image themselves. Needed outside the device
   * control view — the campaign editor has no mirror to capture, so a
   * screenshot from disk (or the template already stored) is the only source.
   */
  allowFilePick?: boolean;
  copyScope?: 'tapImage' | 'verifyScreen';
};

function dataUrlToFile(dataUrl: string, name: string): File {
  const [meta, b64] = dataUrl.split(',');
  const mime = /:(.*?);/.exec(meta ?? '')?.[1] ?? 'image/png';
  const bin = atob(b64 ?? '');
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new File([bytes], name, { type: mime });
}

export function ImageTemplateDialog({
  open,
  onOpenChange,
  scenarioId,
  frameDataUrl,
  onPicked,
  allowFilePick = false,
  copyScope = 'tapImage'
}: Props) {
  const t = useTranslations(`campaignsFeature.stepEditor.${copyScope}`);
  const [cropped, setCropped] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [frameSize, setFrameSize] = useState<{ w: number; h: number } | null>(
    null
  );
  const [pickedFile, setPickedFile] = useState<File | null>(null);

  // Decoding is ~1.5MB of atob per call for a full device frame. Without memo
  // this reran on every render (each crop drag fires setCropped) and handed
  // ImageCrop a new File identity, which resets the selection mid-drag.
  const frameFile = useMemo(
    () => (frameDataUrl ? dataUrlToFile(frameDataUrl, 'frame.png') : null),
    [frameDataUrl]
  );
  // A file the user chose wins over the mirror frame: they picked it after
  // seeing the frame, so it is the more recent intent.
  const sourceFile = pickedFile ?? frameFile;

  useEffect(() => {
    if (!open) {
      setCropped(null);
      setError('');
      setSaving(false);
      setPickedFile(null);
      return;
    }
  }, [open]);

  useEffect(() => {
    if (!open || !sourceFile) return;
    // Template matching corrects for a different device resolution at run time,
    // but only if it knows the width the crop was taken at.
    const url = URL.createObjectURL(sourceFile);
    const img = new Image();
    img.onload = () =>
      setFrameSize({ w: img.naturalWidth, h: img.naturalHeight });
    img.onerror = () => setFrameSize(null);
    img.src = url;
    return () => URL.revokeObjectURL(url);
  }, [open, sourceFile]);

  const handleSave = async () => {
    if (!cropped) return;
    setSaving(true);
    setError('');
    try {
      const file = dataUrlToFile(cropped, 'template.png');
      const out = await orgScenariosApi.uploadImageTemplate(scenarioId, file, {
        w: frameSize?.w,
        h: frameSize?.h
      });
      onPicked({
        templateKey: out.template_key,
        screenW: out.screen_w ?? frameSize?.w,
        screenH: out.screen_h ?? frameSize?.h,
        preview: cropped,
        warning: out.warning
      });
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : t('saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{t('dialogTitle')}</DialogTitle>
          <DialogDescription>{t('dialogDescription')}</DialogDescription>
        </DialogHeader>

        {allowFilePick && (
          <label className='flex cursor-pointer items-center gap-2 rounded-md border border-dashed p-3 text-xs'>
            <ImageIcon className='size-4 shrink-0 text-muted-foreground' />
            <span className='text-muted-foreground'>
              {sourceFile ? t('pickAnotherFile') : t('pickFile')}
            </span>
            <input
              type='file'
              accept='image/*'
              className='sr-only'
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setCropped(null);
                setPickedFile(file);
                // Same file twice in a row still fires onChange.
                e.target.value = '';
              }}
            />
          </label>
        )}

        {!sourceFile ? (
          <div className='py-10 text-center text-sm text-muted-foreground'>
            {allowFilePick ? t('noSource') : t('noMirrorFrame')}
          </div>
        ) : (
          <ImageCrop file={sourceFile} onCrop={setCropped}>
            <div className='flex flex-col items-center gap-3'>
              <ImageCropContent className='max-h-[420px]' />
              <div className='flex items-center gap-2'>
                <ImageCropApply asChild>
                  <Button size='sm' variant='secondary'>
                    <CropIcon className='mr-1 size-4' />
                    {t('applyCrop')}
                  </Button>
                </ImageCropApply>
                <ImageCropReset asChild>
                  <Button size='sm' variant='ghost'>
                    {t('resetCrop')}
                  </Button>
                </ImageCropReset>
              </div>
            </div>
          </ImageCrop>
        )}

        {cropped && (
          <div className='flex items-center gap-3 rounded-md border p-3'>
            {/* eslint-disable-next-line @next/next/no-img-element -- local data URL, no loader needed */}
            <img
              src={cropped}
              alt={t('croppedAlt')}
              className='max-h-24 rounded border'
            />
            <span className='text-xs text-muted-foreground'>
              {t('croppedHint')}
            </span>
          </div>
        )}

        {error && (
          <p className='flex items-center gap-2 text-sm text-destructive'>
            <AlertTriangle className='size-4' />
            {error}
          </p>
        )}

        <DialogFooter>
          <Button variant='ghost' onClick={() => onOpenChange(false)}>
            {t('cancel')}
          </Button>
          <Button onClick={handleSave} disabled={!cropped || saving}>
            {saving && <Loader2 className='mr-1 size-4 animate-spin' />}
            {t('useImage')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
