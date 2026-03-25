'use client';

import { IconX, IconUpload, IconFile } from '@tabler/icons-react';
import Image from 'next/image';
import * as React from 'react';
import Dropzone, {
  type DropzoneProps,
  type FileRejection
} from 'react-dropzone';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useControllableState } from '@/hooks/use-controllable-state';
import { cn, formatBytes } from '@/lib/utils';
import {
  uploadFiles as uploadFilesToAPI,
  generateUploadPath
} from './upload-service';

interface FileUploaderProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Value of the uploader.
   * @type File[]
   * @default undefined
   * @example value={files}
   */
  value?: File[];

  /**
   * Function to be called when the value changes.
   * @type React.Dispatch<React.SetStateAction<File[]>>
   * @default undefined
   * @example onValueChange={(files) => setFiles(files)}
   */
  onValueChange?: React.Dispatch<React.SetStateAction<File[]>>;

  /**
   * Function to be called when files are uploaded.
   * @type (files: File[]) => Promise<void>
   * @default undefined
   * @example onUpload={(files) => uploadFiles(files)}
   */
  onUpload?: (files: File[]) => Promise<void>;

  /**
   * Callback when upload completes with results
   * @type (results: string[] | File[]) => void
   * @default undefined
   * @example onUploadComplete={(urls) => setUrls(urls)}
   */
  onUploadComplete?: (results: string[] | File[]) => void;

  /**
   * Progress of the uploaded files.
   * @type Record<string, number> | undefined
   * @default undefined
   * @example progresses={{ "file1.png": 50 }}
   */
  progresses?: Record<string, number>;

  /**
   * Accepted file types for the uploader.
   * @type { [key: string]: string[]}
   * @default
   * ```ts
   * { "image/*": [] }
   * ```
   * @example accept={["image/png", "image/jpeg"]}
   */
  accept?: DropzoneProps['accept'];

  acceptHint?: string;

  /**
   * Maximum file size for the uploader.
   * @type number | undefined
   * @default 1024 * 1024 * 2 // 2MB
   * @example maxSize={1024 * 1024 * 2} // 2MB
   */
  maxSize?: DropzoneProps['maxSize'];

  /**
   * Maximum number of files for the uploader.
   * @type number | undefined
   * @default 1
   * @example maxFiles={5}
   */
  maxFiles?: DropzoneProps['maxFiles'];

  /**
   * Whether the uploader should accept multiple files.
   * @type boolean
   * @default false
   * @example multiple
   */
  multiple?: boolean;

  /**
   * Whether the uploader is disabled.
   * @type boolean
   * @default false
   * @example disabled
   */
  disabled?: boolean;

  /**
   * Custom upload directory for organizing files
   * @type string | undefined
   * @example directory="attachments"
   */
  directory?: string;

  /**
   * Show preview for uploaded files
   * @type boolean
   * @default true
   */
  showPreview?: boolean;

  /**
   * Custom placeholder text
   * @type string | undefined
   */
  placeholder?: string;

  /**
   * Auto upload files when dropped
   * @type boolean
   * @default true
   */
  autoUpload?: boolean;

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
}

