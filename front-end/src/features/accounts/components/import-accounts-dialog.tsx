'use client';

import { useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useBulkImportAccountsCsv } from '../hooks/use-accounts';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

export function ImportAccountsDialog() {
  const t = useTranslations('accountsFeature.importDialog');
  const [open, setOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const {
    mutate,
    isPending,
    data: result,
    error,
    reset
  } = useBulkImportAccountsCsv();

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    mutate(file);
  };

  const handleClose = (v: boolean) => {
    setOpen(v);
    if (!v) reset();
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
          <code className='block rounded bg-muted p-2 text-xs'>
            platform,username,password,display_name,tags,notes
          </code>
          <input
            ref={fileRef}
            type='file'
            accept='.csv'
            className='hidden'
            onChange={handleFile}
          />
          <Button
            variant='outline'
            className='w-full'
            disabled={isPending}
            onClick={() => fileRef.current?.click()}
          >
            {isPending ? t('importing') : t('selectFile')}
          </Button>
          {result && (
            <p className='text-sm text-green-600'>
              {t('result', {
                created: result.created,
                skipped: result.skipped,
                total: result.total
              })}
            </p>
          )}
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
