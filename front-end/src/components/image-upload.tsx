'use client';

import { IconCamera, IconUpload, IconX } from '@tabler/icons-react';
import { useTranslations } from 'next-intl';
import * as React from 'react';
import Dropzone from 'react-dropzone';
import { toast } from 'sonner';

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { uploadMedia } from '@/features/core/services/upload-media';
import { cn } from '@/lib/utils';

export type ImageUploadType = 'avatar' | 'default';
export type ImageUploadMode = 'single' | 'multiple';

interface ImageUploadProps<T extends ImageUploadMode = ImageUploadMode>
  extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  /**
   * Type of image upload - affects the visual display
   * @type ImageUploadType
   * @default 'default'
   */
  type?: ImageUploadType;

  /**
   * Upload mode - single or multiple files
   * @type T
   * @default 'single'
   */
  mode?: T;

  /**
   * Current value - string for single mode, string[] for multiple mode
   * @type T extends 'single' ? string : string[]
   * @default undefined
   */
  value?: T extends 'single' ? string : string[];

  /**
   * Callback when upload is complete and URLs are ready
   * @type (urls: T extends 'single' ? string : string[]) => void
   * @default undefined
   */
  onChange?: (
    urls: T extends 'single' ? string | File : string[] | File[]
  ) => void;

  /**
   * Directory for upload
   * @type string
   * @default 'images'
   */
  directory?: string;

  /**
   * Maximum file size in bytes
   * @type number
   * @default 1024 * 1024 * 5 // 5MB
   */
  maxSize?: number;

  /**
   * Maximum number of files (only for multiple mode)
   * @type number
   * @default 5
   */
  maxFiles?: number;

  /**
   * Whether the component is disabled
   * @type boolean
   * @default false
   */
  disabled?: boolean;

  /**
   * Placeholder text or fallback for avatar
   * @type string
   * @default undefined
   */
  placeholder?: string;
}

