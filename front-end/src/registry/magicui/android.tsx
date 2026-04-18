import * as React from 'react';
import { cn } from '@/lib/utils';

export interface AndroidProps extends React.SVGProps<SVGSVGElement> {
  width?: number;
  height?: number;
  /** ratio = screenWidth / screenHeight */
  screenRatio?: number;
  children?: React.ReactNode;
}

/**
 * MagicUI-style Android mockup (registry path).
 * Adapted to support arbitrary stream ratio via `screenRatio`.
 */
export function Android({
  width = 433,
  height = 882,
  screenRatio = 360 / 800,
  className,
  children,
  ...props
}: AndroidProps) {
  const bodyX = 0;
  const bodyY = 0;
  const bodyW = 378;
  const bodyH = 830;

  const maxScreenW = 360;
  const maxScreenH = 800;
  let screenW = maxScreenW;
  let screenH = screenW / Math.max(screenRatio, 0.1);
  if (screenH > maxScreenH) {
    screenH = maxScreenH;
    screenW = screenH * Math.max(screenRatio, 0.1);
  }
  const screenX = 9 + (maxScreenW - screenW) / 2;
  const screenY = 14 + (maxScreenH - screenH) / 2;
  const clipId = React.useId();

  return (
    <svg
      width={width}
      height={height}
      viewBox={`${bodyX} ${bodyY} ${bodyW} ${bodyH}`}
      fill='none'
      xmlns='http://www.w3.org/2000/svg'
      className={cn('drop-shadow-[0_12px_28px_rgba(2,6,23,0.24)]', className)}
      {...props}
    >
      <path d='M376 153H378C379.105 153 380 153.895 380 155V249C380 250.105 379.105 251 378 251H376V153Z' fill='#2A2A2E' />
      <path d='M376 276H378C379.105 276 380 276.895 380 278V372C380 373.105 379.105 374 378 374H376V276Z' fill='#2A2A2E' />
      <path d='M-2 173H0C1.10457 173 2 173.895 2 175V271C2 272.105 1.10457 273 0 273H-2V173Z' fill='#2A2A2E' />
      <rect x='0' y='0' width='378' height='830' rx='42' fill='url(#android_body)' />
      <rect x='4' y='4' width='370' height='822' rx='38' stroke='white' strokeOpacity='0.08' strokeWidth='2' />
      <rect x={screenX} y={screenY} width={screenW} height={screenH} rx='22' fill='black' />
      <circle cx='189' cy='22' r='8.5' fill='url(#android_cam)' />
      <rect x='160' y='19.5' width='58' height='5' rx='2.5' fill='#2B2E35' />

      <foreignObject
        x={screenX}
        y={screenY}
        width={screenW}
        height={screenH}
        clipPath={`url(#${clipId})`}
      >
        <div
          style={{
            width: '100%',
            height: '100%',
            overflow: 'hidden',
            borderRadius: '22px',
            background: '#000',
          }}
        >
          {children}
        </div>
      </foreignObject>

      <defs>
        <linearGradient id='android_body' x1='189' y1='0' x2='189' y2='830' gradientUnits='userSpaceOnUse'>
          <stop stopColor='#17181C' />
          <stop offset='1' stopColor='#0E1015' />
        </linearGradient>
        <radialGradient id='android_cam' cx='0' cy='0' r='1' gradientUnits='userSpaceOnUse' gradientTransform='translate(189 22) rotate(90) scale(8.5)'>
          <stop stopColor='#3A3D45' />
          <stop offset='1' stopColor='#1A1C22' />
        </radialGradient>
        <clipPath id={clipId}>
          <rect x={screenX} y={screenY} width={screenW} height={screenH} rx='22' />
        </clipPath>
      </defs>
    </svg>
  );
}
