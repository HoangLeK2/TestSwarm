'use client';

import { useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import {
  useAccountImportFormats,
  useBulkImportAccountsCsv,
  useBulkImportAccountsTxt
} from '../hooks/use-accounts';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

export function ImportAccountsDialog() {
  const t = useTranslations('accountsFeature.importDialog');
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<'csv' | 'txt'>('csv');
  const [formatSlug, setFormatSlug] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const formats = useAccountImportFormats();
  const csvImport = useBulkImportAccountsCsv();
  const txtImport = useBulkImportAccountsTxt();
  const activeFormats = formats.data?.items ?? [];
  const selectedFormatSlug = formatSlug || activeFormats[0]?.slug || '';
  const error = csvImport.error ?? txtImport.error;
  const isPending = csvImport.isPending || txtImport.isPending;

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSelectedFile(file);
    csvImport.reset();
    txtImport.reset();
    e.target.value = '';
  };

  const handleUpload = () => {
    if (!selectedFile) return;
    if (kind === 'txt') {
      txtImport.mutate(
        { file: selectedFile, formatSlug: selectedFormatSlug },
        {
          onSuccess: (data) => {
            toast.success(
              t('result', {
                created: data.created,
                skipped: data.skipped,
                total: data.total
              })
            );
            setSelectedFile(null);
          }
        }
      );
    } else {
      csvImport.mutate(selectedFile, {
        onSuccess: (data) => {
          toast.success(
            t('result', {
              created: data.created,
              skipped: data.skipped,
              total: data.total
            })
          );
          setSelectedFile(null);
        }
      });
    }
  };

  const handleKindChange = (value: 'csv' | 'txt') => {
    setKind(value);
    setSelectedFile(null);
    csvImport.reset();
    txtImport.reset();
  };

  const handleClose = (v: boolean) => {
    setOpen(v);
    if (!v) {
      setSelectedFile(null);
      csvImport.reset();
      txtImport.reset();
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline'>
          <Upload size={16} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='z-[1000] max-w-sm'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <div className='space-y-4 pt-2'>
          <p className='text-sm text-muted-foreground'>{t('description')}</p>
          <code className='block overflow-hidden text-ellipsis whitespace-nowrap rounded bg-muted p-2 text-xs'>
            {kind === 'txt'
              ? activeFormats.find((fmt) => fmt.slug === selectedFormatSlug)?.description ||
                t('txtFormatFallback')
              : 'platform,username,password,display_name,tags,notes'}
          </code>
          <div className='space-y-2'>
            <Select
              value={kind}
              onValueChange={(value) => handleKindChange(value as 'csv' | 'txt')}
            >
              <SelectTrigger className='w-full'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='csv'>{t('csv')}</SelectItem>
                <SelectItem value='txt'>{t('txt')}</SelectItem>
              </SelectContent>
            </Select>
            {kind === 'txt' ? (
              <Select
                value={selectedFormatSlug}
                onValueChange={setFormatSlug}
                disabled={!activeFormats.length}
              >
                <SelectTrigger className='w-full min-w-0'>
                  <SelectValue placeholder={t('format')} />
                </SelectTrigger>
                <SelectContent>
                  {activeFormats.map((fmt) => (
                    <SelectItem key={fmt.id} value={fmt.slug}>
                      {fmt.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <div className='flex h-9 w-full items-center rounded-md border border-input bg-muted px-3 text-sm text-muted-foreground'>
                {t('standardCsv')}
              </div>
            )}
          </div>
          <input
            ref={fileRef}
            type='file'
            accept={kind === 'txt' ? '.txt,text/plain' : '.csv,text/csv'}
            className='hidden'
            onChange={handleFile}
          />
          <Button
            variant='outline'
            className='w-full'
            disabled={isPending}
            onClick={() => fileRef.current?.click()}
          >
            {kind === 'txt' ? t('selectTxtFile') : t('selectCsvFile')}
          </Button>
          {selectedFile && (
            <p className='truncate text-xs text-muted-foreground'>
              {selectedFile.name}
            </p>
          )}
          <Button
            className='w-full'
            variant={selectedFile ? 'default' : 'secondary'}
            disabled={
              isPending ||
              !selectedFile ||
              (kind === 'txt' && !selectedFormatSlug)
            }
            onClick={handleUpload}
          >
            {isPending ? t('importing') : t('upload')}
          </Button>
          {error && (
            <p className='text-xs text-destructive'>
              {formatFarmApiError(error, t('importFailed'))}
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