export function ImageUpload({
  type = 'default',
  mode = 'single',
  value,
  onChange,
  directory = 'images',
  maxSize = 1024 * 1024 * 5, // 5MB
  maxFiles = 5,
  disabled = false,
  placeholder,
  className,
  ...props
}: ImageUploadProps) {
  const t = useTranslations('common');
  const [uploading, setUploading] = React.useState(false);
  const [progress, setProgress] = React.useState<Record<string, number>>({});

  // Normalize value to always work with arrays internally
  const urls = React.useMemo(() => {
    if (!value) return [];
    if (mode === 'single') {
      return typeof value === 'string' ? [value] : [];
    }
    return Array.isArray(value) ? value : [];
  }, [value, mode]);

  const handleUpload = async (files: File[]) => {
    if (disabled) return;

    // Validate file count for multiple mode
    if (mode === 'multiple' && urls.length + files.length > maxFiles) {
      toast.error(
        t('tooManyFiles', {
          max: maxFiles,
          current: urls.length,
          attempting: files.length
        })
      );
      return;
    }

    // Validate individual file sizes
    const oversizedFiles = files.filter((file) => file.size > maxSize);
    if (oversizedFiles.length > 0) {
      toast.error(
        t('fileTooLarge', {
          maxSize: Math.round(maxSize / 1024 / 1024),
          files: oversizedFiles.map((f) => f.name).join(', ')
        })
      );
      return;
    }

    setUploading(true);
    const uploadedUrls: string[] = [];

    try {
      // Initialize progress for all files
      files.forEach((file) => {
        setProgress((prev) => ({ ...prev, [file.name]: 0 }));
      });

      // Upload all files at once
      const response = await uploadMedia(files, directory);

      // Update progress for all files to 100%
      files.forEach((file) => {
        setProgress((prev) => ({ ...prev, [file.name]: 100 }));
      });

      uploadedUrls.push(...response);

      // Combine with existing URLs if in multiple mode
      const newUrls =
        mode === 'multiple' ? [...urls, ...uploadedUrls] : uploadedUrls;

      // Return single URL for single mode, array for multiple mode
      if (mode === 'single') {
        onChange?.(newUrls[0]);
      } else {
        onChange?.(newUrls.slice(0, maxFiles));
      }

      toast.success(
        t('uploadSuccess', {
          target: files.length === 1 ? t('file') : t('files')
        })
      );
    } catch (error) {
      toast.error(
        t('uploadFailed', {
          target: files.length === 1 ? t('file') : t('files')
        })
      );
    } finally {
      setUploading(false);
      setProgress({});
    }
  };

  const handleRemove = (index: number) => {
    if (disabled) return;

    const newUrls = urls.filter((_, i) => i !== index);
    if (mode === 'single') {
      onChange?.(newUrls[0] || '');
    } else {
      onChange?.(newUrls);
    }
  };

  const canUploadMore =
    mode === 'single' ? urls.length === 0 : urls.length < maxFiles;

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
      toast.error(errors[0]); // Show first error
    }
  };

  if (type === 'avatar') {
    return (
      <div
        className={cn('flex flex-col items-center gap-4', className)}
        {...props}
      >
        <div className='relative'>
          <Avatar className='size-24'>
            <AvatarImage src={urls[0]} alt='Avatar' />
            <AvatarFallback className='text-lg'>
              {placeholder || <IconCamera className='size-8' />}
            </AvatarFallback>
          </Avatar>

          {urls[0] && !disabled && (
            <Button
              type='button'
              variant='destructive'
              size='icon'
              className='absolute -right-2 -top-2 size-6 rounded-full'
              onClick={() => handleRemove(0)}
            >
              <IconX className='size-3' />
            </Button>
          )}
        </div>

        {canUploadMore && (
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
                variant='outline'
                size='sm'
                disabled={disabled || uploading}
                {...getRootProps()}
              >
                <input {...getInputProps()} />
                <IconUpload className='mr-2 size-4' />
                {uploading ? t('uploading') : t('uploadAvatar')}
              </Button>
            )}
          </Dropzone>
        )}
      </div>
    );
  }

  return (
    <div className={cn('space-y-4', className)} {...props}>
      {canUploadMore && (
        <Dropzone
          onDrop={handleUpload}
          onDropRejected={handleDropRejected}
          accept={{ 'image/*': [] }}
          multiple={mode === 'multiple'}
          disabled={disabled || uploading}
        >
          {({ getRootProps, getInputProps }) => (
            <div
              {...getRootProps()}
              className={cn(
                'group relative grid h-32 w-full cursor-pointer place-items-center rounded-lg border-2 border-dashed border-muted-foreground/25 px-5 py-2.5 text-center transition hover:bg-muted/25',
                'focus-visible:outline-hidden ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                false && 'border-muted-foreground/50',
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
                    {mode === 'single'
                      ? t('maxFile')
                      : t('maxFiles', { count: maxFiles })}{' '}
                    ({Math.round(maxSize / 1024 / 1024)}MB)
                  </p>
                </div>
              </div>
            </div>
          )}
        </Dropzone>
      )}

      {urls.length > 0 && (
        <div
          className={
            mode === 'single' ? 'w-full' : 'flex gap-4 overflow-x-auto py-2'
          }
        >
          {urls.map((url, index) => {
            const fileName = `image-${index + 1}`;
            const currentProgress = progress[fileName];

            return (
              <div
                key={`${url}-${index}`}
                className='group relative w-full max-w-40'
              >
                <div
                  className={cn(
                    'relative overflow-hidden rounded-lg border',
                    mode === 'single' ? 'aspect-video' : 'aspect-square'
                  )}
                >
                  <img
                    src={url}
                    alt={`Uploaded image ${index + 1}`}
                    className='h-full w-full object-contain'
                  />
                  {currentProgress !== undefined && currentProgress < 100 && (
                    <div className='absolute inset-0 flex items-center justify-center bg-black/50'>
                      <Progress value={currentProgress} className='w-16' />
                    </div>
                  )}
                </div>

                {!disabled && (
                  <div
                    className={cn(
                      'absolute -right-2 -top-2 flex gap-1',
                      mode === 'single'
                        ? 'opacity-100'
                        : 'opacity-0 transition-opacity group-hover:opacity-100'
                    )}
                  >
                    {mode === 'single' && (
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
                    )}
                    <Button
                      type='button'
                      variant='destructive'
                      size='icon'
                      className='size-6 rounded-full'
                      onClick={() => handleRemove(index)}
                    >
                      <IconX className='size-3' />
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
