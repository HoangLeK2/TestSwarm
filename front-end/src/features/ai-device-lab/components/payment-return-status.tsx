'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { formatFarmApiError } from '@/lib/format-farm-api-error';

import {
  loadWizardState,
  type WizardState
} from '../services/ai-device-lab-api';

export function PaymentReturnStatus({
  campaignId,
  locale
}: {
  campaignId: string | null;
  locale: 'en' | 'vi';
}) {
  const [state, setState] = useState<WizardState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const copy =
    locale === 'vi'
      ? {
          title: 'Trạng thái thanh toán',
          missing: 'Thiếu campaign ID hợp lệ trong đường dẫn trả về.',
          loading: 'Đang hỏi máy chủ về payment event đã xác minh…',
          paid: 'Thanh toán đã được xác minh và quyền dịch vụ đã được cấp.',
          pending:
            'Thanh toán chưa được máy chủ xác minh. Trang này sẽ tiếp tục kiểm tra; redirect không tự cấp quyền.',
          failed: 'Thanh toán không thành công hoặc đã hoàn tiền.',
          back: 'Quay lại wizard',
          loadError: 'Không tải được trạng thái thanh toán.'
        }
      : {
          title: 'Payment status',
          missing: 'The provider return is missing a valid campaign ID.',
          loading: 'Checking the server for a verified payment event…',
          paid: 'Payment is verified and the service entitlement is active.',
          pending:
            'The server has not verified payment yet. This page will keep checking; a redirect never grants access.',
          failed: 'Payment failed or was refunded.',
          back: 'Return to wizard',
          loadError: 'The payment state could not be loaded.'
        };

  useEffect(() => {
    if (!campaignId) return;
    let cancelled = false;
    let timer: number | undefined;
    let attempts = 0;
    const poll = async () => {
      try {
        const next = await loadWizardState(campaignId);
        if (cancelled) return;
        setState(next);
        setError(null);
        const terminal =
          next.payment.entitlement?.state === 'active' ||
          ['failed', 'refunded'].includes(next.payment.order?.status ?? '');
        attempts += 1;
        if (!terminal && attempts < 30) timer = window.setTimeout(poll, 2000);
      } catch (reason) {
        if (!cancelled) setError(formatFarmApiError(reason, copy.loadError));
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [campaignId, copy.loadError]);

  const paid = state?.payment.entitlement?.state === 'active';
  const failed = ['failed', 'refunded'].includes(
    state?.payment.order?.status ?? ''
  );

  return (
    <main className='flex min-h-screen items-center justify-center bg-slate-50 p-6'>
      <Card className='w-full max-w-xl'>
        <CardHeader>
          <h1 className='text-2xl font-semibold'>{copy.title}</h1>
        </CardHeader>
        <CardContent className='space-y-4' aria-live='polite'>
          {!campaignId ? (
            <p role='alert'>{copy.missing}</p>
          ) : error ? (
            <p role='alert' className='text-red-700'>
              {error}
            </p>
          ) : paid ? (
            <p className='text-emerald-800'>{copy.paid}</p>
          ) : failed ? (
            <p className='text-red-800'>{copy.failed}</p>
          ) : (
            <p className='flex items-start gap-2 text-amber-900'>
              <Loader2 className='mt-0.5 size-4 shrink-0 animate-spin' />
              {state ? copy.pending : copy.loading}
            </p>
          )}
          {campaignId && (
            <Button asChild>
              <Link
                href={`/${locale}/ai-device-lab/wizard/${encodeURIComponent(campaignId)}`}
              >
                {copy.back}
              </Link>
            </Button>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
