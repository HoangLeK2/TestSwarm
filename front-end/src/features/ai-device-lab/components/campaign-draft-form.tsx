'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

import { createServiceCampaign } from '../services/ai-device-lab-api';

type Locale = 'en' | 'vi';

const acquisitionStorageKey = 'ai-device-lab:acquisition-v1';

type AcquisitionEvent = {
  event_id: string;
  event_name: 'landing_view' | 'start_click';
  occurred_at: string;
  attribution: Record<string, string>;
};

type AcquisitionJourney = {
  acquisitionId: string;
  events: AcquisitionEvent[];
};

function safeAttribution(): Record<string, string> {
  const attribution: Record<string, string> = {};
  const params = new URLSearchParams(window.location.search);
  for (const key of [
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content'
  ]) {
    const value = params.get(key)?.trim();
    if (
      value &&
      value.length <= 128 &&
      !value.includes('@') &&
      !Array.from(value).some((character) => character.charCodeAt(0) < 32)
    ) {
      attribution[key] = value;
    }
  }
  if (document.referrer) {
    try {
      const host = new URL(document.referrer).hostname;
      if (host && host.length <= 128) attribution.referrer_host = host;
    } catch {
      // Invalid referrers are intentionally ignored instead of persisted.
    }
  }
  return attribution;
}

function acquisitionJourney(markStart = false): AcquisitionJourney {
  let journey: AcquisitionJourney | null = null;
  const stored = window.sessionStorage.getItem(acquisitionStorageKey);
  if (stored) {
    try {
      const candidate = JSON.parse(stored) as AcquisitionJourney;
      if (
        typeof candidate.acquisitionId === 'string' &&
        Array.isArray(candidate.events)
      ) {
        journey = candidate;
      }
    } catch {
      // Corrupt browser state is replaced with a new opaque journey.
    }
  }
  if (!journey) {
    const legacyIntent = window.sessionStorage.getItem(
      'ai-device-lab:creation-intent'
    );
    journey = {
      acquisitionId:
        legacyIntent && legacyIntent.length >= 8 && legacyIntent.length <= 128
          ? legacyIntent
          : crypto.randomUUID(),
      events: [
        {
          event_id: crypto.randomUUID(),
          event_name: 'landing_view',
          occurred_at: new Date().toISOString(),
          attribution: safeAttribution()
        }
      ]
    };
  }
  if (
    markStart &&
    !journey.events.some((event) => event.event_name === 'start_click')
  ) {
    journey.events.push({
      event_id: crypto.randomUUID(),
      event_name: 'start_click',
      occurred_at: new Date().toISOString(),
      attribution: safeAttribution()
    });
  }
  window.sessionStorage.setItem(acquisitionStorageKey, JSON.stringify(journey));
  return journey;
}

export function CampaignDraftForm({ locale }: { locale: Locale }) {
  const router = useRouter();
  const [runtimeCampaignId, setRuntimeCampaignId] = useState('');
  const [packageName, setPackageName] = useState('');
  const [timezone, setTimezone] = useState('UTC');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    acquisitionJourney();
  }, []);
  const text = useMemo(
    () =>
      locale === 'vi'
        ? {
            title: 'Tạo draft AI Device Lab',
            description:
              'Draft được lưu theo tổ chức đang hoạt động. Retry dùng cùng creation intent để không tạo trùng.',
            runtime: 'Runtime campaign ID',
            package: 'Android package name',
            timezone: 'Múi giờ dịch vụ',
            submit: 'Tạo draft 12 lane',
            submitting: 'Đang tạo…',
            error: 'Không tạo được draft campaign.'
          }
        : {
            title: 'Create an AI Device Lab draft',
            description:
              'The draft belongs to the active organization. Retries reuse one creation intent to prevent duplicates.',
            runtime: 'Runtime campaign ID',
            package: 'Android package name',
            timezone: 'Service timezone',
            submit: 'Create 12-lane draft',
            submitting: 'Creating…',
            error: 'The campaign draft could not be created.'
          },
    [locale]
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const journey = acquisitionJourney(true);
      const campaign = await createServiceCampaign({
        creation_intent_key: journey.acquisitionId,
        runtime_campaign_id: runtimeCampaignId.trim(),
        package_name: packageName.trim(),
        timezone: timezone.trim(),
        plan_version: 'adl-14d-v1',
        acquisition_events: journey.events
      });
      window.sessionStorage.removeItem(acquisitionStorageKey);
      window.sessionStorage.removeItem('ai-device-lab:creation-intent');
      router.push(`/${locale}/ai-device-lab/wizard/${campaign.id}`);
    } catch (reason) {
      setError(formatFarmApiError(reason, text.error));
      setSubmitting(false);
    }
  }

  return (
    <main className='min-h-screen bg-slate-50 px-5 py-10 text-slate-950 sm:px-8'>
      <Card className='mx-auto max-w-2xl'>
        <CardHeader>
          <div className='mb-3 flex items-center gap-2 text-sm font-medium text-emerald-700'>
            <ShieldCheck className='size-4' aria-hidden='true' />
            AI Device Lab
          </div>
          <CardTitle className='text-3xl'>{text.title}</CardTitle>
          <p className='pt-2 text-sm leading-6 text-slate-600'>
            {text.description}
          </p>
        </CardHeader>
        <CardContent>
          <form className='space-y-5' onSubmit={submit}>
            <div className='space-y-2'>
              <Label htmlFor='runtime-campaign'>{text.runtime}</Label>
              <Input
                id='runtime-campaign'
                value={runtimeCampaignId}
                onChange={(event) => setRuntimeCampaignId(event.target.value)}
                required
                autoComplete='off'
              />
            </div>
            <div className='space-y-2'>
              <Label htmlFor='package-name'>{text.package}</Label>
              <Input
                id='package-name'
                value={packageName}
                onChange={(event) => setPackageName(event.target.value)}
                required
                pattern='[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+'
                autoComplete='off'
              />
            </div>
            <div className='space-y-2'>
              <Label htmlFor='service-timezone'>{text.timezone}</Label>
              <Input
                id='service-timezone'
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                required
                autoComplete='off'
              />
            </div>
            {error && (
              <p
                role='alert'
                className='rounded-lg bg-red-50 p-3 text-sm text-red-900'
              >
                {error}
              </p>
            )}
            <Button type='submit' disabled={submitting}>
              {submitting ? text.submitting : text.submit}
              {!submitting && (
                <ArrowRight className='ml-2 size-4' aria-hidden='true' />
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
