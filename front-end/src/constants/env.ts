declare const process: {
  env: Record<string, string | undefined>;
};

export const env = {
  API_PRODUCT_URL: process.env.NEXT_PUBLIC_PRODUCT_API_URL || '',
  ENVIRONMENT: process.env.NEXT_PUBLIC_ENVIRONMENT || 'dev'
};
