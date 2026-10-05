'use client';

import { ExternalLink, LogIn, ShieldCheck, ShieldOff } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Link } from '@/i18n/navigation';
import { cn } from '@/lib/utils';

export type ScenarioRequirements = Record<string, any>;

export type PlatformSessionRequirement = {
  required?: boolean;
  platform?: string;
  account_source?: string;
};

export function normalizePlatformSessionRequirement(
  requirements?: ScenarioRequirements | null
): PlatformSessionRequirement | null {
  const raw =
    requirements?.platform_session ?? requirements?.platformSession ?? null;
  if (!raw || typeof raw !== 'object') return null;
  return raw as PlatformSessionRequirement;
}

export function scenarioRequiresPlatformSession(
  requirements?: ScenarioRequirements | null
): boolean {
  const session = normalizePlatformSessionRequirement(requirements);
  return session?.required !== false && Boolean(session);
}

export function platformSessionLabel(
  t: (key: string, values?: Record<string, any>) => string,
  requirements?: ScenarioRequirements | null
) {
  const session = normalizePlatformSessionRequirement(requirements);
  if (!session || session.required === false) return t('summaryNoSession');
  return t('summarySession', {
    platform: session.platform || 'platform'
  });
}

export function withPlatformSessionRequirement(
  requirements: ScenarioRequirements | undefined,
  next: PlatformSessionRequirement | null
): ScenarioRequirements {
  const current = { ...(requirements ?? {}) };
  delete current.platformSession;
  if (!next || next.required === false) {
    delete current.platform_session;
    return current;
  }
  return {
    ...current,
    platform_session: {
      required: true,
      platform: next.platform || 'auto',
      account_source: next.account_source || 'device_primary'
    }
  };
}

export function ScenarioRequirementBadge({
  requirements,
  className,
  hideWhenEmpty = false
}: {
  requirements?: ScenarioRequirements | null;
  className?: string;
  hideWhenEmpty?: boolean;
}) {
  const t = useTranslations('campaignsFeature.stepEditor.requirements');
  const requiresSession = scenarioRequiresPlatformSession(requirements);
  if (hideWhenEmpty && !requiresSession) return null;

  return (
    <Badge
      variant={requiresSession ? 'secondary' : 'outline'}
      className={cn(
        'inline-flex max-w-full items-center gap-1 truncate px-1.5 text-[10px] font-medium',
        requiresSession
          ? 'border-amber-200 bg-amber-50 text-amber-700'
          : 'text-muted-foreground',
        className
      )}
      title={platformSessionLabel(t, requirements)}
    >
      {requiresSession ? (
        <ShieldCheck className='size-3 shrink-0' />
      ) : (
        <ShieldOff className='size-3 shrink-0' />
      )}
      <span className='truncate'>{platformSessionLabel(t, requirements)}</span>
    </Badge>
  );
}

export function ScenarioRequirementsSummary({
  requirements,
  className
}: {
  requirements?: ScenarioRequirements | null;
  className?: string;
}) {
  const t = useTranslations('campaignsFeature.stepEditor.requirements');
  const requiresSession = scenarioRequiresPlatformSession(requirements);
  return (
    <div
      className={cn(
        'rounded-md border bg-muted/20 px-3 py-2 text-xs',
        requiresSession && 'border-amber-200 bg-amber-50/70',
        className
      )}
    >
      <div className='flex min-w-0 items-center gap-2'>
        <ScenarioRequirementBadge requirements={requirements} />
        <span className='min-w-0 truncate text-muted-foreground'>
          {requiresSession
            ? t('summarySessionHint')
            : t('summaryNoSessionHint')}
        </span>
      </div>
    </div>
  );
}

export function ScenarioRequirementsSettingsDialog({
  open,
  onOpenChange,
  requirements,
  onChange,
  sessionLoginHref
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  requirements?: ScenarioRequirements | null;
  onChange: (requirements: ScenarioRequirements) => void;
  sessionLoginHref?: string;
}) {
  const t = useTranslations('campaignsFeature.stepEditor.requirements');
  const session = normalizePlatformSessionRequirement(requirements);
  const enabled = session?.required !== false && Boolean(session);
  const platform = session?.platform || 'auto';
  const accountSource = session?.account_source || 'device_primary';

  const update = (patch: Partial<PlatformSessionRequirement> | null) => {
    if (patch === null) {
      onChange(withPlatformSessionRequirement(requirements ?? {}, null));
      return;
    }
    onChange(
      withPlatformSessionRequirement(requirements ?? {}, {
        required: true,
        platform,
        account_source: accountSource,
        ...patch
      })
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription>
            {enabled
              ? t('sessionRequiredDescription', { platform })
              : t('sessionNotRequiredDescription')}
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-4'>
          <div className='flex items-center justify-between gap-3 rounded-md border px-3 py-2'>
            <Label
              htmlFor='scenario-requires-platform-session-settings'
              className='text-sm font-medium'
            >
              {t('sessionToggleLabel')}
            </Label>
            <Switch
              id='scenario-requires-platform-session-settings'
              checked={enabled}
              onCheckedChange={(checked) =>
                checked ? update({}) : update(null)
              }
            />
          </div>
          {enabled ? (
            <div className='grid gap-3 sm:grid-cols-2'>
              <div className='space-y-1.5'>
                <Label className='text-xs text-muted-foreground'>
                  {t('platformLabel')}
                </Label>
                <Select
                  value={platform}
                  onValueChange={(value) => update({ platform: value })}
                >
                  <SelectTrigger className='h-9'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='auto'>Auto</SelectItem>
                    <SelectItem value='tiktok'>
                      {t('platformTiktok')}
                    </SelectItem>
                    <SelectItem value='zalo'>{t('platformZalo')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className='space-y-1.5'>
                <Label className='text-xs text-muted-foreground'>
                  {t('accountSourceLabel')}
                </Label>
                <Select
                  value={accountSource}
                  onValueChange={(value) => update({ account_source: value })}
                >
                  <SelectTrigger className='h-9'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='device_primary'>
                      {t('accountSourceDevicePrimary')}
                    </SelectItem>
                    <SelectItem value='campaign_account'>
                      {t('accountSourceCampaignAccount')}
                    </SelectItem>
                    <SelectItem value='account_group'>
                      {t('accountSourceAccountGroup')}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : null}
          {sessionLoginHref ? (
            <div className='flex flex-col gap-3 rounded-md border bg-muted/20 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between'>
              <div className='min-w-0'>
                <p className='flex items-center gap-1.5 text-sm font-medium'>
                  <LogIn className='size-4 shrink-0' />
                  {t('sessionLoginTitle')}
                </p>
                <p className='mt-1 text-xs text-muted-foreground'>
                  {t('sessionLoginHint')}
                </p>
              </div>
              <Button
                asChild
                type='button'
                variant='outline'
                size='sm'
                className='shrink-0'
              >
                <Link href={sessionLoginHref} target='_blank' rel='noreferrer'>
                  {t('sessionLoginAction')}
                  <ExternalLink className='ml-1.5 size-3.5' />
                </Link>
              </Button>
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button type='button' onClick={() => onOpenChange(false)}>
            {t('done')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
