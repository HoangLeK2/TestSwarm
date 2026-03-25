'use client';

// import { CopyButton } from '@/components/ui/copy-button';
import { cn } from '@/lib/utils';
import { Button } from './button';
import { Check, Copy } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip';

interface TruncatedTextProps {
  text: string;
  maxLength?: number;
  showCopy?: boolean;
  className?: string;
  href?: string;
  truncateVariant?: 'middle' | 'start' | 'end';
  enableTooltip?: boolean;
  tooltipContent?: ReactNode;
  truncateText?: string;
}

export function CopyButton({ value }: { value: string }) {
  const [isCopied, setIsCopied] = useState(false);

  return (
    <Button
      variant='ghost'
      className='h-6 w-6'
      onClick={() => {
        navigator.clipboard.writeText(value);
        setIsCopied(true);
        setTimeout(() => {
          setIsCopied(false);
        }, 2000);
      }}
    >
      {isCopied ? (
        <Check className='!h-3 !w-3' />
      ) : (
        <Copy className='!h-3 !w-3' />
      )}
    </Button>
  );
}

export function TruncatedText({
  text,
  maxLength = 15,
  showCopy = false,
  className,
  truncateVariant = 'middle',
  href,
  enableTooltip = true,
  tooltipContent,
  truncateText = '...'
}: TruncatedTextProps) {
  const needsTruncation = text?.length > maxLength;

  const truncated = needsTruncation
    ? (() => {
        const charsPerSide = Math.floor(maxLength / 2);
        if (truncateVariant === 'middle') {
          const start = text.slice(0, charsPerSide);
          const end = text.slice(-charsPerSide);
          return `${start}${truncateText}${end}`;
        } else if (truncateVariant === 'start') {
          return `${text.slice(0, maxLength)}${truncateText}`;
        } else if (truncateVariant === 'end') {
          return `${truncateText}${text.slice(-maxLength)}`;
        }
      })()
    : text;

  const textElement = (
    <span
      className='truncate'
      title={!enableTooltip && needsTruncation ? text : undefined}
    >
      {truncated}
    </span>
  );

  const wrappedTextElement = href ? (
    <a
      href={href}
      className='text-blue-600 hover:text-blue-800 hover:underline'
      target='_blank'
      rel='noopener noreferrer'
    >
      {textElement}
    </a>
  ) : (
    textElement
  );

  if (!needsTruncation && !showCopy && !href) {
    return <span className={className}>{text}</span>;
  }

  const contentWithTooltip =
    enableTooltip && needsTruncation ? (
      <Tooltip>
        <TooltipTrigger asChild>{wrappedTextElement}</TooltipTrigger>
        <TooltipContent>{tooltipContent ?? text}</TooltipContent>
      </Tooltip>
    ) : (
      wrappedTextElement
    );

  return (
    <div className={cn('flex items-center gap-1', className)}>
      {contentWithTooltip}
      {showCopy && <CopyButton value={text} />}
    </div>
  );
}
