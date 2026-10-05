'use client';

import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CircleAlert,
  FlaskConical,
  ShieldCheck
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Textarea } from '@/components/ui/textarea';

import { prototypeCopy, type PrototypeLocale } from './prototype-copy';
import { getPrototypeStateCatalog } from './prototype-state-catalog';

type PrototypeView =
  | 'landing'
  | 'wizard'
  | 'scenario'
  | 'review'
  | 'payment'
  | 'readiness'
  | 'dashboard'
  | 'lane'
  | 'report'
  | 'operator'
  | 'states';

export function AiDeviceLabPrototype({ locale }: { locale: PrototypeLocale }) {
  const copy = prototypeCopy[locale];
  const [view, setView] = useState<PrototypeView>('landing');
  const wizardActive = ['wizard', 'scenario', 'review', 'payment'].includes(
    view
  );

  useEffect(() => {
    requestAnimationFrame(() => {
      document.getElementById('adl-view-heading')?.focus();
    });
  }, [view]);

  return (
    <main
      data-testid='ai-device-lab-prototype'
      className='min-h-screen bg-[#f5f4ef] text-slate-950'
    >
      <div className='border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-xs font-medium text-amber-950'>
        <FlaskConical className='mr-1.5 inline size-3.5' aria-hidden='true' />
        {copy.prototype}
      </div>

      <header className='mx-auto flex w-full max-w-7xl flex-col gap-4 px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-8'>
        <button
          className='flex items-center gap-2 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-4'
          onClick={() => setView('landing')}
        >
          <span className='grid size-9 place-items-center rounded-xl bg-slate-950 text-white'>
            <ShieldCheck className='size-5' aria-hidden='true' />
          </span>
          <span className='font-semibold tracking-tight'>{copy.brand}</span>
        </button>
        <nav
          aria-label={copy.brand}
          className='flex max-w-full items-center gap-1 overflow-x-auto rounded-full border bg-white/80 p-1 shadow-sm'
        >
          <Button
            size='sm'
            variant={view === 'landing' ? 'default' : 'ghost'}
            aria-current={view === 'landing' ? 'page' : undefined}
            onClick={() => setView('landing')}
          >
            {copy.nav.overview}
          </Button>
          <Button
            size='sm'
            variant={wizardActive ? 'default' : 'ghost'}
            aria-current={wizardActive ? 'page' : undefined}
            onClick={() => setView('wizard')}
          >
            {copy.nav.wizard}
          </Button>
          <Button
            size='sm'
            variant={view === 'readiness' ? 'default' : 'ghost'}
            aria-current={view === 'readiness' ? 'page' : undefined}
            onClick={() => setView('readiness')}
          >
            {copy.nav.readiness}
          </Button>
          <Button
            size='sm'
            variant={view === 'dashboard' ? 'default' : 'ghost'}
            aria-current={view === 'dashboard' ? 'page' : undefined}
            onClick={() => setView('dashboard')}
          >
            {copy.nav.dashboard}
          </Button>
          <Button
            size='sm'
            variant={view === 'report' ? 'default' : 'ghost'}
            aria-current={view === 'report' ? 'page' : undefined}
            onClick={() => setView('report')}
          >
            {copy.nav.report}
          </Button>
          <Button
            size='sm'
            variant={view === 'operator' ? 'default' : 'ghost'}
            aria-current={view === 'operator' ? 'page' : undefined}
            onClick={() => setView('operator')}
          >
            {copy.nav.operator}
          </Button>
          <Button
            size='sm'
            variant={view === 'states' ? 'default' : 'ghost'}
            aria-current={view === 'states' ? 'page' : undefined}
            onClick={() => setView('states')}
          >
            {copy.nav.states}
          </Button>
        </nav>
      </header>

      {view === 'landing' && (
        <LandingScreen onStart={() => setView('wizard')} copy={copy.landing} />
      )}
      {view === 'wizard' && (
        <WizardScreen
          onBack={() => setView('landing')}
          onContinue={() => setView('scenario')}
          copy={copy.wizard}
        />
      )}
      {view === 'scenario' && (
        <ScenarioScreen
          onBack={() => setView('wizard')}
          onContinue={() => setView('review')}
          copy={copy.scenario}
        />
      )}
      {view === 'review' && (
        <ReviewScreen
          copy={copy.review}
          onBack={() => setView('scenario')}
          onContinue={() => setView('payment')}
        />
      )}
      {view === 'payment' && (
        <PaymentScreen
          copy={copy.payment}
          onBack={() => setView('review')}
          onReadiness={() => setView('readiness')}
        />
      )}
      {view === 'readiness' && (
        <ReadinessScreen
          copy={copy.readiness}
          onDashboard={() => setView('dashboard')}
        />
      )}
      {view === 'dashboard' && (
        <DashboardScreen
          copy={copy.dashboard}
          onLaneOpen={() => setView('lane')}
        />
      )}
      {view === 'lane' && (
        <LaneDetailScreen
          copy={copy.lane}
          onBack={() => setView('dashboard')}
        />
      )}
      {view === 'report' && <ReportScreen copy={copy.report} />}
      {view === 'operator' && <OperatorScreen copy={copy.operator} />}
      {view === 'states' && (
        <StateMapScreen locale={locale} copy={copy.states} />
      )}
    </main>
  );
}

