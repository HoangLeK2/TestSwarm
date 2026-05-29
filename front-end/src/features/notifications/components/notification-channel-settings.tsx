'use client';

import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Bell, Loader2, Pencil, Plus, Send, Trash2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import {
  NOTIFICATION_EVENTS,
  type NotificationChannel,
  type NotificationChannelInput,
  type NotificationChannelType
} from '../services/api';
import {
  useCreateNotificationChannel,
  useDeleteNotificationChannel,
  useNotificationChannels,
  useTestNotificationChannel,
  useUpdateNotificationChannel
} from '../hooks/use-notifications';

type FormState = {
  name: string;
  type: NotificationChannelType;
  enabled: boolean;
  events: string[];
  botToken: string;
  chatId: string;
  webhookUrl: string;
  headersText: string;
};

const DEFAULT_FORM: FormState = {
  name: '',
  type: 'in_app',
  enabled: true,
  events: [...NOTIFICATION_EVENTS],
  botToken: '',
  chatId: '',
  webhookUrl: '',
  headersText: ''
};

function channelToForm(channel?: NotificationChannel): FormState {
  if (!channel) return DEFAULT_FORM;
  return {
    name: channel.name,
    type: channel.type,
    enabled: channel.is_enabled,
    events: channel.events?.length ? channel.events : [...NOTIFICATION_EVENTS],
    botToken: String(channel.config?.bot_token ?? ''),
    chatId: String(channel.config?.chat_id ?? ''),
    webhookUrl: String(channel.config?.url ?? ''),
    headersText: JSON.stringify(channel.config?.headers ?? {}, null, 2)
  };
}

function eventLabelKey(eventName: string) {
  return `eventLabels.${eventName.replace(/\./g, '_')}` as const;
}

function formToPayload(form: FormState): NotificationChannelInput {
  let config: Record<string, unknown> = {};
  if (form.type === 'telegram') {
    config = { bot_token: form.botToken.trim(), chat_id: form.chatId.trim() };
  } else if (form.type === 'webhook') {
    let headers: Record<string, unknown> = {};
    if (form.headersText.trim()) {
      headers = JSON.parse(form.headersText) as Record<string, unknown>;
    }
    config = { url: form.webhookUrl.trim(), headers };
  }
  return {
    name: form.name.trim(),
    type: form.type,
    config,
    events: form.events,
    is_enabled: form.enabled
  };
}

function typeLabel(
  type: NotificationChannelType,
  t: ReturnType<typeof useTranslations>
) {
  if (type === 'telegram') return t('types.telegram');
  if (type === 'webhook') return t('types.webhook');
  return t('types.in_app');
}

