'use client';

import { IconCamera, IconUpload, IconX } from '@tabler/icons-react';
import { useTranslations } from 'next-intl';
import * as React from 'react';
import Dropzone from 'react-dropzone';
import { toast } from 'sonner';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  uploadFiles as uploadFilesToAPI,
  generateUploadPath
} from '@/components/upload/upload-service';

export type FileImageUploadType = 'avatar' | 'default';
export type FileImageUploadMode = 'single' | 'multiple';

interface FileImageUploadProps<
  T extends FileImageUploadMode = FileImageUploadMode
> extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onChange'> {
  /**
   * Type of image upload - affects the visual display
   * @type FileImageUploadType
   * @default 'default'
   */
  type?: FileImageUploadType;

  /**
   * Upload mode - single or multiple files
   * @type T
   * @default 'single'
   */
  mode?: T;

  /**
   * Current value - File/string for single mode, File[]/string[] for multiple mode
   * @type T extends 'single' ? File | string : File[] | string[]
   * @default undefined
   */
  value?: T extends 'single' ? File | string : File[] | string[];

  /**
   * Callback when files are selected
   * @type (files: T extends 'single' ? File | string : File[] | string[]) => void
   * @default undefined
   */
  onChange?: (
    files: T extends 'single' ? File | string : File[] | string[]
  ) => void;

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

  /**
   * Output type for uploaded files
   * @type 'binary' | 'url'
   * @default 'binary'
   * @example outputType="url" // Returns URLs from API
   * @example outputType="binary" // Returns File objects
   */
  outputType?: 'binary' | 'url';

  /**
   * User ID for organizing uploads
   * @type string | undefined
   * @example userId="user123"
   */
  userId?: string;

  /**
   * Custom upload directory for organizing files
   * @type string | undefined
   * @example directory="attachments"
   */
  directory?: string;

  /**
   * Auto upload files when dropped
   * @type boolean
   * @default false
   */
  autoUpload?: boolean;

  /**
   * Callback when upload completes with results
   * @type (results: string[] | File[]) => void
   * @default undefined
   * @example onUploadComplete={(urls) => setUrls(urls)}
   */
  onUploadComplete?: (results: string[] | File[]) => void;
}