function LandingScreen({
  copy,
  onStart
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['landing'];
  onStart: () => void;
}) {
  const [state, setState] = useState<'signed-in' | 'guest' | 'error'>(
    'signed-in'
  );

  return (
    <section className='mx-auto grid w-full max-w-7xl gap-12 px-5 pb-16 pt-10 sm:px-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-center lg:pt-20'>
      <div>
        <Badge
          variant='outline'
          className='mb-5 border-emerald-300 bg-emerald-50 text-emerald-800'
        >
          {copy.eyebrow}
        </Badge>
        <h1
          id='adl-view-heading'
          tabIndex={-1}
          className='max-w-4xl text-balance text-5xl font-semibold leading-[0.98] tracking-[-0.045em] outline-none sm:text-7xl'
        >
          {copy.title}
        </h1>
        <p className='mt-6 max-w-2xl text-pretty text-base leading-7 text-slate-600 sm:text-lg'>
          {copy.description}
        </p>
        <div className='mt-6 flex flex-wrap gap-2' aria-label={copy.stateLabel}>
          <Button
            size='sm'
            variant={state === 'signed-in' ? 'default' : 'outline'}
            aria-pressed={state === 'signed-in'}
            onClick={() => setState('signed-in')}
          >
            {copy.signedIn}
          </Button>
          <Button
            size='sm'
            variant={state === 'guest' ? 'default' : 'outline'}
            aria-pressed={state === 'guest'}
            onClick={() => setState('guest')}
          >
            {copy.guest}
          </Button>
          <Button
            size='sm'
            variant={state === 'error' ? 'destructive' : 'outline'}
            aria-pressed={state === 'error'}
            onClick={() => setState('error')}
          >
            {copy.ctaError}
          </Button>
        </div>
        <p
          className='mt-3 text-sm text-slate-600'
          role='status'
          aria-live='polite'
        >
          {state === 'signed-in'
            ? copy.signedInMessage
            : state === 'guest'
              ? copy.guestMessage
              : copy.ctaErrorMessage}
        </p>
        <div className='mt-6 flex flex-col gap-3 sm:flex-row'>
          <Button
            size='lg'
            disabled={state === 'guest'}
            onClick={state === 'error' ? () => setState('signed-in') : onStart}
          >
            {state === 'error' ? copy.retryCta : copy.cta}
            <ArrowRight aria-hidden='true' />
          </Button>
          <Button
            size='lg'
            variant='outline'
            onClick={() =>
              document
                .getElementById('service-package')
                ?.scrollIntoView({ behavior: 'smooth' })
            }
          >
            {copy.secondary}
          </Button>
        </div>
        <p className='mt-5 max-w-2xl border-l-2 border-slate-300 pl-4 text-sm leading-6 text-slate-600'>
          {copy.disclaimer}
        </p>
      </div>

      <Card
        id='service-package'
        className='overflow-hidden border-slate-200 bg-slate-950 text-white shadow-2xl shadow-slate-300/60'
      >
        <CardContent className='p-6 sm:p-8'>
          <p className='text-sm font-medium text-emerald-300'>
            {copy.packageLabel}
          </p>
          <p className='mt-2 text-2xl font-semibold'>{copy.price}</p>
          <p className='mt-2 text-sm leading-6 text-slate-300'>
            {copy.priceNote}
          </p>
          <div className='mt-8 grid grid-cols-3 gap-3'>
            {copy.metrics.map(([value, label]) => (
              <div
                key={label}
                className='rounded-2xl border border-white/10 bg-white/5 p-3'
              >
                <p className='text-2xl font-semibold'>{value}</p>
                <p className='mt-1 text-xs leading-4 text-slate-300'>{label}</p>
              </div>
            ))}
          </div>
          <ul className='mt-8 space-y-3 text-sm text-slate-200'>
            {copy.benefits.map((item) => (
              <li key={item} className='flex items-center gap-2'>
                <Check className='size-4 text-emerald-300' aria-hidden='true' />
                {item}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </section>
  );
}

function WizardScreen({
  copy,
  onBack,
  onContinue
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['wizard'];
  onBack: () => void;
  onContinue: () => void;
}) {
  return (
    <section className='mx-auto w-full max-w-4xl px-5 pb-20 pt-8 sm:px-8'>
      <button
        className='mb-6 rounded text-sm text-slate-600 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900'
        onClick={onBack}
      >
        ← {copy.back}
      </button>
      <div className='mb-8 flex items-end justify-between gap-4'>
        <div>
          <p className='text-sm font-medium text-slate-500'>{copy.step}</p>
          <h1
            id='adl-view-heading'
            tabIndex={-1}
            className='mt-2 text-3xl font-semibold tracking-tight outline-none'
          >
            {copy.heading}
          </h1>
          <p className='mt-2 text-slate-600'>{copy.description}</p>
        </div>
        <Badge variant='secondary'>{copy.title}</Badge>
      </div>
      <Card className='bg-white shadow-xl shadow-slate-200/50'>
        <CardContent className='grid gap-6 p-6 sm:p-8'>
          <div className='grid gap-2'>
            <Label htmlFor='adl-app-name'>{copy.appName}</Label>
            <Input id='adl-app-name' defaultValue={copy.defaultAppName} />
          </div>
          <div className='grid gap-2'>
            <Label htmlFor='adl-package'>{copy.packageName}</Label>
            <Input
              id='adl-package'
              defaultValue={copy.defaultPackageName}
              spellCheck={false}
            />
          </div>
          <div className='grid gap-2'>
            <Label htmlFor='adl-goal'>{copy.goal}</Label>
            <Textarea id='adl-goal' defaultValue={copy.defaultGoal} rows={5} />
          </div>
          <Button className='justify-self-end' onClick={onContinue}>
            {copy.continue}
            <ArrowRight aria-hidden='true' />
          </Button>
        </CardContent>
      </Card>
    </section>
  );
}

function ScenarioScreen({
  copy,
  onBack,
  onContinue
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['scenario'];
  onBack: () => void;
  onContinue: () => void;
}) {
  const [state, setState] = useState<
    'generating' | 'ai-error' | 'approved' | 'denied' | 'stale'
  >('approved');

  const notice =
    state === 'generating'
      ? [copy.generatingHeading, copy.generatingBody]
      : state === 'ai-error'
        ? [copy.aiErrorHeading, copy.aiErrorBody]
        : state === 'stale'
          ? [copy.staleHeading, copy.staleBody]
          : null;

  return (
    <section className='mx-auto w-full max-w-4xl px-5 pb-20 pt-8 sm:px-8'>
      <button
        className='mb-6 rounded text-sm text-slate-600 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900'
        onClick={onBack}
      >
        ← {copy.back}
      </button>
      <p className='text-sm font-medium text-slate-500'>{copy.step}</p>
      <h1
        id='adl-view-heading'
        tabIndex={-1}
        className='mt-2 text-3xl font-semibold tracking-tight outline-none'
      >
        {copy.heading}
      </h1>
      <p className='mt-2 text-slate-600'>{copy.description}</p>

      <div className='mt-6 flex flex-wrap gap-2' aria-label={copy.stateLabel}>
        <Button
          variant={state === 'generating' ? 'default' : 'outline'}
          aria-pressed={state === 'generating'}
          onClick={() => setState('generating')}
        >
          {copy.generating}
        </Button>
        <Button
          variant={state === 'ai-error' ? 'destructive' : 'outline'}
          aria-pressed={state === 'ai-error'}
          onClick={() => setState('ai-error')}
        >
          {copy.aiError}
        </Button>
        <Button
          variant={state === 'approved' ? 'default' : 'outline'}
          aria-pressed={state === 'approved'}
          onClick={() => setState('approved')}
        >
          {copy.approved}
        </Button>
        <Button
          variant={state === 'denied' ? 'destructive' : 'outline'}
          aria-pressed={state === 'denied'}
          onClick={() => setState('denied')}
        >
          {copy.denied}
        </Button>
        <Button
          variant={state === 'stale' ? 'destructive' : 'outline'}
          aria-pressed={state === 'stale'}
          onClick={() => setState('stale')}
        >
          {copy.stale}
        </Button>
      </div>

      <Card className='mt-6 bg-white shadow-xl shadow-slate-200/50'>
        <CardContent className='p-6 sm:p-8'>
          {state === 'denied' ? (
            <div
              className='rounded-2xl border border-amber-200 bg-amber-50 p-5'
              role='status'
            >
              <div className='flex gap-3'>
                <AlertTriangle
                  className='mt-0.5 size-5 shrink-0 text-amber-700'
                  aria-hidden='true'
                />
                <div>
                  <h2 className='text-xl font-semibold'>
                    {copy.deniedHeading}
                  </h2>
                  <p className='mt-2 text-sm leading-6 text-slate-700'>
                    {copy.deniedReason}
                  </p>
                  <p className='mt-3 text-sm font-semibold text-amber-900'>
                    {copy.notFailure}
                  </p>
                  <p className='mt-1 text-sm text-slate-600'>{copy.owner}</p>
                  <Button className='mt-5' variant='outline' onClick={onBack}>
                    {copy.action}
                  </Button>
                </div>
              </div>
            </div>
          ) : notice ? (
            <div
              className='rounded-2xl border border-amber-200 bg-amber-50 p-5'
              role='status'
              aria-live='polite'
            >
              <h2 className='text-xl font-semibold'>{notice[0]}</h2>
              <p className='mt-2 text-sm leading-6 text-slate-700'>
                {notice[1]}
              </p>
              {state === 'ai-error' && (
                <Button
                  className='mt-5'
                  variant='outline'
                  onClick={() => setState('generating')}
                >
                  {copy.retryGeneration}
                </Button>
              )}
              {state === 'stale' && (
                <Button className='mt-5' variant='outline' onClick={onBack}>
                  {copy.reviewChanges}
                </Button>
              )}
            </div>
          ) : (
            <ol className='grid gap-3'>
              {copy.steps.map((item, index) => (
                <li
                  key={item}
                  className='flex items-center gap-3 rounded-xl border p-4'
                >
                  <span className='grid size-7 shrink-0 place-items-center rounded-full bg-slate-950 text-xs font-semibold text-white'>
                    {index + 1}
                  </span>
                  <span className='font-medium'>{item}</span>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
      {state === 'approved' && (
        <div className='mt-6 flex justify-end'>
          <Button onClick={onContinue}>
            {copy.continue}
            <ArrowRight aria-hidden='true' />
          </Button>
        </div>
      )}
    </section>
  );
}

function ReviewScreen({
  copy,
  onBack,
  onContinue
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['review'];
  onBack: () => void;
  onContinue: () => void;
}) {
  return (
    <section className='mx-auto w-full max-w-4xl px-5 pb-20 pt-8 sm:px-8'>
      <button
        className='mb-6 rounded text-sm text-slate-600 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900'
        onClick={onBack}
      >
        ← {copy.back}
      </button>
      <p className='text-sm font-medium text-slate-500'>{copy.step}</p>
      <h1
        id='adl-view-heading'
        tabIndex={-1}
        className='mt-2 text-3xl font-semibold tracking-tight outline-none'
      >
        {copy.heading}
      </h1>
      <p className='mt-2 text-slate-600'>{copy.description}</p>
      <Card className='mt-6 gap-0 bg-white shadow-xl shadow-slate-200/50'>
        <CardContent className='divide-y p-0'>
          {[copy.package, copy.app, copy.scenario, copy.price].map((item) => (
            <p key={item} className='p-5 font-medium'>
              {item}
            </p>
          ))}
          <p className='bg-blue-50 p-5 text-sm leading-6 text-blue-950'>
            {copy.policy}
          </p>
        </CardContent>
      </Card>
      <div className='mt-6 flex justify-end'>
        <Button onClick={onContinue}>
          {copy.continue}
          <ArrowRight aria-hidden='true' />
        </Button>
      </div>
    </section>
  );
}

function PaymentScreen({
  copy,
  onBack,
  onReadiness
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['payment'];
  onBack: () => void;
  onReadiness: () => void;
}) {
  const [state, setState] = useState<'pending' | 'paid' | 'failed'>('pending');

  return (
    <section className='mx-auto w-full max-w-4xl px-5 pb-20 pt-8 sm:px-8'>
      <button
        className='mb-6 rounded text-sm text-slate-600 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900'
        onClick={onBack}
      >
        ← {copy.back}
      </button>
      <p className='text-sm font-medium text-slate-500'>{copy.step}</p>
      <h1
        id='adl-view-heading'
        tabIndex={-1}
        className='mt-2 text-3xl font-semibold tracking-tight outline-none'
      >
        {copy.heading}
      </h1>
      <p className='mt-2 max-w-3xl text-slate-600'>{copy.description}</p>
      <div className='mt-6 flex flex-wrap gap-2' aria-label={copy.stateLabel}>
        <Button
          variant={state === 'pending' ? 'default' : 'outline'}
          aria-pressed={state === 'pending'}
          onClick={() => setState('pending')}
        >
          {copy.showPending}
        </Button>
        <Button
          variant={state === 'paid' ? 'default' : 'outline'}
          aria-pressed={state === 'paid'}
          onClick={() => setState('paid')}
        >
          {copy.showPaid}
        </Button>
        <Button
          variant={state === 'failed' ? 'destructive' : 'outline'}
          aria-pressed={state === 'failed'}
          onClick={() => setState('failed')}
        >
          {copy.showFailed}
        </Button>
      </div>
      <Card className='mt-6 gap-0 bg-white shadow-xl shadow-slate-200/50'>
        <CardContent className='p-6'>
          <p className='text-xl font-semibold' role='status' aria-live='polite'>
            {copy[state]}
          </p>
        </CardContent>
      </Card>
      <div className='mt-6 flex flex-wrap justify-end gap-3'>
        {state === 'failed' && (
          <Button variant='outline' onClick={() => setState('pending')}>
            {copy.retry}
          </Button>
        )}
        <Button disabled={state !== 'paid'} onClick={onReadiness}>
          {copy.openReadiness}
          <ArrowRight aria-hidden='true' />
        </Button>
      </div>
    </section>
  );
}

function ReadinessScreen({
  copy,
  onDashboard
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['readiness'];
  onDashboard: () => void;
}) {
  const [state, setState] = useState<
    'unknown' | 'blocked' | 'ready' | 'running' | 'attention'
  >('blocked');
  const [recheckMessage, setRecheckMessage] = useState<string | null>(null);
  useEffect(() => {
    if (state !== 'running') return;
    requestAnimationFrame(() => {
      document.getElementById('adl-view-heading')?.focus();
    });
  }, [state]);
  const heading =
    state === 'unknown'
      ? copy.unknownHeading
      : state === 'ready'
        ? copy.readyHeading
        : state === 'running'
          ? copy.runningHeading
          : state === 'attention'
            ? copy.attentionHeading
            : copy.heading;
  const description =
    state === 'unknown'
      ? copy.unknownDescription
      : state === 'ready'
        ? copy.readyDescription
        : state === 'running'
          ? copy.runningDescription
          : state === 'attention'
            ? copy.attentionDescription
            : copy.description;

  return (
    <section className='mx-auto w-full max-w-5xl px-5 pb-20 pt-8 sm:px-8'>
      <p className='text-sm font-medium text-amber-700'>{copy.eyebrow}</p>
      <h1
        id='adl-view-heading'
        tabIndex={-1}
        className='mt-2 text-4xl font-semibold tracking-tight outline-none'
      >
        {heading}
      </h1>
      <p className='mt-3 max-w-3xl text-slate-600'>{description}</p>
      <div className='mt-6 flex flex-wrap gap-2' aria-label={copy.stateLabel}>
        {(
          [
            ['unknown', copy.showUnknown],
            ['blocked', copy.showBlocked],
            ['ready', copy.showReady],
            ['running', copy.showRunning],
            ['attention', copy.showAttention]
          ] as const
        ).map(([value, label]) => (
          <Button
            key={value}
            size='sm'
            variant={state === value ? 'default' : 'outline'}
            aria-pressed={state === value}
            onClick={() => {
              setState(value);
              setRecheckMessage(null);
            }}
          >
            {label}
          </Button>
        ))}
      </div>
      <div className='mt-5 flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-medium text-blue-950'>
        <CircleAlert className='size-4 shrink-0' aria-hidden='true' />
        {copy.notFailure}
      </div>
      {recheckMessage && (
        <p
          className='mt-3 text-sm font-medium text-blue-950'
          role='status'
          aria-live='polite'
        >
          {recheckMessage}
        </p>
      )}

      <Card className='mt-6 bg-white shadow-xl shadow-slate-200/50'>
        <CardContent className='divide-y p-0'>
          {copy.items.map(([label, status, source, resolvedSource]) => {
            const visibleStatus =
              state === 'ready' || state === 'running'
                ? copy.ready
                : state === 'unknown'
                  ? copy.showUnknown
                  : status;
            const visibleSource =
              state === 'ready' || state === 'running'
                ? resolvedSource
                : source;
            const needsAttention = visibleStatus === copy.attention;
            return (
              <div
                key={label}
                className='grid gap-3 p-5 sm:grid-cols-[1fr_auto] sm:items-center'
              >
                <div>
                  <p className='font-medium'>{label}</p>
                  <p className='mt-1 text-sm text-slate-500'>{visibleSource}</p>
                </div>
                <Badge variant={needsAttention ? 'destructive' : 'outline'}>
                  {visibleStatus}
                </Badge>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <div className='mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end'>
        {state === 'running' ? (
          <Button onClick={onDashboard}>{copy.openDashboard}</Button>
        ) : (
          <>
            <Button
              variant='outline'
              onClick={() =>
                setRecheckMessage(
                  state === 'ready'
                    ? copy.recheckComplete
                    : state === 'unknown'
                      ? copy.recheckUnknown
                      : copy.recheckBlocked
                )
              }
            >
              {copy.recheck}
            </Button>
            <Button
              disabled={state !== 'ready'}
              onClick={() => setState('running')}
            >
              {copy.start}
            </Button>
          </>
        )}
      </div>
    </section>
  );
}

function DashboardScreen({
  copy,
  onLaneOpen
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['dashboard'];
  onLaneOpen: () => void;
}) {
  return (
    <section className='mx-auto w-full max-w-6xl px-5 pb-20 pt-8 sm:px-8'>
      <div className='flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between'>
        <div>
          <p className='text-sm font-medium text-emerald-700'>{copy.eyebrow}</p>
          <h1
            id='adl-view-heading'
            tabIndex={-1}
            className='mt-2 text-4xl font-semibold tracking-tight outline-none'
          >
            {copy.heading}
          </h1>
        </div>
        <Badge className='bg-emerald-700 text-white'>{copy.running}</Badge>
      </div>

      <div className='mt-8 grid gap-4 lg:grid-cols-3'>
        {copy.axes.map(([label, value, percent, detail], index) => (
          <Card
            key={label}
            data-testid={
              index === 0
                ? 'progress-service'
                : index === 1
                  ? 'progress-quality'
                  : 'progress-participation'
            }
            className='gap-0 bg-white'
          >
            <CardContent className='p-5'>
              <p className='text-sm font-medium text-slate-500'>{label}</p>
              <p className='mt-3 text-2xl font-semibold'>{value}</p>
              <Progress
                className='mt-4'
                value={Number(percent)}
                aria-label={`${label}: ${value}`}
              />
              <p className='mt-3 text-sm leading-5 text-slate-600'>{detail}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className='mt-6 gap-0 bg-white'>
        <CardContent className='p-0'>
          <div className='border-b p-5'>
            <h2 className='text-xl font-semibold'>{copy.lanesTitle}</h2>
            <p className='mt-1 text-sm text-slate-600'>
              {copy.lanesDescription}
            </p>
          </div>
          <div className='divide-y'>
            {copy.lanes.map(([label, device, status]) => (
              <div
                key={label}
                className='grid grid-cols-[1fr_auto] items-center gap-4 p-5 sm:grid-cols-[1fr_1fr_auto]'
              >
                {label === 'Tester 03' ? (
                  <button
                    className='w-fit rounded font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900'
                    onClick={onLaneOpen}
                  >
                    <span className='sr-only'>{copy.openLane}</span>
                    <span aria-hidden='true'>{label}</span>
                  </button>
                ) : (
                  <p className='font-medium'>{label}</p>
                )}
                <p className='hidden text-sm text-slate-500 sm:block'>
                  {device}
                </p>
                <Badge
                  variant={
                    status.includes('Blocked') || status.includes('chặn')
                      ? 'destructive'
                      : 'outline'
                  }
                >
                  {status}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

function LaneDetailScreen({
  copy,
  onBack
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['lane'];
  onBack: () => void;
}) {
  const [retryPreview, setRetryPreview] = useState<string | null>(null);

  return (
    <section className='mx-auto w-full max-w-5xl px-5 pb-20 pt-8 sm:px-8'>
      <button
        className='mb-6 rounded text-sm text-slate-600 underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900'
        onClick={onBack}
      >
        ← {copy.back}
      </button>
      <h1
        id='adl-view-heading'
        tabIndex={-1}
        className='text-4xl font-semibold tracking-tight outline-none'
      >
        {copy.heading}
      </h1>
      <p className='mt-2 text-slate-600'>{copy.subtitle}</p>
      <div className='mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-5'>
        <Badge variant='destructive'>{copy.status}</Badge>
        <p className='mt-3 font-medium text-slate-900'>{copy.reason}</p>
        <p className='mt-2 text-sm leading-6 text-slate-600'>{copy.owner}</p>
      </div>

      <h2 className='mt-8 text-xl font-semibold'>{copy.attempts}</h2>
      <div className='mt-4 grid gap-4 md:grid-cols-2'>
        <Card className='gap-0 bg-white'>
          <CardContent className='p-5'>
            <p className='font-semibold'>{copy.current}</p>
            <p className='mt-2 text-sm text-slate-600'>
              {copy.currentEvidence}
            </p>
          </CardContent>
        </Card>
        <Card className='gap-0 bg-white'>
          <CardContent className='p-5'>
            <p className='font-semibold'>{copy.previous}</p>
            <p className='mt-2 text-sm text-slate-600'>
              {copy.expiredEvidence}
            </p>
          </CardContent>
        </Card>
      </div>
      <p className='mt-5 rounded-xl border bg-white p-4 text-sm leading-6 text-slate-600'>
        {copy.retryNote}
      </p>
      <div className='mt-4 flex flex-wrap gap-3'>
        <Button
          variant='outline'
          onClick={() => setRetryPreview(copy.runRetryConsequence)}
        >
          {copy.runRetry}
        </Button>
        <Button
          variant='outline'
          onClick={() => setRetryPreview(copy.stepRetryConsequence)}
        >
          {copy.stepRetry}
        </Button>
      </div>
      {retryPreview && (
        <p
          className='mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950'
          role='status'
          aria-live='polite'
        >
          {retryPreview}
        </p>
      )}
    </section>
  );
}

function ReportScreen({
  copy
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['report'];
}) {
  const [state, setState] = useState<
    'generating' | 'failed' | 'frozen' | 'corrected'
  >('frozen');
  const stateCopy = {
    generating: [copy.generating, copy.generatingMessage],
    failed: [copy.failed, copy.failedMessage],
    frozen: [copy.state, copy.frozenMessage],
    corrected: [copy.corrected, copy.correctedMessage]
  }[state];

  return (
    <section className='mx-auto w-full max-w-6xl px-5 pb-20 pt-8 sm:px-8'>
      <p className='text-sm font-medium text-emerald-700'>{copy.eyebrow}</p>
      <div className='mt-2 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between'>
        <h1
          id='adl-view-heading'
          tabIndex={-1}
          className='text-4xl font-semibold tracking-tight outline-none'
        >
          {copy.heading}
        </h1>
        <Badge variant='outline'>{stateCopy[0]}</Badge>
      </div>
      <div className='mt-6 flex flex-wrap gap-2' aria-label={copy.stateLabel}>
        {(
          [
            ['generating', copy.generating],
            ['failed', copy.failed],
            ['frozen', copy.frozen],
            ['corrected', copy.corrected]
          ] as const
        ).map(([value, label]) => (
          <Button
            key={value}
            size='sm'
            variant={state === value ? 'default' : 'outline'}
            aria-pressed={state === value}
            onClick={() => setState(value)}
          >
            {label}
          </Button>
        ))}
      </div>
      <p
        className='mt-3 max-w-3xl text-sm leading-6 text-slate-600'
        role='status'
        aria-live='polite'
      >
        {stateCopy[1]}
      </p>
      {state === 'corrected' && (
        <p className='mt-2 max-w-3xl text-sm leading-6 text-slate-600'>
          {copy.correction}
        </p>
      )}
      {state === 'failed' && (
        <Button
          className='mt-4'
          variant='outline'
          onClick={() => setState('generating')}
        >
          {copy.retry}
        </Button>
      )}
      <div className='mt-8 grid grid-cols-2 gap-3 lg:grid-cols-5'>
        {copy.metrics.map(([value, label]) => (
          <Card key={label} className='gap-0 bg-white'>
            <CardContent className='p-5'>
              <p className='text-3xl font-semibold'>{value}</p>
              <p className='mt-1 text-sm text-slate-500'>{label}</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className='mt-6 gap-0 bg-slate-950 text-white'>
        <CardContent className='grid gap-5 p-6 sm:grid-cols-2'>
          <div>
            <p className='font-semibold'>{copy.issues}</p>
            <p className='mt-2 text-sm text-slate-300'>{copy.missing}</p>
          </div>
          <div className='sm:text-right'>
            <p className='text-sm text-slate-300'>{copy.retention}</p>
            <Button className='mt-3' variant='secondary' disabled>
              {copy.download}
            </Button>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

function OperatorScreen({
  copy
}: {
  copy: (typeof prototypeCopy)[PrototypeLocale]['operator'];
}) {
  const [consequence, setConsequence] = useState<string>(copy.noAction);
  const [selectedAction, setSelectedAction] = useState<
    'replace' | 'cancel' | 'extend' | 'quarantine' | null
  >(null);

  return (
    <section className='mx-auto w-full max-w-5xl px-5 pb-20 pt-8 sm:px-8'>
      <p className='text-sm font-medium text-emerald-700'>{copy.eyebrow}</p>
      <h1
        id='adl-view-heading'
        tabIndex={-1}
        className='mt-2 max-w-3xl text-4xl font-semibold tracking-tight outline-none'
      >
        {copy.heading}
      </h1>
      <div className='mt-8 grid gap-3 sm:grid-cols-2'>
        <Button
          variant='outline'
          className='h-auto justify-start p-5'
          aria-pressed={selectedAction === 'replace'}
          onClick={() => {
            setSelectedAction('replace');
            setConsequence(copy.replaceConsequence);
          }}
        >
          {copy.replace}
        </Button>
        <Button
          variant='destructive-outline'
          className='h-auto justify-start p-5'
          aria-pressed={selectedAction === 'cancel'}
          onClick={() => {
            setSelectedAction('cancel');
            setConsequence(copy.cancelConsequence);
          }}
        >
          {copy.cancel}
        </Button>
        <Button
          variant='outline'
          className='h-auto justify-start p-5'
          aria-pressed={selectedAction === 'extend'}
          onClick={() => {
            setSelectedAction('extend');
            setConsequence(copy.extendConsequence);
          }}
        >
          {copy.extend}
        </Button>
        <Button
          variant='outline'
          className='h-auto justify-start p-5'
          aria-pressed={selectedAction === 'quarantine'}
          onClick={() => {
            setSelectedAction('quarantine');
            setConsequence(copy.quarantineConsequence);
          }}
        >
          {copy.quarantine}
        </Button>
      </div>
      <div
        className='mt-6 rounded-2xl border border-blue-200 bg-blue-50 p-5 text-sm font-medium leading-6 text-blue-950'
        role='status'
        aria-live='polite'
      >
        {consequence}
      </div>
    </section>
  );
}

function StateMapScreen({
  locale,
  copy
}: {
  locale: PrototypeLocale;
  copy: (typeof prototypeCopy)[PrototypeLocale]['states'];
}) {
  const states = getPrototypeStateCatalog(locale);
  const [selectedId, setSelectedId] = useState(states[0].id);
  const [mode, setMode] = useState<'normal' | 'loading' | 'error'>('normal');
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const selected = states.find((state) => state.id === selectedId) ?? states[0];
  const previewCopy =
    mode === 'loading'
      ? selected.loadingCopy
      : mode === 'error'
        ? selected.errorCopy
        : `${selected.role} · ${selected.source}`;

  return (
    <section className='mx-auto w-full max-w-7xl px-5 pb-20 pt-8 sm:px-8'>
      <p className='text-sm font-medium text-emerald-700'>{copy.eyebrow}</p>
      <h1
        id='adl-view-heading'
        tabIndex={-1}
        className='mt-2 max-w-4xl text-4xl font-semibold tracking-tight outline-none'
      >
        {copy.heading}
      </h1>
      <p className='mt-3 max-w-3xl text-slate-600'>{copy.description}</p>

      <Card className='mt-8 border-blue-200 bg-blue-50'>
        <CardContent className='p-5 sm:p-6'>
          <p className='text-xs font-semibold uppercase tracking-[0.14em] text-blue-700'>
            {copy.previewHeading}
          </p>
          <h2
            id='adl-state-preview'
            tabIndex={-1}
            className='mt-2 text-2xl font-semibold outline-none'
          >
            {selected.view} · {selected.state}
          </h2>
          <div
            className='mt-4 flex flex-wrap gap-2'
            aria-label={copy.previewHeading}
          >
            {(
              [
                ['normal', copy.normal],
                ['loading', copy.loading],
                ['error', copy.error]
              ] as const
            ).map(([value, label]) => (
              <Button
                key={value}
                size='sm'
                variant={mode === value ? 'default' : 'outline'}
                aria-pressed={mode === value}
                onClick={() => {
                  setMode(value);
                  setActionMessage(null);
                }}
              >
                {label}
              </Button>
            ))}
          </div>
          <p
            className='mt-4 text-sm leading-6 text-blue-950'
            role='status'
            aria-live='polite'
          >
            {actionMessage ?? previewCopy}
          </p>
          <div className='mt-4 flex flex-wrap gap-3'>
            <Button onClick={() => setActionMessage(selected.action)}>
              {selected.action}
            </Button>
            <Button
              variant='outline'
              onClick={() => setActionMessage(selected.secondaryAction)}
            >
              {selected.secondaryAction}
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className='mt-8 grid gap-3 md:grid-cols-2 xl:grid-cols-3'>
        {states.map((state) => (
          <Card
            key={`${state.view}:${state.state}`}
            data-testid='state-spec'
            data-role={state.role}
            data-source={state.source}
            data-primary-action={state.action}
            data-secondary-action={state.secondaryAction}
            data-loading-copy={state.loadingCopy}
            data-error-copy={state.errorCopy}
            className='gap-0 bg-white'
          >
            <CardContent className='p-5'>
              <p className='text-xs font-semibold uppercase tracking-[0.14em] text-slate-500'>
                {state.view}
              </p>
              <h2 className='mt-2 text-lg font-semibold'>{state.state}</h2>
              <dl className='mt-4 grid gap-3 text-sm'>
                <div>
                  <dt className='text-slate-500'>{copy.role}</dt>
                  <dd className='mt-0.5 font-medium'>{state.role}</dd>
                </div>
                <div>
                  <dt className='text-slate-500'>{copy.source}</dt>
                  <dd className='mt-0.5 font-medium'>{state.source}</dd>
                </div>
                <div>
                  <dt className='text-slate-500'>{copy.action}</dt>
                  <dd className='mt-0.5 font-medium'>{state.action}</dd>
                </div>
                <div>
                  <dt className='text-slate-500'>{copy.secondaryAction}</dt>
                  <dd className='mt-0.5 font-medium'>
                    {state.secondaryAction}
                  </dd>
                </div>
                <div>
                  <dt className='text-slate-500'>{copy.loadingCopy}</dt>
                  <dd className='mt-0.5 font-medium'>{state.loadingCopy}</dd>
                </div>
                <div>
                  <dt className='text-slate-500'>{copy.errorCopy}</dt>
                  <dd className='mt-0.5 font-medium'>{state.errorCopy}</dd>
                </div>
              </dl>
              <Button
                className='mt-4'
                size='sm'
                variant={selectedId === state.id ? 'default' : 'outline'}
                aria-label={`${copy.preview}: ${state.view} · ${state.state}`}
                aria-pressed={selectedId === state.id}
                onClick={() => {
                  setSelectedId(state.id);
                  setMode('normal');
                  setActionMessage(null);
                  requestAnimationFrame(() => {
                    document.getElementById('adl-state-preview')?.focus();
                  });
                }}
              >
                {copy.preview}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
