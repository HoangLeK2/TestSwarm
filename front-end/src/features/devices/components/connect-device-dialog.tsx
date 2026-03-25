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
import { devicesApi, type PairingOut } from '../services/manage-api';
import { Smartphone, Copy, Check, ChevronDown, ChevronUp } from 'lucide-react';
import { toast } from 'sonner';

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
      toast.error('Không tạo được link. Thử lại.');
    } finally {
      setLoading(false);
    }
  }, [count]);

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
    const t = setInterval(async () => {
      for (const id of ids) {
        try {
          const { status } = await devicesApi.pollPair(id);
          if (status === 'paired') {
            setPairedIds((prev) => new Set(prev).add(id));
            onDeviceConnected?.();
          }
        } catch {
          // ignore
        }
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [open, pairings, pairedIds, onDeviceConnected]);

  const copyUrl = (url: string, index: number) => {
    navigator.clipboard.writeText(url).then(
      () => {
        setCopiedIndex(index);
        toast.success('Đã copy link');
        setTimeout(() => setCopiedIndex(null), 2000);
      },
      () => toast.error('Copy thất bại')
    );
  };

  const connectedCount = pairings.filter((p) => pairedIds.has(p.pairing_id)).length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="z-[1000] max-w-md max-h-[90vh] overflow-y-auto" onInteractOutside={() => {}}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Smartphone className="size-5" />
            Kết nối thiết bị lên cloud
          </DialogTitle>
        </DialogHeader>

        {pairings.length === 0 ? (
          <div className="flex flex-col gap-4 pt-2">
            <p className="text-sm text-muted-foreground">
              Server chạy trên cloud nên thiết bị phải <strong>chủ động kết nối lên server</strong>. Chọn số thiết bị, tạo link — mỗi điện thoại mở app <strong>STFService</strong> và <strong>dán link</strong> (hoặc quét QR) để kết nối. Không cần cùng mạng.
            </p>
            <div className="space-y-2">
              <Label>Số thiết bị cần kết nối (1–{MAX_DEVICES})</Label>
              <Input
                type="number"
                min={1}
                max={MAX_DEVICES}
                value={count}
                onChange={(e) => setCount(Math.min(MAX_DEVICES, Math.max(1, parseInt(e.target.value, 10) || 1)))}
              />
            </div>
            <Button className="w-full" onClick={createLinks} disabled={loading}>
              {loading ? 'Đang tạo…' : 'Tạo link kết nối'}
            </Button>
            <Button variant="outline" className="w-full" onClick={() => onOpenChange(false)}>
              Hủy
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-4 pt-2">
            <p className="text-sm text-muted-foreground">
              Trên mỗi điện thoại: mở app <strong>STFService</strong> → dán link bên dưới (hoặc bấm &quot;Hiện QR&quot; để quét). Thiết bị sẽ kết nối lên cloud.
            </p>
            {connectedCount > 0 && (
              <p className="text-sm text-green-600 dark:text-green-400">
                Đã kết nối: {connectedCount}/{pairings.length} thiết bị.
              </p>
            )}
            <div className="space-y-3">
              {pairings.map((p, i) => {
                const isPaired = pairedIds.has(p.pairing_id);
                const showQr = showQrIndex === i;
                return (
                  <div
                    key={p.pairing_id}
                    className={`rounded-lg border p-3 ${isPaired ? 'border-green-500/50 bg-green-500/5' : ''}`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-sm font-medium">
                        Thiết bị {i + 1} {isPaired && '✓ Đã kết nối'}
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs"
                        onClick={() => setShowQrIndex(showQr ? null : i)}
                      >
                        {showQr ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        {showQr ? 'Ẩn QR' : 'Hiện QR'}
                      </Button>
                    </div>
                    <div className="flex gap-2">
                      <Input
                        readOnly
                        value={p.qr_url}
                        className="font-mono text-xs flex-1"
                      />
                      <Button
                        size="icon"
                        variant="outline"
                        className="shrink-0"
                        onClick={() => copyUrl(p.qr_url, i)}
                      >
                        {copiedIndex === i ? <Check size={14} /> : <Copy size={14} />}
                      </Button>
                    </div>
                    {showQr && (
                      <div className="mt-2 flex justify-center">
                        {qrDataUrls[i] ? (
                          <img
                            src={qrDataUrls[i]}
                            alt={`QR thiết bị ${i + 1}`}
                            className="rounded border bg-white p-1"
                            width={200}
                            height={200}
                          />
                        ) : (
                          <div className="flex h-[200px] w-[200px] items-center justify-center rounded border bg-muted text-xs text-muted-foreground">
                            Đang tạo QR…
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => { setPairings([]); setPairedIds(new Set()); }}>
                Tạo link mới
              </Button>
              <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)}>
                Đóng
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
