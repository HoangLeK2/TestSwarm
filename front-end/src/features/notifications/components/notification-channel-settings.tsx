'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  Bell,
  ExternalLink,
  Loader2,
  Pencil,
  Plus,
  Send,
  Trash2
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useResourcePermissions } from '@/features/auth/hooks/use-permission';
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
  useTestNotificationChannelDraft,
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
    type: channel.type as NotificationChannelType,
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

function ChannelTypeSetup({
  form,
  setForm,
  t,
  canTest,
  testing,
  onTestConnection
}: {
  form: FormState;
  setForm: (updater: (current: FormState) => FormState) => void;
  t: ReturnType<typeof useTranslations<'notificationsFeature'>>;
  canTest: boolean;
  testing: boolean;
  onTestConnection: () => void;
}) {
  if (form.type === 'in_app') {
    return (
      <div className='rounded-lg border border-dashed bg-muted/30 px-4 py-3 text-sm text-muted-foreground'>
        {t('inAppHint')}
      </div>
    );
  }

  if (form.type === 'telegram') {
    return (
      <div className='space-y-4 rounded-lg border bg-muted/20 p-4'>
        <div>
          <p className='text-sm font-medium'>{t('telegramSetupTitle')}</p>
          <p className='mt-1 text-xs text-muted-foreground'>
            {t('telegramSetupIntro')}
          </p>
        </div>
        <ol className='list-decimal space-y-1 pl-4 text-xs text-muted-foreground'>
          <li>{t('telegramStep1')}</li>
          <li>{t('telegramStep2')}</li>
          <li>{t('telegramStep3')}</li>
        </ol>
        <a
          href='https://t.me/BotFather'
          target='_blank'
          rel='noopener noreferrer'
          className='inline-flex items-center gap-1 text-xs text-primary hover:underline'
        >
          @BotFather
          <ExternalLink className='size-3' />
        </a>
        <div className='grid gap-3'>
          <div className='grid gap-2'>
            <Label htmlFor='telegram-token'>{t('fields.botToken')}</Label>
            <Input
              id='telegram-token'
              type='password'
              autoComplete='off'
              value={form.botToken}
              placeholder={t('placeholders.botToken')}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  botToken: event.target.value
                }))
              }
            />
            <p className='text-xs text-muted-foreground'>{t('botTokenHint')}</p>
          </div>
          <div className='grid gap-2'>
            <Label htmlFor='telegram-chat'>{t('fields.chatId')}</Label>
            <Input
              id='telegram-chat'
              value={form.chatId}
              placeholder={t('placeholders.chatId')}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  chatId: event.target.value
                }))
              }
            />
            <p className='text-xs text-muted-foreground'>{t('chatIdHint')}</p>
          </div>
        </div>
        {canTest ? (
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={onTestConnection}
            disabled={testing}
          >
            {testing ? <Loader2 className='size-4 animate-spin' /> : <Send className='size-4' />}
            {t('actions.testConnection')}
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className='space-y-4 rounded-lg border bg-muted/20 p-4'>
      <div>
        <p className='text-sm font-medium'>{t('webhookSetupTitle')}</p>
        <p className='mt-1 text-xs text-muted-foreground'>
          {t('webhookSetupIntro')}
        </p>
      </div>
      <div className='grid gap-2'>
        <Label htmlFor='webhook-url'>{t('fields.webhookUrl')}</Label>
        <Input
          id='webhook-url'
          type='url'
          value={form.webhookUrl}
          placeholder={t('placeholders.webhookUrl')}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              webhookUrl: event.target.value
            }))
          }
        />
      </div>
      <div className='grid gap-2'>
        <Label htmlFor='webhook-headers'>{t('fields.headersJson')}</Label>
        <Textarea
          id='webhook-headers'
          value={form.headersText}
          placeholder='{}'
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              headersText: event.target.value
            }))
          }
          className='min-h-24 font-mono text-xs'
        />
        <p className='text-xs text-muted-foreground'>{t('headersHint')}</p>
      </div>
      {canTest ? (
        <Button
          type='button'
          variant='outline'
          size='sm'
          onClick={onTestConnection}
          disabled={testing}
        >
          {testing ? <Loader2 className='size-4 animate-spin' /> : <Send className='size-4' />}
          {t('actions.testConnection')}
        </Button>
      ) : null}
    </div>
  );
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
  const perms = useResourcePermissions('notifications');
  const [form, setForm] = useState<FormState>(() => channelToForm(channel));
  const createChannel = useCreateNotificationChannel();
  const updateChannel = useUpdateNotificationChannel();
  const testChannelDraft = useTestNotificationChannelDraft();
  const isEdit = !!channel;
  const saving = createChannel.isPending || updateChannel.isPending;
  const testing = testChannelDraft.isPending;

  useEffect(() => {
    if (open) {
      setForm(channelToForm(channel));
    }
  }, [open, channel]);

  const toggleEvent = (event: string, checked: boolean) => {
    setForm((current) => ({
      ...current,
      events: checked
        ? Array.from(new Set([...current.events, event]))
        : current.events.filter((item) => item !== event)
    }));
  };

  const testConnection = () => {
    try {
      if (form.type === 'telegram') {
        if (!form.botToken.trim()) {
          toast.error(t('errors.telegramTokenRequired'));
          return;
        }
        if (!form.chatId.trim()) {
          toast.error(t('errors.telegramChatRequired'));
          return;
        }
      }
      if (form.type === 'webhook' && !form.webhookUrl.trim()) {
        toast.error(t('errors.webhookUrlRequired'));
        return;
      }
      const payload = formToPayload(form);
      testChannelDraft
        .mutateAsync({ type: payload.type, config: payload.config ?? {} })
        .then(() => toast.success(t('toasts.testSent')))
        .catch((err) =>
          toast.error(err?.response?.data?.detail ?? t('errors.testFailed'))
        );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t('errors.invalidConfig')
      );
    }
  };

  const submit = () => {
    try {
      const payload = formToPayload(form);
      if (!payload.name) {
        toast.error(t('errors.nameRequired'));
        return;
      }
      if ((payload.events ?? []).length === 0) {
        toast.error(t('errors.eventRequired'));
        return;
      }
      if (form.type === 'telegram') {
        if (!form.botToken.trim()) {
          toast.error(t('errors.telegramTokenRequired'));
          return;
        }
        if (!form.chatId.trim()) {
          toast.error(t('errors.telegramChatRequired'));
          return;
        }
      }
      if (form.type === 'webhook' && !form.webhookUrl.trim()) {
        toast.error(t('errors.webhookUrlRequired'));
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
      <DialogContent className='flex max-h-[min(90vh,720px)] max-w-2xl flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl'>
        <DialogHeader className='shrink-0 border-b px-6 py-4'>
          <DialogTitle>
            {isEdit ? t('editChannel') : t('createChannel')}
          </DialogTitle>
        </DialogHeader>

        <div className='min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4'>
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
                disabled={form.type === 'webhook'}
                onValueChange={(value) =>
                  setForm((current) => ({
                    ...current,
                    type: value as NotificationChannelType
                  }))
                }
              >
                <SelectTrigger className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className='z-[10001]'>
                  <SelectItem value='in_app'>{t('types.in_app')}</SelectItem>
                  <SelectItem value='telegram'>
                    {t('types.telegram')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className='grid gap-2'>
              <Label htmlFor='notification-channel-enabled'>
                {t('fields.enabled')}
              </Label>
              <div className='flex h-9 items-center justify-between rounded-md border border-input px-3 shadow-xs'>
                <span className='text-sm text-muted-foreground'>
                  {form.enabled ? t('status.on') : t('status.off')}
                </span>
                <Switch
                  id='notification-channel-enabled'
                  checked={form.enabled}
                  onCheckedChange={(enabled) =>
                    setForm((current) => ({ ...current, enabled }))
                  }
                />
              </div>
            </div>
          </div>
          <ChannelTypeSetup
            form={form}
            setForm={setForm}
            t={t}
            canTest={perms.canExecute && (form.type === 'telegram' || form.type === 'webhook')}
            testing={testing}
            onTestConnection={testConnection}
          />
          <div className='grid gap-2'>
            <Label>{t('fields.events')}</Label>
            <div className='grid gap-2 rounded-md border p-3 sm:grid-cols-2'>
              {NOTIFICATION_EVENTS.map((eventName) => {
                const labelKey = eventLabelKey(eventName);
                const label = t.has(labelKey) ? t(labelKey) : eventName;
                return (
                  <Label
                    key={eventName}
                    className='flex cursor-pointer items-center text-xs font-normal'
                  >
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

        <DialogFooter className='shrink-0 border-t bg-background px-6 py-4'>
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

export function NotificationChannelSettings({
  embedded = false
}: {
  embedded?: boolean;
}) {
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
  const perms = useResourcePermissions('notifications');

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
        {embedded ? (
          <p className='text-sm text-muted-foreground'>
            {t('channelsTabHint')}
          </p>
        ) : (
          <div>
            <h1 className='text-xl font-semibold tracking-tight'>
              {t('title')}
            </h1>
            <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
          </div>
        )}
        {perms.canCreate ? (
          <Button size='sm' onClick={() => setCreateOpen(true)}>
            <Plus size={15} />
            {t('addChannel')}
          </Button>
        ) : null}
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
                  <TableCell>
                    {typeLabel(channel.type as NotificationChannelType, t)}
                  </TableCell>
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
                      {perms.canExecute ? (
                        <Button
                          variant='ghost'
                          size='icon'
                          className='size-8'
                          onClick={() => runTest(channel.id)}
                          disabled={testChannel.isPending}
                        >
                          <Send size={14} />
                        </Button>
                      ) : null}
                      {perms.canUpdate ? (
                        <Button
                          variant='ghost'
                          size='icon'
                          className='size-8'
                          onClick={() => setEditing(channel)}
                        >
                          <Pencil size={14} />
                        </Button>
                      ) : null}
                      {perms.canDelete ? (
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
                              .catch(() =>
                                toast.error(t('errors.deleteFailed'))
                              );
                          }}
                        >
                          <Trash2 size={14} />
                        </Button>
                      ) : null}
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
