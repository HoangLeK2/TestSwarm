'use client';

import React from 'react';
import { useTranslations } from 'next-intl';
import { Button } from './button';

interface ReadMoreProps {
  html: string;
  maxLines?: number;
  className?: string;
}

export function ReadMore({ html, maxLines = 5, className }: ReadMoreProps) {
  const t = useTranslations('common');
  const contentRef = React.useRef<HTMLDivElement | null>(null);
  const [isExpanded, setIsExpanded] = React.useState(false);
  const [isOverflowing, setIsOverflowing] = React.useState(false);

  const measureOverflow = React.useCallback(() => {
    const el = contentRef.current;
    if (!el) return;

    // Force clamp off to get full height, then restore
    const prevDisplay = el.style.display;
    const prevClamp = (el.style as any).WebkitLineClamp;
    const prevOrient = (el.style as any).WebkitBoxOrient;
    const prevOverflow = el.style.overflow;

    (el.style as any).WebkitLineClamp = '';
    (el.style as any).WebkitBoxOrient = '';
    el.style.display = '';
    el.style.overflow = '';

    const fullHeight = el.scrollHeight;

    // Apply clamp styles for measurement comparison
    (el.style as any).WebkitLineClamp = String(maxLines);
    (el.style as any).WebkitBoxOrient = 'vertical';
    el.style.display = '-webkit-box';
    el.style.overflow = 'hidden';

    const clampedHeight = el.clientHeight;

    // Restore previous styles
    el.style.display = prevDisplay;
    (el.style as any).WebkitLineClamp = prevClamp;
    (el.style as any).WebkitBoxOrient = prevOrient;
    el.style.overflow = prevOverflow;

    setIsOverflowing(fullHeight > clampedHeight + 1);
  }, [maxLines]);

  React.useEffect(() => {
    measureOverflow();
  }, [html, maxLines, measureOverflow]);

  React.useEffect(() => {
    const handle = () => measureOverflow();
    window.addEventListener('resize', handle);
    return () => window.removeEventListener('resize', handle);
  }, [measureOverflow]);

  return (
    <div className={`relative ${className || ''}`}>
      <div
        ref={contentRef}
        style={
          isExpanded
            ? undefined
            : ({
                display: '-webkit-box',
                WebkitLineClamp: String(maxLines),
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden'
              } as React.CSSProperties)
        }
        dangerouslySetInnerHTML={{ __html: html }}
      />
      {isOverflowing && !isExpanded && (
        <div className='pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-background to-transparent' />
      )}
      {isOverflowing && (
        <Button
          type='button'
          variant='link'
          onClick={() => setIsExpanded((v) => !v)}
          className='absolute bottom-0 right-0 inline text-xs font-medium text-primary hover:underline'
          aria-expanded={isExpanded}
        >
          {isExpanded ? t('show_less') : t('read_more')}
        </Button>
      )}
    </div>
  );
}

export default ReadMore;
