'use client';

import {
  type ReactNode,
  useCallback,
  useLayoutEffect,
  useRef,
  useState
} from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useTranslations } from 'next-intl';
import type { Device } from '../../types';
import {
  FollowerPreview,
  followerMockupWidth,
  formatFollowerLabel
} from './follower-preview';
import { mockupOuterHeightPx } from '../device-android-frame';
import {
  FOLLOWER_GRID_GAP_PX,
  getFollowerGridColumnCount,
  getFollowerGridRowBounds,
  getFollowerGridRowCount
} from '../../lib/follower-virtual-grid';

const FOLLOWER_GRID_HORIZONTAL_PADDING_PX = 24;
const FOLLOWER_CARD_EXTRA_WIDTH_PX = 16;
const FOLLOWER_CARD_EXTRA_HEIGHT_PX = 44;

type Props = {
  mode: 'focus' | 'edit';
  primaryMirror: ReactNode;
  toolbar?: ReactNode;
  devices: Device[];
  onPromote: (serial: string) => void;
};

export function MultiDeviceStage({
  mode,
  primaryMirror,
  toolbar,
  devices,
  onPromote
}: Props) {
  const t = useTranslations('devicesControlRecord.view.multiControl');
  const focus = mode === 'focus';
  const followerMockupW = followerMockupWidth(devices.length);
  const followerScrollRef = useRef<HTMLDivElement>(null);
  const [gridWidth, setGridWidth] = useState(0);

  useLayoutEffect(() => {
    const scroller = followerScrollRef.current;
    if (!focus || !scroller) return;

    const syncWidth = () => {
      const nextWidth = Math.max(
        0,
        scroller.clientWidth - FOLLOWER_GRID_HORIZONTAL_PADDING_PX
      );
      setGridWidth((current) =>
        Math.abs(current - nextWidth) < 0.5 ? current : nextWidth
      );
    };

    syncWidth();
    const resizeObserver = new ResizeObserver(syncWidth);
    resizeObserver.observe(scroller);
    return () => resizeObserver.disconnect();
  }, [devices.length, focus]);

  const columnCount = getFollowerGridColumnCount(
    gridWidth,
    devices.length,
    followerMockupW + FOLLOWER_CARD_EXTRA_WIDTH_PX
  );
  const rowCount = getFollowerGridRowCount(devices.length, columnCount);
  const getScrollElement = useCallback(() => followerScrollRef.current, []);
  const getVirtualRowKey = useCallback(
    (rowIndex: number) => {
      const firstDevice = devices[rowIndex * columnCount];
      return `${columnCount}:${firstDevice?.serial ?? rowIndex}`;
    },
    [columnCount, devices]
  );
  const rowVirtualizer = useVirtualizer({
    count: focus ? rowCount : 0,
    getScrollElement,
    estimateSize: () =>
      mockupOuterHeightPx(followerMockupW) + FOLLOWER_CARD_EXTRA_HEIGHT_PX,
    getItemKey: getVirtualRowKey,
    gap: FOLLOWER_GRID_GAP_PX,
    overscan: 1,
    enabled: focus && devices.length > 0,
    useFlushSync: false,
    directDomUpdates: true
  });

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
              <div
                ref={followerScrollRef}
                className='min-h-0 flex-1 overflow-y-auto px-3 py-3'
              >
                <div
                  ref={rowVirtualizer.containerRef}
                  className='relative w-full'
                  style={{ height: rowVirtualizer.getTotalSize() }}
                >
                  {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                    const { start, end } = getFollowerGridRowBounds(
                      virtualRow.index,
                      columnCount,
                      devices.length
                    );
                    return (
                      <div
                        key={virtualRow.key}
                        ref={rowVirtualizer.measureElement}
                        data-index={virtualRow.index}
                        className='absolute left-0 top-0 grid justify-start gap-2'
                        style={{
                          gridTemplateColumns: `repeat(${columnCount}, max-content)`,
                          transform: `translateY(${virtualRow.start}px)`,
                          contain: 'layout paint'
                        }}
                      >
                        {devices.slice(start, end).map((d, index) => (
                          <FollowerPreview
                            key={d.serial}
                            device={d}
                            mockupScreenWidth={followerMockupW}
                            onPromote={onPromote}
                            previewIndex={start + index}
                            previewCount={devices.length}
                          />
                        ))}
                      </div>
                    );
                  })}
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
