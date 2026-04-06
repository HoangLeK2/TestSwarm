declare module 'jmuxer' {
  interface JMuxerOptions {
    node: HTMLVideoElement | string;
    mode?: 'video' | 'audio' | 'both';
    flushingTime?: number;
    fps?: number;
    debug?: boolean;
    onReady?: () => void;
    onError?: (data: unknown) => void;
  }

  interface FeedData {
    video?: Uint8Array;
    audio?: Uint8Array;
    duration?: number;
  }

  class JMuxer {
    constructor(options: JMuxerOptions);
    feed(data: FeedData): void;
    reset(): void;
    destroy(): void;
  }

  export default JMuxer;
}
