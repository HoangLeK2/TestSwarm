'use client';

import { useState, useEffect, useCallback } from 'react';
import QRCode from 'qrcode';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { devicesApi, type PairingOut } from '../services/manage-api';
import { Copy, Check, ChevronDown, ChevronUp, CheckCircle2, Loader2, Smartphone } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { useTranslations } from 'next-intl';

interface ConnectDeviceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeviceConnected?: () => void;
  liveCount?: number;
}

const POLL_INTERVAL_MS = 2000;
const MAX_DEVICES = 10;

export function ConnectDeviceDialog({
  open,
  onOpenChange,
  onDeviceConnected
}: ConnectDeviceDialogProps) {
  const t = useTranslations('devicesConnect');
  const [count, setCount] = useState(1);
  const [pairings, setPairings] = useState<PairingOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [showQrIndex, setShowQrIndex] = useState<number | null>(null);
  const [qrDataUrls, setQrDataUrls] = useState<Record<number, string>>({});
  const [pairedIds, setPairedIds] = useState<Set<string>>(new Set());
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!open) {
      setPairings([]);
      setShowQrIndex(null);
      setQrDataUrls({});
      setPairedIds(new Set());
      setCopiedIndex(null);
    }
  }, [open]);

  const createLinks = useCallback(async () => {
    if (count < 1 || count > MAX_DEVICES) return;
    setLoading(true);
    try {
      const { pairings: list } = await devicesApi.pairBulk(count);
      setPairings(list);
    } catch {
      toast.error(t('errorCreate'));
    } finally {
      setLoading(false);
    }
  }, [count, t]);

  useEffect(() => {
    if (showQrIndex == null || !pairings[showQrIndex]) return;
    const url = pairings[showQrIndex].qr_url;
    QRCode.toDataURL(url, { width: 200, margin: 2 })
      .then((dataUrl) => setQrDataUrls((prev) => ({ ...prev, [showQrIndex]: dataUrl })))
      .catch(() => setQrDataUrls((prev) => ({ ...prev, [showQrIndex]: '' })));
  }, [showQrIndex, pairings]);

  useEffect(() => {
    if (!open || pairings.length === 0) return;
    const ids = pairings.map((p) => p.pairing_id).filter((id) => !pairedIds.has(id));
    if (ids.length === 0) return;
    const interval = setInterval(async () => {
      for (const id of ids) {
        try {
          const { status } = await devicesApi.pollPair(id);
          if (status === 'paired') {
            setPairedIds((prev) => new Set(prev).add(id));
            onDeviceConnected?.();
            toast.success(t('toastConnected'));
          }
        } catch {
          // ignore
        }
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [open, pairings, pairedIds, onDeviceConnected, t]);

  const copyUrl = (url: string, index: number) => {
    navigator.clipboard.writeText(url).then(
      () => {
        setCopiedIndex(index);
        setTimeout(() => setCopiedIndex(null), 2000);
      },
      () => toast.error(t('errorCreate'))
    );
  };

  const connectedCount = pairings.filter((p) => pairedIds.has(p.pairing_id)).length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="z-[1000] max-w-md max-h-[90vh] overflow-y-auto" onInteractOutside={() => {}}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Smartphone className="size-5" />
            {t('title')}
          </DialogTitle>
        </DialogHeader>

        {pairings.length === 0 ? (
          <div className="flex flex-col gap-4 pt-2">
            <p className="text-sm text-muted-foreground">
              {t.rich('description', { strong: (c) => <strong>{c}</strong> })}
            </p>
            <div className="space-y-2">
              <Label>{t('countLabel', { max: MAX_DEVICES })}</Label>
              <Input
                type="number"
                min={1}
                max={MAX_DEVICES}
                value={count}
                onChange={(e) => setCount(Math.min(MAX_DEVICES, Math.max(1, parseInt(e.target.value, 10) || 1)))}
              />
            </div>
            <Button className="w-full" onClick={createLinks} disabled={loading}>
              {loading ? t('creating') : t('createLinks')}
            </Button>
            <Button variant="outline" className="w-full" onClick={() => onOpenChange(false)}>
              {t('cancel')}
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-4 pt-2">
            <p className="text-sm text-muted-foreground">
              {t.rich('instructionHint', { strong: (c) => <strong>{c}</strong> })}
            </p>

            {/* Progress */}
            {pairings.length > 1 && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>{t('progressLabel')}</span>
                  <Badge
                    variant={connectedCount === pairings.length ? 'default' : 'secondary'}
                    className={cn(connectedCount === pairings.length && 'bg-green-500 text-white')}
                  >
                    {t('progressCount', { connected: connectedCount, total: pairings.length })}
                  </Badge>
                </div>
                <Progress value={(connectedCount / pairings.length) * 100} />
              </div>
            )}

            <div className="space-y-3">
              {pairings.map((p, i) => {
                const isPaired = pairedIds.has(p.pairing_id);
                const showQr = showQrIndex === i;
                return (
                  <div
                    key={p.pairing_id}
                    className={cn(
                      'rounded-lg border p-3 transition-colors duration-300',
                      isPaired ? 'border-green-500/50 bg-green-500/5' : 'border-border'
                    )}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      {isPaired ? (
                        <CheckCircle2 size={16} className="shrink-0 text-green-500" />
                      ) : (
                        <Loader2 size={16} className="shrink-0 animate-spin text-muted-foreground" />
                      )}
                      <span className={cn('flex-1 text-sm font-medium', isPaired && 'text-green-700 dark:text-green-400')}>
                        {isPaired ? t('deviceConnected', { index: i + 1 }) : t('deviceWaiting', { index: i + 1 })}
                      </span>
                      {!isPaired && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs"
                          onClick={() => setShowQrIndex(showQr ? null : i)}
                        >
                          {showQr ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          {showQr ? t('hideQr') : t('showQr')}
                        </Button>
                      )}
                    </div>

                    {!isPaired && (
                      <>
                        <div className="flex gap-2">
                          <Input readOnly value={p.qr_url} className="font-mono text-xs flex-1" />
                          <Button size="icon" variant="outline" className="shrink-0" onClick={() => copyUrl(p.qr_url, i)}>
                            {copiedIndex === i ? <Check size={14} /> : <Copy size={14} />}
                          </Button>
                        </div>
                        {showQr && (
                          <div className="mt-2 flex justify-center">
                            {qrDataUrls[i] ? (
                              <img
                                src={qrDataUrls[i]}
                                alt={`QR ${i + 1}`}
                                className="rounded border bg-white p-1"
                                width={200}
                                height={200}
                              />
                            ) : (
                              <div className="flex h-[200px] w-[200px] items-center justify-center rounded border bg-muted text-xs text-muted-foreground">
                                {t('generatingQr')}
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => { setPairings([]); setPairedIds(new Set()); }}>
                {t('createNewLinks')}
              </Button>
              <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)}>
                {t('close')}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
