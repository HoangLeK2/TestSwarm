'use client';

import { twMerge } from 'tailwind-merge';

interface GoogleDocViewerProps {
  url: string;
  className?: string;
}

const GoogleDocViewer = ({ url, className }: GoogleDocViewerProps) => {
  return (
    <div
      className={twMerge(
        'scrollbar-always-visible! m-auto h-[85vh] w-full overflow-y-scroll md:w-[700px] lg:w-[900px]',
        className
      )}
    >
      <iframe
        width='100%'
        height='auto'
        className='m-auto h-full'
        src={url}
        style={{ padding: '0 !important' }}
      />
    </div>
  );
};

export default GoogleDocViewer;
