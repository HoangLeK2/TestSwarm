'use client';

import { useCallback, useRef, useState } from 'react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Bell, WifiOff, Wifi, AlertTriangle, Skull, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import type { DeviceEvent } from '../types';
import { fetchEvents } from '../services/api';

interface EventLogPanelProps {
  /** Real-time events received via WS during this session. */
  realtimeEvents: DeviceEvent[];
  unreadCount: number;
  onOpen: () => void;
}

const EVENT_ICONS: Record<string, typeof WifiOff> = {
  disconnected: WifiOff,
  connected: Wifi,
  reconnected: Wifi,
  error: AlertTriangle,
  dead: Skull,
};

const EVENT_COLORS: Record<string, string> = {
  disconnected: 'text-destructive',
  connected: 'text-emerald-500',
  reconnected: 'text-emerald-500',
  error: 'text-amber-500',
  dead: 'text-destructive',
};

function timeAgo(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 0) return 'just now';
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

/** Short human-readable serial: "172.16.0.213:39951" → "...213:39951", long hex → last 8 chars */
function shortSerial(serial: string): string {
  if (serial.includes(':')) {
    // IP:port — show last octet + port
    const parts = serial.split('.');
    if (parts.length === 4) return `...${parts[3]}`;
    return serial.length > 16 ? `...${serial.slice(-12)}` : serial;
  }
  // Hex serial — show last 8 chars
  return serial.length > 12 ? `...${serial.slice(-8)}` : serial;
}

/** Device display name: "Samsung Galaxy S21 (...931e8222)" */
function deviceName(evt: DeviceEvent): { name: string; serial: string } {
  const parts = [evt.device_brand, evt.device_model].filter(Boolean);
  const short = shortSerial(evt.serial);
  if (parts.length > 0) return { name: parts.join(' '), serial: short };
  return { name: short, serial: '' };
}

const PAGE_SIZE = 50;

export function EventLogPanel({ realtimeEvents, unreadCount, onOpen }: EventLogPanelProps) {
  const t = useTranslations('devicesFarm.eventLog');
  const [filterEvent, setFilterEvent] = useState<string>('all');
  const [filterSerial, setFilterSerial] = useState<string>('all');

  // DB history
  const [dbEvents, setDbEvents] = useState<DeviceEvent[]>([]);
  const [dbLoading, setDbLoading] = useState(false);
  const [dbOffset, setDbOffset] = useState(0);
  const [dbHasMore, setDbHasMore] = useState(true);
  const hasFetchedRef = useRef(false);

  // Fetch first page from DB when panel opens
  const loadFromDb = useCallback(async (offset: number, reset: boolean) => {
    setDbLoading(true);
    try {
      const res = await fetchEvents({ limit: PAGE_SIZE, offset });
      const newEvents = res.events ?? [];
      setDbEvents((prev) => reset ? newEvents : [...prev, ...newEvents]);
      setDbOffset(offset + newEvents.length);
      setDbHasMore(newEvents.length >= PAGE_SIZE);
    } catch {
      // Silently fail — in-memory events still available
    } finally {
      setDbLoading(false);
    }
  }, []);

  const handleOpenChange = useCallback((open: boolean) => {
    if (open) {
      onOpen();
      hasFetchedRef.current = true;
      setDbOffset(0);
      setDbHasMore(true);
      loadFromDb(0, true);
    }
  }, [onOpen, loadFromDb]);

  const handleLoadMore = useCallback(() => {
    if (!dbLoading && dbHasMore) {
      loadFromDb(dbOffset, false);
    }
  }, [dbLoading, dbHasMore, dbOffset, loadFromDb]);

  // Merge real-time events with DB events (deduplicate by id, newest first)
  const allEvents = (() => {
    const seen = new Set<string>();
    const merged: DeviceEvent[] = [];
    for (const evt of realtimeEvents) {
      if (!seen.has(evt.id)) { seen.add(evt.id); merged.push(evt); }
    }
    for (const evt of dbEvents) {
      if (!seen.has(evt.id)) { seen.add(evt.id); merged.push(evt); }
    }
    merged.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    return merged;
  })();

  const serials = Array.from(new Set(allEvents.map((e) => e.serial))).sort();
  const filtered = allEvents.filter((e) => {
    if (filterEvent !== 'all' && e.event !== filterEvent) return false;
    if (filterSerial !== 'all' && e.serial !== filterSerial) return false;
    return true;
  });

  return (
    <Sheet onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" className="relative gap-1.5">
          <Bell size={14} />
          <span className="hidden sm:inline text-[10px]">{t('title')}</span>
          {unreadCount > 0 && (
            <Badge
              variant="destructive"
              className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9px]"
            >
              {unreadCount > 99 ? '99+' : unreadCount}
            </Badge>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Bell size={16} />
            {t('title')}
            <Badge variant="outline" className="text-[10px]">
              {filtered.length} {t('events')}
            </Badge>
          </SheetTitle>
        </SheetHeader>

        {/* Filters */}
        <div className="flex gap-2 px-1 pb-2">
          <Select value={filterEvent} onValueChange={setFilterEvent}>
            <SelectTrigger className="h-7 text-[11px]">
              <SelectValue placeholder={t('filterEvent')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('allEvents')}</SelectItem>
              <SelectItem value="disconnected">{t('eventDisconnected')}</SelectItem>
              <SelectItem value="connected">{t('eventConnected')}</SelectItem>
              <SelectItem value="reconnected">{t('eventReconnected')}</SelectItem>
              <SelectItem value="error">{t('eventError')}</SelectItem>
              <SelectItem value="dead">{t('eventDead')}</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filterSerial} onValueChange={setFilterSerial}>
            <SelectTrigger className="h-7 text-[11px]">
              <SelectValue placeholder={t('filterDevice')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('allDevices')}</SelectItem>
              {serials.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Event list */}
        <ScrollArea className="flex-1">
          <div className="flex flex-col gap-1 px-1 pb-4">
            {dbLoading && filtered.length === 0 && (
              <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" />
                {t('loading')}
              </div>
            )}
            {!dbLoading && filtered.length === 0 && (
              <div className="py-12 text-center text-sm text-muted-foreground">
                {t('noEvents')}
              </div>
            )}
            {filtered.map((evt) => {
              const Icon = EVENT_ICONS[evt.event] ?? AlertTriangle;
              const color = EVENT_COLORS[evt.event] ?? 'text-muted-foreground';
              const { name, serial } = deviceName(evt);
              return (
                <div
                  key={evt.id}
                  className="flex items-start gap-2.5 rounded-md border border-border/50 bg-card/50 px-3 py-2"
                >
                  <Icon size={14} className={`mt-0.5 shrink-0 ${color}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-1.5">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className={`text-xs font-medium shrink-0 ${color}`}>
                          {t(`event_${evt.event}`)}
                        </span>
                        <span className="truncate text-xs text-foreground">
                          {name}
                        </span>
                        {serial && (
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {serial}
                          </span>
                        )}
                      </div>
                      <span className="shrink-0 text-[10px] text-muted-foreground/60">
                        {timeAgo(evt.created_at)}
                      </span>
                    </div>
                    {evt.reason && (
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {evt.reason}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Load more button */}
            {dbHasMore && filtered.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="mx-auto mt-2 text-[11px]"
                onClick={handleLoadMore}
                disabled={dbLoading}
              >
                {dbLoading ? (
                  <Loader2 size={14} className="mr-1.5 animate-spin" />
                ) : null}
                {t('loadMore')}
              </Button>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
