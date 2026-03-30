import { uploadFiles } from '@/components/upload/upload-service';

/** Multi-file upload used by shared image components (device farm portal). */
export async function uploadMedia(
  files: File[],
  directory: string = 'images'
): Promise<string[]> {
  return uploadFiles(files, directory);
}
