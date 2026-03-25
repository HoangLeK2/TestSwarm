import axios from 'axios';
import { env } from '@/constants/env';

export interface UploadResponse {
  urls: string[];
  success: boolean;
  message?: string;
}

export interface UploadOptions {
  directory?: string;
  maxRetries?: number;
  timeout?: number;
}

/**
 * Upload multiple files to the media service
 * @param files - Array of files to upload
 * @param directory - Directory path for organizing uploads
 * @param options - Additional upload options
 * @returns Promise with array of uploaded file URLs
 */
export const uploadFiles = async (
  files: File[],
  directory: string = 'uploads',
  options: UploadOptions = {}
): Promise<string[]> => {
  const { maxRetries = 3, timeout = 30000 } = options;

  if (!files || files.length === 0) {
    throw new Error('No files provided for upload');
  }

  const formData = new FormData();

  files.forEach((file) => {
    formData.append('files', file);
  });

  formData.append('directory', directory);

  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const response = await axios.post<UploadResponse>(
        `${env.API_PRODUCT_URL}/api/v1/upload-media`,
        formData,
        {
          headers: {
            accept: 'application/json'
          },
          timeout
        }
      );

      return response.data?.urls || [];
    } catch (error) {
      lastError =
        error instanceof Error ? error : new Error('Unknown upload error');

      if (attempt === maxRetries) {
        break;
      }

      await new Promise((resolve) =>
        setTimeout(resolve, Math.pow(2, attempt) * 1000)
      );
    }
  }

  throw lastError || new Error('Upload failed after all retries');
};

/**
 * Upload a single file
 */
export const uploadFile = async (
  file: File,
  directory: string = 'uploads',
  options: UploadOptions = {}
): Promise<string> => {
  const urls = await uploadFiles([file], directory, options);

  if (urls.length === 0) {
    throw new Error('No URL returned from upload');
  }

  return urls[0];
};

/**
 * Validate file before upload
 */
export const validateFile = (
  file: File,
  maxSize: number = 10 * 1024 * 1024,
  allowedTypes: string[] = []
): { valid: boolean; error?: string } => {
  if (file.size > maxSize) {
    return {
      valid: false,
      error: `File size (${formatFileSize(file.size)}) exceeds maximum allowed size (${formatFileSize(maxSize)})`
    };
  }

  if (allowedTypes.length > 0 && !allowedTypes.includes(file.type)) {
    return {
      valid: false,
      error: `File type ${file.type} is not allowed. Allowed types: ${allowedTypes.join(', ')}`
    };
  }

  return { valid: true };
};

export const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes';

  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

export const generateUploadPath = (
  userId: string,
  context: string = 'uploads'
): string => {
  const timestamp = new Date().toISOString().split('T')[0];
  return `${context}/${userId}/${timestamp}`;
};
