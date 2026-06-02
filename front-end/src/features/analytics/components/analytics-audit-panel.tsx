'use client';

import { useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAnalyticsAuditExport } from '../hooks/use-analytics';
import { lastNDaysRange } from '../lib/date-range';

export function AnalyticsAuditPanel() {
  const t = useTranslations('analyticsFeature.audit');
  const defaultRange = lastNDaysRange(7);
  const [from, setFrom] = useState(defaultRange.from);
  const [to, setTo] = useState(defaultRange.to);
  const [action, setAction] = useState('');
  const [actor, setActor] = useState('');
  const [resourceType, setResourceType] = useState('');
  const [resourceId, setResourceId] = useState('');
  const exportMutation = useAnalyticsAuditExport();

  const handleExport = () => {
    exportMutation.mutate(
      {
        from,
        to,
        action: action.trim() || undefined,
        actor: actor.trim() || undefined,
        resource_type: resourceType.trim() || undefined,
        resource_id: resourceId.trim() || undefined
      },
      {
        onSuccess: () => toast.success(t('exportSuccess')),
        onError: () => toast.error(t('exportFailed'))
      }
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className='text-base'>{t('title')}</CardTitle>
        <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
      </CardHeader>
      <CardContent className='space-y-4'>
        <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>
          <div className='space-y-1'>
            <Label htmlFor='audit-from'>{t('from')}</Label>
            <Input
              id='audit-from'
              type='date'
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </div>
          <div className='space-y-1'>
            <Label htmlFor='audit-to'>{t('to')}</Label>
            <Input
              id='audit-to'
              type='date'
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </div>
          <div className='space-y-1'>
            <Label htmlFor='audit-action'>{t('action')}</Label>
            <Input
              id='audit-action'
              value={action}
              onChange={(e) => setAction(e.target.value)}
              placeholder={t('actionPlaceholder')}
            />
          </div>
          <div className='space-y-1'>
            <Label htmlFor='audit-actor'>{t('actor')}</Label>
            <Input
              id='audit-actor'
              value={actor}
              onChange={(e) => setActor(e.target.value)}
            />
          </div>
          <div className='space-y-1'>
            <Label htmlFor='audit-resource-type'>{t('resourceType')}</Label>
            <Input
              id='audit-resource-type'
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
            />
          </div>
          <div className='space-y-1'>
            <Label htmlFor='audit-resource-id'>{t('resourceId')}</Label>
            <Input
              id='audit-resource-id'
              value={resourceId}
              onChange={(e) => setResourceId(e.target.value)}
            />
          </div>
        </div>
        <Button onClick={handleExport} disabled={exportMutation.isPending}>
          {exportMutation.isPending ? (
            <Loader2 className='mr-2 size-4 animate-spin' />
          ) : (
            <Download className='mr-2 size-4' />
          )}
          {t('exportCsv')}
        </Button>
        <p className='text-xs text-muted-foreground'>{t('exportNote')}</p>
      </CardContent>
    </Card>
  );
}
