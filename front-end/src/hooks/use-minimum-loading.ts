import { useState, useEffect, useRef } from 'react';

interface UseMinimumLoadingOptions {
  minDuration?: number; // in milliseconds, default 2000 (2s)
}

interface UseMinimumLoadingReturn {
  isMinLoading: boolean;
  startLoading: () => void;
  stopLoading: () => void;
}

export function useMinimumLoading({
  minDuration = 2000
}: UseMinimumLoadingOptions = {}): UseMinimumLoadingReturn {
  const [isLoading, setIsLoading] = useState(false);
  const [isMinLoading, setIsMinLoading] = useState(false);
  const startTimeRef = useRef<number | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const startLoading = () => {
    startTimeRef.current = Date.now();
    setIsLoading(true);
    setIsMinLoading(true);
  };

  const stopLoading = () => {
    setIsLoading(false);

    if (startTimeRef.current) {
      const elapsed = Date.now() - startTimeRef.current;
      const remaining = Math.max(0, minDuration - elapsed);

      if (remaining > 0) {
        // Still need to wait to meet minimum duration
        timeoutRef.current = setTimeout(() => {
          setIsMinLoading(false);
          startTimeRef.current = null;
        }, remaining);
      } else {
        // Minimum duration already met
        setIsMinLoading(false);
        startTimeRef.current = null;
      }
    } else {
      setIsMinLoading(false);
    }
  };

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, []);

  return {
    isMinLoading,
    startLoading,
    stopLoading
  };
}
