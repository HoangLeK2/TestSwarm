import { useEffect } from 'react';
import { useMinimumLoading } from './use-minimum-loading';

interface UseDataTableLoadingOptions {
  isLoading: boolean;
  minDuration?: number; // in milliseconds, default 2000 (2s)
}

interface UseDataTableLoadingReturn {
  isMinLoading: boolean;
  loadingProps: {
    isLoading: boolean;
    content?: React.ReactNode;
  };
}

export function useDataTableLoading({
  isLoading,
  minDuration = 2000
}: UseDataTableLoadingOptions): UseDataTableLoadingReturn {
  const { isMinLoading, startLoading, stopLoading } = useMinimumLoading({
    minDuration
  });

  useEffect(() => {
    if (isLoading) {
      startLoading();
    } else {
      stopLoading();
    }
  }, [isLoading, startLoading, stopLoading]);

  return {
    isMinLoading,
    loadingProps: {
      isLoading: isMinLoading
    }
  };
}
