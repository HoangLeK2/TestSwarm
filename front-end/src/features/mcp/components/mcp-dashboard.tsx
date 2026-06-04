'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, KeyRound, Plus, ShieldAlert } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import {
  createMcpToken,
  getMcpAuditLog,
  getMcpTokens,
  revokeMcpToken
} from '@/features/mcp/services/api';
import { usePermission } from '@/features/auth/hooks/use-permission';

function TokenDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations('mcpFeature');
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [consent, setConsent] = useState(false);
  const [createdToken, setCreatedToken] = useState<string | null>(null);

  const { mutate, isPending } = useMutation({
    mutationFn: () =>
      createMcpToken({
        name,
        scope_type: 'user',
        preview_consent: consent
      }),
    onSuccess: (result) => {
      setCreatedToken(result.token);
      qc.invalidateQueries({ queryKey: ['mcp-tokens'] });
    }
  });

  const close = () => {
    setName('');
    setConsent(false);
    setCreatedToken(null);
    onOpenChange(false);
  };

  const copyToken = async () => {
    if (!createdToken) return;
    await navigator.clipboard.writeText(createdToken);
    toast.success(t('copied'));
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
    >
      <DialogContent className='max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('createToken')}</DialogTitle>
          <DialogDescription>{t('createTokenDescription')}</DialogDescription>
        </DialogHeader>
        {createdToken ? (
          <div className='space-y-3'>
            <code className='block break-all rounded-md bg-muted p-3 text-xs'>
              {createdToken}
            </code>
            <Button type='button' variant='outline' onClick={copyToken}>
              <Copy className='mr-2 size-4' />
              {t('copyToken')}
            </Button>
          </div>
        ) : (
          <div className='space-y-4'>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t('tokenName')}
            />
            <label className='flex items-start gap-2 text-sm'>
              <Checkbox
                checked={consent}
                onCheckedChange={(value) => setConsent(value === true)}
              />
              <span>{t('consent')}</span>
            </label>
          </div>
        )}
        <DialogFooter>
          <Button type='button' variant='outline' onClick={close}>
            {t('close')}
          </Button>
          {!createdToken ? (
            <Button
              type='button'
              disabled={!name.trim() || !consent || isPending}
              onClick={() => mutate()}
            >
              <Plus className='mr-2 size-4' />
              {t('create')}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type McpTab = 'tokens' | 'audit';

function tokenStatusLabel(
  status: string,
  t: ReturnType<typeof useTranslations<'mcpFeature'>>
) {
  if (status === 'active') return t('statusActive');
  if (status === 'revoked') return t('statusRevoked');
  return status;
}

function auditResultLabel(
  code: string,
  t: ReturnType<typeof useTranslations<'mcpFeature'>>
) {
  if (code === 'success') return t('resultSuccess');
  if (code === 'error' || code === 'failure') return t('resultFailure');
  return code;
}

export function McpDashboard({
  initialTab = 'tokens'
}: {
  initialTab?: McpTab;
}) {
  const t = useTranslations('mcpFeature');
  const qc = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [tab, setTab] = useState<McpTab>(initialTab);
  const canManageMcp = usePermission('mcp', 'manage');
  const tokens = useQuery({ queryKey: ['mcp-tokens'], queryFn: getMcpTokens });
  const audit = useQuery({ queryKey: ['mcp-audit'], queryFn: getMcpAuditLog });

  const revoke = useMutation({
    mutationFn: revokeMcpToken,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mcp-tokens'] })
  });

  const tokenRows = tokens.data?.tokens ?? [];
  const auditRows = audit.data?.entries ?? [];

  return (
    <div className='space-y-4'>
      <div className='flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between'>
        <div className='space-y-1'>
          <h1 className='text-xl font-bold tracking-tight text-foreground'>
            {t('title')}
          </h1>
          <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
        </div>
        {canManageMcp ? (
          <Button onClick={() => setDialogOpen(true)}>
            <Plus className='mr-2 size-4' />
            {t('createToken')}
          </Button>
        ) : null}
      </div>

      <Tabs value={tab} onValueChange={(value) => setTab(value as McpTab)}>
        <TabsList>
          <TabsTrigger value='tokens'>{t('tabs.tokens')}</TabsTrigger>
          <TabsTrigger value='audit'>{t('tabs.audit')}</TabsTrigger>
        </TabsList>
        <TabsContent value='tokens' className='mt-4'>
          <div className='rounded-lg border'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('token')}</TableHead>
                  <TableHead>{t('scope')}</TableHead>
                  <TableHead>{t('status')}</TableHead>
                  <TableHead className='w-[90px]' />
                </TableRow>
              </TableHeader>
              <TableBody>
                {tokenRows.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className='py-8 text-center text-sm text-muted-foreground'
                    >
                      {t('emptyTokens')}
                    </TableCell>
                  </TableRow>
                ) : (
                  tokenRows.map((token) => (
                    <TableRow key={token.id}>
                      <TableCell>
                        <div className='flex items-center gap-2 font-medium'>
                          <KeyRound className='size-4 text-muted-foreground' />
                          {token.name}
                        </div>
                        <code className='text-xs text-muted-foreground'>
                          {token.prefix}
                        </code>
                      </TableCell>
                      <TableCell>{t('scopeUser')}</TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            token.status === 'active' ? 'secondary' : 'outline'
                          }
                        >
                          {tokenStatusLabel(token.status, t)}
                        </Badge>
                      </TableCell>
                      <TableCell className='text-right'>
                        {canManageMcp &&
                        token.status === 'active' &&
                        token.source !== 'env' ? (
                          <Button
                            size='sm'
                            variant='outline'
                            onClick={() => revoke.mutate(token.id)}
                          >
                            {t('revoke')}
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
        <TabsContent value='audit' className='mt-4'>
          <div className='rounded-lg border'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('auditAction')}</TableHead>
                  <TableHead>{t('result')}</TableHead>
                  <TableHead>{t('session')}</TableHead>
                  <TableHead>{t('latency')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {auditRows.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className='py-8 text-center text-sm text-muted-foreground'
                    >
                      {t('emptyAudit')}
                    </TableCell>
                  </TableRow>
                ) : (
                  auditRows.map((entry, index) => (
                    <TableRow
                      key={`${entry.started_at}-${entry.tool_name}-${index}`}
                    >
                      <TableCell className='font-mono text-xs'>
                        {entry.tool_name}
                      </TableCell>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <ShieldAlert className='size-4 text-muted-foreground' />
                          <Badge
                            variant={
                              entry.result_code === 'success'
                                ? 'secondary'
                                : 'destructive'
                            }
                          >
                            {auditResultLabel(entry.result_code, t)}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell className='font-mono text-xs'>
                        {entry.session_id || t('sessionNone')}
                      </TableCell>
                      <TableCell>
                        {t('latencyMs', { ms: entry.latency_ms })}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>
      <TokenDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
