'use client';

import { IconCamera, IconUpload, IconX } from '@tabler/icons-react';
import { useTranslations } from 'next-intl';
import * as React from 'react';
import Dropzone from 'react-dropzone';
import { toast } from 'sonner';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import { uploadMedia } from '@/features/core/services/upload-media';
import { cn } from '@/lib/utils';
import {
  ImageCrop,
  ImageCropContent,
  ImageCropApply,
  ImageCropReset
} from '@/components/ui/shadcn-io/image-crop';

export type ImageDropInputType = 'avatar' | 'default';

interface ImageDropInputProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  type?: ImageDropInputType;
  value?: string;
  onChange?: (url: string) => void;
  directory?: string;
  maxSize?: number;
  disabled?: boolean;
  placeholder?: string;
  aspectRatio?: number;
  enableCrop?: boolean;
}

export function ImageDropInput({
  type = 'default',
  value,
  onChange,
  directory = 'images',
  maxSize = 1024 * 1024 * 5,
  disabled = false,
  placeholder,
  aspectRatio = 1,
  enableCrop = true,
  className,
  ...props
}: ImageDropInputProps) {
  const t = useTranslations('common');
  const [uploading, setUploading] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const [cropDialogOpen, setCropDialogOpen] = React.useState(false);
  const [currentFile, setCurrentFile] = React.useState<File | null>(null);
  const [croppedImageUrl, setCroppedImageUrl] = React.useState<string>('');

  const dataURLtoFile = (dataURL: string, filename: string): File => {
    const arr = dataURL.split(',');
    const mime = arr[0].match(/:(.*?);/)?.[1] || 'image/png';
    const bstr = atob(arr[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n);
    }
    const blob = new Blob([u8arr], { type: mime });
    return new File([blob], filename, { type: mime, lastModified: Date.now() });
  };

  const handleCropComplete = (croppedImage: string) => {
    setCroppedImageUrl(croppedImage);
  };

  const handleCropApply = React.useCallback(async () => {
    if (!currentFile) return;

    setCropDialogOpen(false);
    setCurrentFile(null);
    setCroppedImageUrl('');
  }, [currentFile]);

  const handleImageCropApply = React.useCallback(
    async (croppedImage: string) => {
      if (!currentFile) return;

      const croppedFile = dataURLtoFile(croppedImage, currentFile.name);

      setCropDialogOpen(false);
      setCurrentFile(null);
      setCroppedImageUrl('');

      // Upload the cropped file to S3
      await uploadFile(croppedFile);
    },
    [currentFile]
  );

  const uploadFile = async (file: File) => {
    setUploading(true);
    setProgress(0);

    try {
      setProgress(20);
      const response = await uploadMedia([file], directory);
      setProgress(100);

      const uploadedUrl = response[0];
      onChange?.(uploadedUrl);

      toast.success(t('uploadSuccess', { target: t('file') }));
    } catch (error) {
      toast.error(t('uploadFailed', { target: t('file') }));
    } finally {
      setUploading(false);
      setTimeout(() => setProgress(0), 500);
    }
  };

  const handleUpload = async (files: File[]) => {
    if (disabled) return;

    const file = files[0];

    if (file.size > maxSize) {
      toast.error(
        t('fileTooLarge', {
          maxSize: Math.round(maxSize / 1024 / 1024),
          files: file.name
        })
      );
      return;
    }

    if (enableCrop && file.type.startsWith('image/')) {
      setCurrentFile(file);
      setCropDialogOpen(true);
    } else {
      await uploadFile(file);
    }
  };

  const handleRemove = () => {
    if (disabled) return;
    onChange?.('');
  };

  const handleDropRejected = (rejectedFiles: any[]) => {
    const errors: string[] = [];

    rejectedFiles.forEach(({ errors: fileErrors, file }) => {
      fileErrors.forEach((error: any) => {
        switch (error.code) {
          case 'file-invalid-type':
            errors.push(t('invalidFileType', { files: file.name }));
            break;
          default:
            errors.push(t('uploadError', { files: file.name }));
        }
      });
    });

    if (errors.length > 0) {
      toast.error(errors[0]);
    }
  };

  if (type === 'avatar') {
    return (
      <>
        <div
          className={cn(
            'flex flex-col items-start justify-center gap-4',
            className
          )}
          {...props}
        >
          <div className='relative'>
            <Dropzone
              onDrop={handleUpload}
              onDropRejected={handleDropRejected}
              accept={{ 'image/*': [] }}
              multiple={false}
              disabled={disabled || uploading}
            >
              {({ getRootProps, getInputProps }) => (
                <div
                  {...getRootProps()}
                  className={cn(
                    'relative cursor-pointer rounded-full',
                    (disabled || uploading) && 'pointer-events-none opacity-60'
                  )}
                >
                  <input {...getInputProps()} />
                  <Avatar className='size-24'>
                    <AvatarImage src={value} alt='Avatar' />
                    <AvatarFallback className='text-lg'>
                      {placeholder || <IconCamera className='size-4' />}
                    </AvatarFallback>
                  </Avatar>

                  {!value && (
                    <div className='absolute inset-0 flex items-center justify-center rounded-full bg-black/20 opacity-0 transition-opacity hover:opacity-100'>
                      <IconUpload className='size-6 text-white' />
                    </div>
                  )}
                </div>
              )}
            </Dropzone>

            {value && !disabled && (
              <Button
                type='button'
                variant='destructive'
                size='icon'
                className='absolute -right-2 -top-2 size-6 rounded-full'
                onClick={handleRemove}
              >
                <IconX className='size-3' />
              </Button>
            )}
          </div>
        </div>

        {currentFile && (
          <Dialog open={cropDialogOpen} onOpenChange={setCropDialogOpen}>
            <DialogContent className='!z-[100] max-w-2xl' zIndex={100}>
              <DialogHeader>
                <DialogTitle>{t('cropImage')}</DialogTitle>
                <DialogDescription>
                  {t('cropImageDescription')}
                </DialogDescription>
              </DialogHeader>
              <ImageCrop
                file={currentFile}
                aspect={aspectRatio}
                onCrop={handleImageCropApply}
                // circularCrop={type === 'avatar'}
              >
                <div className='py-4'>
                  <ImageCropContent />
                </div>
                <DialogFooter className='flex flex-col gap-2 sm:flex-row sm:justify-end'>
                  <ImageCropReset asChild>
                    <Button type='button' variant='outline' size='sm'>
                      {t('reset')}
                    </Button>
                  </ImageCropReset>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    onClick={() => {
                      setCropDialogOpen(false);
                      setCurrentFile(null);
                      setCroppedImageUrl('');
                    }}
                  >
                    {t('cancel')}
                  </Button>
                  <ImageCropApply className='w-full sm:w-auto'>
                    <Button type='button' variant='default' size='sm'>
                      {t('applyCrop')}
                    </Button>
                  </ImageCropApply>
                </DialogFooter>
              </ImageCrop>
            </DialogContent>
          </Dialog>
        )}
      </>
    );
  }

  return (
    <>
      <div className={cn('space-y-4', className)} {...props}>
        {!value && (
          <Dropzone
            onDrop={handleUpload}
            onDropRejected={handleDropRejected}
            accept={{ 'image/*': [] }}
            multiple={false}
            disabled={disabled || uploading}
          >
            {({ getRootProps, getInputProps }) => (
              <div
                {...getRootProps()}
                className={cn(
                  'group relative grid h-32 w-full cursor-pointer place-items-center rounded-lg border-2 border-dashed border-muted-foreground/25 px-5 py-2.5 text-center transition hover:bg-muted/25',
                  'focus-visible:outline-hidden ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                  (disabled || uploading) && 'pointer-events-none opacity-60'
                )}
              >
                <input {...getInputProps()} />
                <div className='flex flex-col items-center justify-center gap-2'>
                  <div className='rounded-full border border-dashed p-2'>
                    <IconUpload className='size-5 text-muted-foreground' />
                  </div>
                  <div className='space-y-1'>
                    <p className='text-sm font-medium text-muted-foreground'>
                      {uploading ? t('uploading') : t('dropImagesHere')}
                    </p>
                    <p className='text-xs text-muted-foreground/70'>
                      {t('maxFile')} ({Math.round(maxSize / 1024 / 1024)}MB)
                    </p>
                  </div>
                </div>
              </div>
            )}
          </Dropzone>
        )}

        {value && (
          <div className='w-full'>
            <div className='group relative w-full max-w-40'>
              <div className='relative aspect-video overflow-hidden rounded-lg border'>
                <img
                  src={value}
                  alt='Uploaded image'
                  className='h-full w-full object-contain'
                />
                {progress > 0 && progress < 100 && (
                  <div className='absolute inset-0 flex items-center justify-center bg-black/50'>
                    <Progress value={progress} className='w-16' />
                  </div>
                )}
              </div>

              {!disabled && (
                <div className='absolute -right-2 -top-2 flex gap-1'>
                  <Dropzone
                    onDrop={handleUpload}
                    onDropRejected={handleDropRejected}
                    accept={{ 'image/*': [] }}
                    multiple={false}
                    disabled={disabled || uploading}
                  >
                    {({ getRootProps, getInputProps }) => (
                      <Button
                        type='button'
                        variant='secondary'
                        size='icon'
                        className='size-6 rounded-full'
                        {...getRootProps()}
                      >
                        <input {...getInputProps()} />
                        <IconUpload className='size-3' />
                      </Button>
                    )}
                  </Dropzone>
                  <Button
                    type='button'
                    variant='destructive'
                    size='icon'
                    className='size-6 rounded-full'
                    onClick={handleRemove}
                  >
                    <IconX className='size-3' />
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {currentFile && (
        <Dialog open={cropDialogOpen} onOpenChange={setCropDialogOpen}>
          <DialogContent className='!z-[100] max-w-2xl' zIndex={100}>
            <DialogHeader>
              <DialogTitle>{t('cropImage')}</DialogTitle>
              <DialogDescription>{t('cropImageDescription')}</DialogDescription>
            </DialogHeader>
            <ImageCrop
              file={currentFile}
              aspect={aspectRatio}
              onCrop={handleImageCropApply}
            >
              <div className='py-4'>
                <ImageCropContent />
              </div>
              <DialogFooter className='flex gap-2'>
                <ImageCropReset asChild>
                  <Button type='button' variant='outline' size='sm'>
                    {t('reset')}
                  </Button>
                </ImageCropReset>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => {
                    setCropDialogOpen(false);
                    setCurrentFile(null);
                    setCroppedImageUrl('');
                  }}
                >
                  {t('cancel')}
                </Button>
                <ImageCropApply className='w-full sm:w-auto'>
                  <Button type='button' variant='default' size='sm'>
                    {t('applyCrop')}
                  </Button>
                </ImageCropApply>
              </DialogFooter>
            </ImageCrop>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