export function FileImageUpload({
  type = 'default',
  mode = 'single',
  value,
  onChange,
  maxSize = 1024 * 1024 * 5, // 5MB
  maxFiles = 5,
  disabled = false,
  placeholder,
  outputType = 'binary',
  userId,
  directory,
  autoUpload = false,
  onUploadComplete,
  className,
  ...props
}: FileImageUploadProps) {
  const t = useTranslations('common');

  // Normalize value to always work with arrays internally
  const items = React.useMemo(() => {
    if (!value) return [];
    if (mode === 'single') {
      return value ? [value] : [];
    }
    return Array.isArray(value) ? value : [];
  }, [value, mode]);

  // Separate files and URLs
  const files = React.useMemo(() => {
    return items.filter((item): item is File => item instanceof File);
  }, [items]);

  const existingUrls = React.useMemo(() => {
    return items.filter((item): item is string => typeof item === 'string');
  }, [items]);

  // Create preview URLs for files
  const [previewUrls, setPreviewUrls] = React.useState<string[]>([]);

  // Upload progress tracking
  const [uploadProgress, setUploadProgress] = React.useState<
    Record<string, number>
  >({});
  const [isUploading, setIsUploading] = React.useState(false);

  // Handle internal upload
  const handleInternalUpload = React.useCallback(
    async (uploadFiles: File[]) => {
      if (outputType === 'binary') {
        // For binary mode, just return the files without API call
        onUploadComplete?.(uploadFiles);
        return;
      }

      if (!userId) {
        toast.error('User ID is required for URL mode');
        return;
      }

      try {
        setIsUploading(true);

        const progressTracker: Record<string, number> = {};
        uploadFiles.forEach((file) => {
          progressTracker[file.name] = 0;
        });
        setUploadProgress(progressTracker);

        const progressInterval = setInterval(() => {
          setUploadProgress((prev) => {
            const updated = { ...prev };
            uploadFiles.forEach((file) => {
              if (updated[file.name] < 90) {
                updated[file.name] = Math.min(90, updated[file.name] + 10);
              }
            });
            return updated;
          });
        }, 200);

        // Upload files using the upload service
        const uploadPath = directory
          ? `${directory}/${userId}`
          : generateUploadPath(userId, 'uploads');
        const urls = await uploadFilesToAPI(uploadFiles, uploadPath);

        // Complete progress
        clearInterval(progressInterval);
        const finalProgress: Record<string, number> = {};
        uploadFiles.forEach((file) => {
          finalProgress[file.name] = 100;
        });
        setUploadProgress(finalProgress);

        // Always append new URLs to existing ones when there are existing values
        const finalUrls =
          existingUrls.length > 0 ? [...existingUrls, ...urls] : urls;

        // Call completion callback with combined URLs
        onUploadComplete?.(finalUrls);

        // Clear progress after a short delay
        setTimeout(() => {
          setUploadProgress({});
          setIsUploading(false);
        }, 1000);
      } catch (error) {
        console.error('Upload failed:', error);
        setUploadProgress({});
        setIsUploading(false);
        throw error; // Let the toast promise handle the error
      }
    },
    [outputType, userId, directory, onUploadComplete]
  );

  React.useEffect(() => {
    // Clean up old URLs (only for blob URLs created from files)
    previewUrls.forEach((url) => {
      if (url.startsWith('blob:')) {
        URL.revokeObjectURL(url);
      }
    });

    // Create preview URLs: combine existing URLs with new blob URLs from files
    const filePreviewUrls = files.map((file) => URL.createObjectURL(file));
    const allPreviewUrls = [...existingUrls, ...filePreviewUrls];
    setPreviewUrls(allPreviewUrls);

    // Cleanup function
    return () => {
      filePreviewUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [files, existingUrls]);

  const handleFileSelect = (newFiles: File[]) => {
    if (disabled) return;

    // Validate file count for multiple mode (count both files and existing URLs)
    const totalCurrentItems = items.length;
    if (mode === 'multiple' && totalCurrentItems + newFiles.length > maxFiles) {
      toast.error(
        t('tooManyFiles', {
          max: maxFiles,
          current: totalCurrentItems,
          attempting: newFiles.length
        })
      );
      return;
    }

    // Validate individual file sizes
    const oversizedFiles = newFiles.filter((file) => file.size > maxSize);
    if (oversizedFiles.length > 0) {
      toast.error(
        t('fileTooLarge', {
          maxSize: Math.round(maxSize / 1024 / 1024),
          files: oversizedFiles.map((f) => f.name).join(', ')
        })
      );
      return;
    }

    // Combine with existing items if in multiple mode
    const updatedItems =
      mode === 'multiple' ? [...items, ...newFiles] : newFiles;
    const finalItems = updatedItems.slice(0, maxFiles);

    console.log('updatedItems', updatedItems);
    console.log('finalItems', finalItems);

    // Return single item for single mode, array for multiple mode
    if (mode === 'single') {
      onChange?.(finalItems[0] as any);
    } else {
      onChange?.(finalItems as any);
    }

    // Auto upload if enabled
    if (autoUpload && newFiles.length > 0) {
      const target = newFiles.length === 1 ? t('file') : t('files');

      toast.promise(handleInternalUpload(newFiles), {
        loading: t('uploading', { target }),
        success: () => {
          return t('uploadSuccess', { target });
        },
        error: (error) => {
          console.error('Upload error:', error);
          return t('uploadFailed', { target });
        }
      });
    } else {
      toast.success(
        t('uploadSuccess', {
          target: newFiles.length === 1 ? t('file') : t('files')
        })
      );
    }
  };

  const handleRemove = (index: number) => {
    if (disabled) return;

    const newItems = items.filter((_, i) => i !== index);
    if (mode === 'single') {
      onChange?.((newItems[0] as any) || null);
    } else {
      onChange?.(newItems as any);
    }
  };

  const canUploadMore =
    mode === 'single' ? items.length === 0 : items.length < maxFiles;

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
            <AvatarImage src={previewUrls[0]} alt='Avatar' />
            <AvatarFallback className='text-lg'>
              {placeholder || <IconCamera className='size-8' />}
            </AvatarFallback>
          </Avatar>

          {previewUrls[0] && !disabled && (
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
            onDrop={handleFileSelect}
            onDropRejected={handleDropRejected}
            accept={{ 'image/*': [] }}
            multiple={false}
            disabled={disabled}
          >
            {({ getRootProps, getInputProps }) => (
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={disabled}
                {...getRootProps()}
              >
                <input {...getInputProps()} />
                <IconUpload className='mr-2 size-4' />
                {t('uploadAvatar')}
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
          onDrop={handleFileSelect}
          onDropRejected={handleDropRejected}
          accept={{ 'image/*': [] }}
          multiple={mode === 'multiple'}
          disabled={disabled}
        >
          {({ getRootProps, getInputProps }) => (
            <div
              {...getRootProps()}
              className={cn(
                'group relative grid h-32 w-full cursor-pointer place-items-center rounded-lg border-2 border-dashed border-muted-foreground/25 px-5 py-2.5 text-center transition hover:bg-muted/25',
                'focus-visible:outline-hidden ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                disabled && 'pointer-events-none opacity-60'
              )}
            >
              <input {...getInputProps()} />
              <div className='flex flex-col items-center justify-center gap-2'>
                <div className='rounded-full border border-dashed p-2'>
                  <IconUpload className='size-5 text-muted-foreground' />
                </div>
                <div className='space-y-1'>
                  <p className='text-sm font-medium text-muted-foreground'>
                    {t('dropImagesHere')}
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

      {items.length > 0 && (
        <div
          className={
            mode === 'single' ? 'w-full' : 'flex gap-4 overflow-x-auto py-2'
          }
        >
          {items.map((item, index) => {
            const previewUrl = previewUrls[index];
            const isFile = item instanceof File;
            const displayName = isFile ? item.name : `Image ${index + 1}`;

            return (
              <div
                key={`${displayName}-${index}`}
                className='group relative w-full max-w-40'
              >
                <div
                  className={cn(
                    'relative overflow-hidden rounded-lg border',
                    mode === 'single' ? 'aspect-video' : 'aspect-square'
                  )}
                >
                  <img
                    src={previewUrl}
                    alt={displayName}
                    className='h-full w-full object-contain'
                  />
                </div>

                <div className='mt-1 truncate text-xs text-muted-foreground'>
                  {displayName}
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
                        onDrop={handleFileSelect}
                        onDropRejected={handleDropRejected}
                        accept={{ 'image/*': [] }}
                        multiple={false}
                        disabled={disabled}
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