export function FileUploader(props: FileUploaderProps) {
  const {
    value: valueProp,
    onValueChange,
    onUpload,
    onUploadComplete,
    progresses: progressesProp,
    accept = { 'image/*': [] },
    acceptHint,
    maxSize = 1024 * 1024 * 2,
    maxFiles = 1,
    multiple = false,
    disabled = false,
    directory,
    showPreview = true,
    placeholder,
    autoUpload = true,
    outputType = 'binary',
    userId,
    className,
    ...dropzoneProps
  } = props;

  const t = useTranslations('common');

  const [files, setFiles] = useControllableState({
    prop: valueProp,
    onChange: onValueChange
  });

  const [internalProgresses, setInternalProgresses] = React.useState<
    Record<string, number>
  >({});

  // Use provided progresses or internal ones
  const progresses = progressesProp || internalProgresses;

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
        // Initialize progress for all files
        const progressTracker: Record<string, number> = {};
        uploadFiles.forEach((file) => {
          progressTracker[file.name] = 0;
        });
        setInternalProgresses(progressTracker);

        const progressInterval = setInterval(() => {
          setInternalProgresses((prev) => {
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
        setInternalProgresses(finalProgress);

        // Call completion callback with URLs
        onUploadComplete?.(urls);

        // Clear progress after a short delay
        setTimeout(() => {
          setInternalProgresses({});
        }, 1000);
      } catch (error) {
        console.error('Upload failed:', error);
        setInternalProgresses({});
        throw error; // Let the toast promise handle the error
      }
    },
    [outputType, userId, directory, onUploadComplete]
  );

  const onDrop = React.useCallback(
    (acceptedFiles: File[], rejectedFiles: FileRejection[]) => {
      if (!multiple && maxFiles === 1 && acceptedFiles.length > 1) {
        toast.error(t('cannotUploadMoreThan', { count: 1 }));
        return;
      }

      if ((files?.length ?? 0) + acceptedFiles.length > maxFiles) {
        toast.error(t('tooManyFiles', { max: maxFiles }));
        return;
      }

      const newFiles = acceptedFiles.map((file) =>
        Object.assign(file, {
          preview: URL.createObjectURL(file)
        })
      );

      // For single file mode, replace existing file
      const updatedFiles =
        !multiple && maxFiles === 1
          ? newFiles
          : files
            ? [...files, ...newFiles]
            : newFiles;

      setFiles(updatedFiles);

      if (rejectedFiles.length > 0) {
        rejectedFiles.forEach(({ file, errors }) => {
          const errorMessages = errors.map((e) => e.message).join(', ');
          toast.error(
            t('fileRejected', { fileName: file.name, reason: errorMessages })
          );
        });
      }

      if (autoUpload && newFiles.length > 0) {
        const target =
          newFiles.length > 1 ? `${newFiles.length} files` : 'file';

        const uploadHandler = onUpload || handleInternalUpload;

        toast.promise(uploadHandler(newFiles), {
          loading: t('uploading', { target }),
          success: () => {
            return t('uploadSuccess', { target });
          },
          error: (error) => {
            console.error('Upload error:', error);
            return t('uploadFailed', { target });
          }
        });
      }
    },
    [
      files,
      maxFiles,
      multiple,
      onUpload,
      setFiles,
      autoUpload,
      t,
      handleInternalUpload
    ]
  );

  function onRemove(index: number) {
    if (!files) return;

    // Revoke the preview URL to prevent memory leaks
    const fileToRemove = files[index];
    if (isFileWithPreview(fileToRemove)) {
      URL.revokeObjectURL(fileToRemove.preview);
    }

    const newFiles = files.filter((_, i) => i !== index);
    setFiles(newFiles);
    onValueChange?.(newFiles);

    toast.success(t('fileRemoved'));
  }

  function handleManualUpload() {
    if (!files?.length) return;

    const target =
      (files?.length || 0) > 1 ? `${files?.length || 0} files` : 'file';
    const uploadHandler = onUpload || handleInternalUpload;

    toast.promise(uploadHandler(files), {
      loading: t('uploading', { target }),
      success: () => {
        setFiles([]);
        return t('uploadSuccess', { target });
      },
      error: (error) => {
        console.error('Upload error:', error);
        return t('uploadFailed', { target });
      }
    });
  }

  // Revoke preview url when component unmounts
  React.useEffect(() => {
    return () => {
      if (!files) return;
      files.forEach((file) => {
        if (isFileWithPreview(file)) {
          URL.revokeObjectURL(file.preview);
        }
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isDisabled = disabled || (files?.length ?? 0) >= maxFiles;
  const acceptedFileTypes = Object.keys(accept || {}).join(', ');

  return (
    <div className='relative flex flex-col gap-4 overflow-hidden'>
      <Dropzone
        onDrop={onDrop}
        accept={accept}
        maxSize={maxSize}
        maxFiles={maxFiles}
        multiple={maxFiles > 1 || multiple}
        disabled={isDisabled}
      >
        {({ getRootProps, getInputProps, isDragActive }) => (
          <div
            {...getRootProps()}
            className={cn(
              'group relative grid h-52 w-full cursor-pointer place-items-center rounded-lg border-2 border-dashed border-muted-foreground/25 px-5 py-2.5 text-center transition hover:bg-muted/25',
              'focus-visible:outline-hidden ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
              isDragActive && 'border-muted-foreground/50',
              isDisabled && 'pointer-events-none opacity-60',
              className
            )}
            {...dropzoneProps}
          >
            <input {...getInputProps()} />
            {isDragActive ? (
              <div className='flex flex-col items-center justify-center gap-4 sm:px-5'>
                <div className='rounded-full border border-dashed p-3'>
                  <IconUpload
                    className='size-7 text-muted-foreground'
                    aria-hidden='true'
                  />
                </div>
                <p className='font-medium text-muted-foreground'>
                  {t('dropFilesHere')}
                </p>
              </div>
            ) : (
              <div className='flex flex-col items-center justify-center gap-4 sm:px-5'>
                <div className='rounded-full border border-dashed p-3'>
                  <IconUpload
                    className='size-7 text-muted-foreground'
                    aria-hidden='true'
                  />
                </div>
                <div className='space-y-px'>
                  <p className='font-medium text-muted-foreground'>
                    {placeholder || t('dragDropFiles')}
                  </p>
                  <p className='text-sm text-muted-foreground/70'>
                    {maxFiles > 1
                      ? ` ${maxFiles === Infinity ? 'multiple' : maxFiles}
                      files (up to ${formatBytes(maxSize)} each)`
                      : ` a file with ${formatBytes(maxSize)}`}
                  </p>
                  {acceptedFileTypes && (
                    <p className='text-xs text-muted-foreground/60'>
                      {t('acceptedTypes', {
                        types: acceptHint || acceptedFileTypes
                      })}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </Dropzone>

      {!autoUpload && files && files.length > 0 && (
        <div className='flex justify-end'>
          <Button
            type='button'
            onClick={handleManualUpload}
            disabled={!files?.length || disabled}
            size='sm'
          >
            {t('uploadFiles', { count: files?.length || 0 })}
          </Button>
        </div>
      )}

      {showPreview && files?.length ? (
        <div className='w-full'>
          {/* Single file preview */}
          {!multiple && maxFiles === 1 ? (
            <div className='space-y-2'>
              <FileCard
                file={files[0] as File}
                onRemove={() => onRemove(0)}
                progress={progresses?.[files[0]?.name]}
                showPreview={showPreview}
                compact={false}
                t={t}
              />
            </div>
          ) : (
            /* Multiple files preview */
            <ScrollArea className='h-fit w-full px-3'>
              <div className='max-h-48 space-y-3'>
                {files?.map((file, index) => (
                  <FileCard
                    key={`${file.name}-${index}`}
                    file={file as File}
                    onRemove={() => onRemove(index)}
                    progress={progresses?.[file.name]}
                    showPreview={showPreview}
                    compact={true}
                    t={t}
                  />
                ))}
              </div>
            </ScrollArea>
          )}
        </div>
      ) : null}
    </div>
  );
}

interface FileCardProps {
  file: File;
  onRemove: () => void;
  progress?: number;
  showPreview?: boolean;
  compact?: boolean;
  t: ReturnType<typeof useTranslations>;
}

function FileCard({
  file,
  progress,
  onRemove,
  showPreview = true,
  compact = true,
  t
}: FileCardProps) {
  if (!file) return null;
  const isImage = file?.type?.startsWith('image/');
  const isPdf = file?.type === 'application/pdf';
  const isDoc =
    file?.type?.includes('word') || file?.type?.includes('document');

  const previewSize = compact ? 48 : 64;
  const iconSize = compact ? 6 : 8;

  const getFileIcon = () => {
    if (isPdf) return '📄';
    if (isDoc) return '📝';
    return '📎';
  };

  return (
    <div
      className={cn(
        'relative flex items-center space-x-4 rounded-lg border bg-card p-3',
        !compact && 'border-dashed'
      )}
    >
      <div className='flex flex-1 space-x-4'>
        {showPreview && isFileWithPreview(file) && isImage ? (
          <div className='relative'>
            <Image
              src={file.preview}
              alt={file.name}
              width={previewSize}
              height={previewSize}
              loading='lazy'
              className={cn(
                'aspect-square shrink-0 rounded-md object-cover',
                !compact && 'ring-2 ring-primary/20'
              )}
            />
            {!compact && (
              <div className='absolute -bottom-1 -right-1 rounded-full bg-primary px-1.5 py-0.5 text-xs text-primary-foreground'>
                📷
              </div>
            )}
          </div>
        ) : (
          <div
            className={cn(
              'flex shrink-0 items-center justify-center rounded-md border bg-muted',
              compact ? 'size-12' : 'size-16'
            )}
          >
            {!compact ? (
              <span className='text-2xl'>{getFileIcon()}</span>
            ) : (
              <IconFile
                className={cn(
                  'text-muted-foreground',
                  compact ? 'size-6' : 'size-8'
                )}
              />
            )}
          </div>
        )}
        <div className='flex w-full flex-col gap-2'>
          <div className='space-y-px'>
            <p
              className={cn(
                'line-clamp-1 font-medium text-foreground/80',
                compact ? 'text-sm' : 'text-base'
              )}
            >
              {(file as File & { displayName?: string })?.displayName ||
                file?.name}
            </p>
            <div className='flex items-center gap-2'>
              <p className='text-xs text-muted-foreground'>
                {formatBytes(file?.size)}
              </p>
              {!compact && (
                <span className='text-xs text-muted-foreground'>
                  • {file?.type || 'Unknown type'}
                </span>
              )}
            </div>
          </div>
          {progress !== undefined && progress < 100 && (
            <div className='space-y-1'>
              <Progress
                value={progress}
                className={cn('h-2', !compact && 'h-3')}
              />
              <p className='text-xs text-muted-foreground'>
                {progress}% uploaded
              </p>
            </div>
          )}
        </div>
      </div>
      <div className='flex items-center gap-2'>
        <Button
          type='button'
          variant='ghost'
          size='icon'
          onClick={onRemove}
          disabled={progress !== undefined && progress < 100}
          className={cn('rounded-full', compact ? 'size-8' : 'size-10')}
        >
          <IconX
            className={cn(
              'text-muted-foreground',
              compact ? 'size-4' : 'size-5'
            )}
          />
          <span className='sr-only'>{t('removeFile')}</span>
        </Button>
      </div>
    </div>
  );
}

function isFileWithPreview(file: File): file is File & { preview: string } {
  return 'preview' in file && typeof file?.preview === 'string';
}
