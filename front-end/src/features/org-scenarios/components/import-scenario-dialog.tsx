'use client';

import { useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
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
import { useImportOrgScenario } from '../hooks/use-org-scenarios';

export function ImportOrgScenarioDialog() {
  const t = useTranslations('orgScenariosFeature.importDialog');
  const [open, setOpen] = useState(false);
  const [resolve, setResolve] = useState<'reject' | 'create_stub'>('reject');
  const inputRef = useRef<HTMLInputElement>(null);
  const { mutate, isPending, error, reset } = useImportOrgScenario();

  const onFile = (file: File | undefined) => {
    if (!file) return;
    mutate(
      { file, resolve },
      {
        onSuccess: () => {
          reset();
          setOpen(false);
          if (inputRef.current) inputRef.current.value = '';
        }
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline'>
          <Upload size={16} className='mr-1' />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      <DialogContent className='max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
        </DialogHeader>
        <div className='space-y-4'>
          <p className='text-sm text-muted-foreground'>{t('hint')}</p>
          <div className='space-y-1.5'>
            <Label>{t('resolveLabel')}</Label>
            <Select
              value={resolve}
              onValueChange={(value) =>
                setResolve(value as 'reject' | 'create_stub')
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='reject'>{t('resolveReject')}</SelectItem>
                <SelectItem value='create_stub'>
                  {t('resolveCreateStub')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <input
            ref={inputRef}
            type='file'
            accept='.yaml,.yml,.json,application/json,text/yaml'
            className='block w-full text-sm'
            disabled={isPending}
            onChange={(event) => onFile(event.target.files?.[0])}
          />
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
