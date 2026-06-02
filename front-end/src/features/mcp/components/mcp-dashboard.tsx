'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Copy,
  KeyRound,
  Plus,
  ShieldAlert,
  Wrench
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
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
  getMcpTools,
  revokeMcpToken
} from '@/features/mcp/services/api';

function PreviewBanner({ contractVersion }: { contractVersion?: string }) {
  const t = useTranslations('mcpFeature');
  return (
    <Alert className='border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100'>
      <AlertTriangle className='size-4' />
      <AlertTitle>{t('previewTitle')}</AlertTitle>
      <AlertDescription>
        {t('previewDescription')}
        {contractVersion ? (
          <span className='ml-2 font-mono text-xs'>{contractVersion}</span>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

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
  const [scopeType, setScopeType] = useState<'device' | 'user'>('device');
  const [scopeRef, setScopeRef] = useState('');
  const [consent, setConsent] = useState(false);
  const [createdToken, setCreatedToken] = useState<string | null>(null);

  const { mutate, isPending } = useMutation({
    mutationFn: () =>
      createMcpToken({
        name,
        scope_type: scopeType,
        scope_ref: scopeRef || undefined,
        preview_consent: consent
      }),
    onSuccess: (result) => {
      setCreatedToken(result.token);
      qc.invalidateQueries({ queryKey: ['mcp-tokens'] });
    }
  });

  const close = () => {
    setName('');
    setScopeRef('');
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
            <Select
              value={scopeType}
              onValueChange={(value) =>
                setScopeType(value as 'device' | 'user')
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='device'>{t('scopeDevice')}</SelectItem>
                <SelectItem value='user'>{t('scopeUser')}</SelectItem>
              </SelectContent>
            </Select>
            <Input
              value={scopeRef}
              onChange={(event) => setScopeRef(event.target.value)}
              placeholder={t('scopeRef')}
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
              disabled={!consent || isPending}
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

type McpTab = 'tools' | 'tokens' | 'audit';

export function McpDashboard({
  initialTab = 'tools'
}: {
  initialTab?: McpTab;
}) {
  const t = useTranslations('mcpFeature');
  const qc = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [tab, setTab] = useState<McpTab>(initialTab);
  const tools = useQuery({ queryKey: ['mcp-tools'], queryFn: getMcpTools });
  const tokens = useQuery({ queryKey: ['mcp-tokens'], queryFn: getMcpTokens });
  const audit = useQuery({ queryKey: ['mcp-audit'], queryFn: getMcpAuditLog });

  const revoke = useMutation({
    mutationFn: revokeMcpToken,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mcp-tokens'] })
  });

  const contractVersion =
    tools.data?.contract_version ||
    tokens.data?.contract_version ||
    audit.data?.contract_version;

  return (
    <div className='space-y-4'>
      <div className='flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between'>
        <div className='space-y-1'>
          <h1 className='text-xl font-bold tracking-tight text-foreground'>
            {t('title')}
          </h1>
          <p className='text-sm text-muted-foreground'>{t('subtitle')}</p>
        </div>
        <Button onClick={() => setDialogOpen(true)}>
          <Plus className='mr-2 size-4' />
          {t('createToken')}
        </Button>
      </div>

      <PreviewBanner contractVersion={contractVersion} />

      <Tabs value={tab} onValueChange={(value) => setTab(value as McpTab)}>
        <TabsList>
          <TabsTrigger value='tools'>{t('tabs.tools')}</TabsTrigger>
          <TabsTrigger value='tokens'>{t('tabs.tokens')}</TabsTrigger>
          <TabsTrigger value='audit'>{t('tabs.audit')}</TabsTrigger>
        </TabsList>
        <TabsContent value='tools' className='mt-4'>
          <div className='rounded-lg border'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('tool')}</TableHead>
                  <TableHead>{t('route')}</TableHead>
                  <TableHead>{t('scope')}</TableHead>
                  <TableHead>{t('stability')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(tools.data?.tools || []).map((tool) => (
                  <TableRow key={tool.name}>
                    <TableCell className='max-w-[420px]'>
                      <div className='flex items-center gap-2 font-medium'>
                        <Wrench className='size-4 text-muted-foreground' />
                        {tool.name}
                      </div>
                      <p className='mt-1 line-clamp-2 text-xs text-muted-foreground'>
                        {tool.description}
                      </p>
                    </TableCell>
                    <TableCell className='font-mono text-xs'>
                      {tool.metadata.route}
                    </TableCell>
                    <TableCell>
                      <Badge variant='secondary'>
                        {tool.metadata.token_scope}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant='outline'>{tool.metadata.stability}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
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
                {(tokens.data?.tokens || []).map((token) => (
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
                    <TableCell>{token.scope_type}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          token.status === 'active' ? 'secondary' : 'outline'
                        }
                      >
                        {token.status}
                      </Badge>
                    </TableCell>
                    <TableCell className='text-right'>
                      {token.status === 'active' && token.source !== 'env' ? (
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
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
        <TabsContent value='audit' className='mt-4'>
          <div className='rounded-lg border'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('tool')}</TableHead>
                  <TableHead>{t('result')}</TableHead>
                  <TableHead>{t('session')}</TableHead>
                  <TableHead>{t('latency')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(audit.data?.entries || []).map((entry, index) => (
                  <TableRow
                    key={`${entry.started_at}-${entry.tool_name}-${index}`}
                  >
                    <TableCell>{entry.tool_name}</TableCell>
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
                          {entry.result_code}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell className='font-mono text-xs'>
                      {entry.session_id || '-'}
                    </TableCell>
                    <TableCell>{entry.latency_ms}ms</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>
      <TokenDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