function ChannelDialog({
  open,
  channel,
  onOpenChange
}: {
  open: boolean;
  channel?: NotificationChannel;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations('notificationsFeature');
  const [form, setForm] = useState<FormState>(() => channelToForm(channel));
  const createChannel = useCreateNotificationChannel();
  const updateChannel = useUpdateNotificationChannel();
  const isEdit = !!channel;
  const saving = createChannel.isPending || updateChannel.isPending;

  const toggleEvent = (event: string, checked: boolean) => {
    setForm((current) => ({
      ...current,
      events: checked
        ? Array.from(new Set([...current.events, event]))
        : current.events.filter((item) => item !== event)
    }));
  };

  const submit = () => {
    try {
      const payload = formToPayload(form);
      if (!payload.name) {
        toast.error(t('errors.nameRequired'));
        return;
      }
      if (payload.events.length === 0) {
        toast.error(t('errors.eventRequired'));
        return;
      }
      const mutation = isEdit
        ? updateChannel.mutateAsync({ id: channel.id, data: payload })
        : createChannel.mutateAsync(payload);
      mutation
        .then(() => {
          toast.success(
            isEdit ? t('toasts.channelUpdated') : t('toasts.channelCreated')
          );
          onOpenChange(false);
        })
        .catch((err) =>
          toast.error(err?.response?.data?.detail ?? t('errors.saveFailed'))
        );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t('errors.invalidConfig')
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-2xl'>
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t('editChannel') : t('createChannel')}
          </DialogTitle>
        </DialogHeader>
        <div className='grid gap-4'>
          <div className='grid gap-2'>
            <Label htmlFor='notification-channel-name'>
              {t('fields.name')}
            </Label>
            <Input
              id='notification-channel-name'
              value={form.name}
              placeholder={t('placeholders.channelName')}
              onChange={(event) =>
                setForm((current) => ({ ...current, name: event.target.value }))
              }
            />
          </div>
          <div className='grid gap-2 sm:grid-cols-2'>
            <div className='grid gap-2'>
              <Label>{t('fields.type')}</Label>
              <Select
                value={form.type}
                onValueChange={(value) =>
                  setForm((current) => ({
                    ...current,
                    type: value as NotificationChannelType
                  }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='in_app'>{t('types.in_app')}</SelectItem>
                  <SelectItem value='telegram'>
                    {t('types.telegram')}
                  </SelectItem>
                  <SelectItem value='webhook'>{t('types.webhook')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className='flex items-end justify-between rounded-md border px-3 py-2'>
              <Label htmlFor='notification-channel-enabled'>
                {t('fields.enabled')}
              </Label>
              <Switch
                id='notification-channel-enabled'
                checked={form.enabled}
                onCheckedChange={(enabled) =>
                  setForm((current) => ({ ...current, enabled }))
                }
              />
            </div>
          </div>
          {form.type === 'telegram' ? (
            <div className='grid gap-2 sm:grid-cols-2'>
              <div className='grid gap-2'>
                <Label htmlFor='telegram-token'>{t('fields.botToken')}</Label>
                <Input
                  id='telegram-token'
                  value={form.botToken}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      botToken: event.target.value
                    }))
                  }
                />
              </div>
              <div className='grid gap-2'>
                <Label htmlFor='telegram-chat'>{t('fields.chatId')}</Label>
                <Input
                  id='telegram-chat'
                  value={form.chatId}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      chatId: event.target.value
                    }))
                  }
                />
              </div>
            </div>
          ) : null}
          {form.type === 'webhook' ? (
            <div className='grid gap-2'>
              <Label htmlFor='webhook-url'>{t('fields.webhookUrl')}</Label>
              <Input
                id='webhook-url'
                value={form.webhookUrl}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    webhookUrl: event.target.value
                  }))
                }
              />
              <Label htmlFor='webhook-headers'>{t('fields.headersJson')}</Label>
              <Textarea
                id='webhook-headers'
                value={form.headersText}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    headersText: event.target.value
                  }))
                }
                className='min-h-24 font-mono text-xs'
              />
            </div>
          ) : null}
          <div className='grid gap-2'>
            <Label>{t('fields.events')}</Label>
            <div className='grid gap-2 rounded-md border p-3 sm:grid-cols-2'>
              {NOTIFICATION_EVENTS.map((eventName) => {
                const labelKey = eventLabelKey(eventName);
                const label = t.has(labelKey) ? t(labelKey) : eventName;
                return (
                  <Label key={eventName} className='text-xs font-normal'>
                    <Checkbox
                      checked={form.events.includes(eventName)}
                      onCheckedChange={(checked) =>
                        toggleEvent(eventName, checked === true)
                      }
                    />
                    <span className='ml-2'>{label}</span>
                  </Label>
                );
              })}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            {t('actions.cancel')}
          </Button>
          <Button onClick={submit} disabled={saving}>
            {saving ? <Loader2 className='size-4 animate-spin' /> : null}
            {t('actions.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function formatEventBadge(
  eventName: string,
  t: ReturnType<typeof useTranslations<'notificationsFeature'>>
) {
  const labelKey = eventLabelKey(eventName);
  return t.has(labelKey) ? t(labelKey) : eventName;
}

export function NotificationChannelSettings() {
  const t = useTranslations('notificationsFeature');
  const { data: channels = [], isLoading, error } = useNotificationChannels();
  const [editing, setEditing] = useState<NotificationChannel | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const deleteChannel = useDeleteNotificationChannel();
  const testChannel = useTestNotificationChannel();
  const sortedChannels = useMemo(
    () => [...channels].sort((a, b) => a.name.localeCompare(b.name)),
    [channels]
  );

  const runTest = (id: string) => {
    testChannel
      .mutateAsync(id)
      .then(() => toast.success(t('toasts.testSent')))
      .catch((err) =>
        toast.error(err?.response?.data?.detail ?? t('errors.testFailed'))
      );
  };

  return (
    <div className='space-y-6'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div>
          <h1 className='text-xl font-semibold tracking-tight'>{t('title')}</h1>
          <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
        </div>
        <Button size='sm' onClick={() => setCreateOpen(true)}>
          <Plus size={15} />
          {t('addChannel')}
        </Button>
      </div>
      {isLoading ? (
        <div className='flex items-center gap-2 text-sm text-muted-foreground'>
          <Loader2 size={15} className='animate-spin' />
          {t('loadingChannels')}
        </div>
      ) : error ? (
        <div className='text-sm text-destructive'>
          {t('errors.loadChannels')}
        </div>
      ) : sortedChannels.length === 0 ? (
        <div className='rounded-lg border border-dashed bg-muted/20 p-12 text-center'>
          <Bell className='mx-auto mb-3 size-10 text-muted-foreground' />
          <div className='text-sm font-medium'>{t('noChannels')}</div>
        </div>
      ) : (
        <div className='rounded-lg border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('fields.name')}</TableHead>
                <TableHead>{t('fields.type')}</TableHead>
                <TableHead>{t('fields.events')}</TableHead>
                <TableHead>{t('fields.enabled')}</TableHead>
                <TableHead className='w-32 text-right'>
                  {t('fields.actions')}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedChannels.map((channel) => (
                <TableRow key={channel.id}>
                  <TableCell className='font-medium'>{channel.name}</TableCell>
                  <TableCell>{typeLabel(channel.type, t)}</TableCell>
                  <TableCell>
                    <div className='flex max-w-[420px] flex-wrap gap-1'>
                      {channel.events.slice(0, 4).map((eventName) => (
                        <Badge
                          key={eventName}
                          variant='outline'
                          className='text-[10px]'
                        >
                          {formatEventBadge(eventName, t)}
                        </Badge>
                      ))}
                      {channel.events.length > 4 ? (
                        <Badge variant='secondary' className='text-[10px]'>
                          +{channel.events.length - 4}
                        </Badge>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={channel.is_enabled ? 'default' : 'outline'}>
                      {channel.is_enabled ? t('status.on') : t('status.off')}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className='flex justify-end gap-1'>
                      <Button
                        variant='ghost'
                        size='icon'
                        className='size-8'
                        onClick={() => runTest(channel.id)}
                        disabled={testChannel.isPending}
                      >
                        <Send size={14} />
                      </Button>
                      <Button
                        variant='ghost'
                        size='icon'
                        className='size-8'
                        onClick={() => setEditing(channel)}
                      >
                        <Pencil size={14} />
                      </Button>
                      <Button
                        variant='destructive-ghost'
                        size='icon'
                        className='size-8'
                        onClick={() => {
                          deleteChannel
                            .mutateAsync(channel.id)
                            .then(() =>
                              toast.success(t('toasts.channelDeleted'))
                            )
                            .catch(() => toast.error(t('errors.deleteFailed')));
                        }}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {createOpen ? (
        <ChannelDialog open={createOpen} onOpenChange={setCreateOpen} />
      ) : null}
      {editing ? (
        <ChannelDialog
          open={!!editing}
          channel={editing}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}
