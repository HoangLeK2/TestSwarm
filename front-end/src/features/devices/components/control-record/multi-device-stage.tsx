'use client';

import { type ReactNode } from 'react';
import { useTranslations } from 'next-intl';
import type { Device } from '../../types';
import {
  FollowerPreview,
  followerGridClass,
  followerMockupWidth,
  formatFollowerLabel
} from './follower-preview';

type Props = {
  mode: 'focus' | 'edit';
  primaryMirror: ReactNode;
  toolbar?: ReactNode;
  devices: Device[];
  wsMode: 'tap' | 'swipe';
  wsSend: (obj: object) => void;
  onPromote: (serial: string) => void;
};

export function MultiDeviceStage({
  mode,
  primaryMirror,
  toolbar,
  devices,
  wsMode,
  wsSend,
  onPromote
}: Props) {
  const t = useTranslations('devicesControlRecord.view.multiControl');
  const focus = mode === 'focus';
  const followerMockupW = followerMockupWidth(devices.length);

  if (focus) {
    return (
      <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
        {toolbar}
        <div className='flex min-h-0 flex-1 overflow-hidden'>
          <aside className='flex shrink-0 items-start justify-center overflow-y-auto border-r border-border/60 bg-muted/10 px-2 py-3'>
            <div className='max-h-[calc(100vh-152px)] w-fit max-w-[min(100vw,320px)]'>
              {primaryMirror}
            </div>
          </aside>

          <section className='flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background'>
            <div className='shrink-0 border-b border-border/50 px-3 py-2 text-[10px] text-muted-foreground'>
              {t('gridHint')}
            </div>
            {devices.length > 0 ? (
              <div className='flex min-h-0 flex-1 justify-start overflow-y-auto px-3 py-3'>
                <div className={followerGridClass(devices.length)}>
                  {devices.map((d) => (
                    <FollowerPreview
                      key={d.serial}
                      device={d}
                      mockupScreenWidth={followerMockupW}
                      mode={wsMode}
                      wsSend={wsSend}
                      onPromote={onPromote}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <div className='flex flex-1 items-center justify-center text-[11px] text-muted-foreground'>
                {t('compactHint')}
              </div>
            )}
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className='flex min-h-0 flex-1 flex-col overflow-hidden'>
      <div className='flex min-h-0 flex-1 items-start justify-center overflow-y-auto px-2 py-3'>
        <div className='max-h-[calc(100vh-210px)]'>{primaryMirror}</div>
      </div>
      {devices.length > 0 ? (
        <div className='shrink-0 border-t border-border/60 bg-muted/20 px-3 py-2'>
          <p className='mb-1.5 text-[10px] text-muted-foreground'>
            {t('compactHint')}
          </p>
          <div className='flex flex-wrap gap-1.5'>
            {devices.map((d) => (
              <button
                key={d.serial}
                type='button'
                onClick={() => onPromote(d.serial)}
                className='max-w-full truncate rounded-full border border-border/60 bg-background px-2.5 py-1 text-[10px] font-medium shadow-sm transition-colors hover:border-primary/50 hover:bg-primary/5'
                title={d.serial}
              >
                {formatFollowerLabel(d)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
