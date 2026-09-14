import type { NextConfig } from 'next';
// import { withSentryConfig } from '@sentry/nextjs';
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin();

function extraDevOrigins(): string[] {
  const origins = new Set<string>([
    'http://localhost:3000',
    'http://127.0.0.1:3000'
  ]);
  const apiUrl = process.env.NEXT_PUBLIC_PRODUCT_API_URL ?? '';
  try {
    const backend = new URL(apiUrl);
    if (
      backend.hostname &&
      backend.hostname !== 'localhost' &&
      backend.hostname !== '127.0.0.1'
    ) {
      origins.add(`http://${backend.hostname}:3000`);
    }
  } catch {
    // ignore
  }
  return Array.from(origins);
}

// Define the base Next.js configuration
const baseConfig: NextConfig = {
  reactStrictMode: false, // Disable to prevent InversifyJS double-registration in flowgram.ai
  output: 'standalone',
  // Cho phép truy cập dev từ IP nội bộ (vd. 172.16.0.86) tránh cảnh báo cross-origin _next/*
  allowedDevOrigins: extraDevOrigins(),
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 's3-sgn10.fptcloud.com',
        port: ''
      },
      {
        protocol: 'https',
        hostname: 'lh3.googleusercontent.com',
        port: ''
      }
    ]
  },
  compiler: {
    // removeConsole: process.env.NEXT_PUBLIC_ENVIRONMENT !== 'dev'
  },
  transpilePackages: ['geist'],
  webpack(config, { isServer }) {
    if (!isServer) {
      // jmuxer uses Node.js stream module — polyfill for browser
      config.resolve.fallback = {
        ...(config.resolve.fallback ?? {}),
        stream: require.resolve('stream-browserify')
      };
    }
    return config;
  }
};

const configWithPlugins = baseConfig;

// Conditionally enable Sentry configuration
// if (!process.env.NEXT_PUBLIC_SENTRY_DISABLED) {
//   configWithPlugins = withSentryConfig(configWithPlugins, {
//     // For all available options, see:
//     // https://www.npmjs.com/package/@sentry/webpack-plugin#options
//     // FIXME: Add your Sentry organization and project names
//     org: process.env.NEXT_PUBLIC_SENTRY_ORG,
//     project: process.env.NEXT_PUBLIC_SENTRY_PROJECT,
//     // Only print logs for uploading source maps in CI
//     silent: !process.env.CI,

//     // For all available options, see:
//     // https://docs.sentry.io/platforms/javascript/guides/nextjs/manual-setup/

//     // Upload a larger set of source maps for prettier stack traces (increases build time)
//     widenClientFileUpload: true,

//     // Upload a larger set of source maps for prettier stack traces (increases build time)
//     reactComponentAnnotation: {
//       enabled: true
//     },

//     // Route browser requests to Sentry through a Next.js rewrite to circumvent ad-blockers.
//     // This can increase your server load as well as your hosting bill.
//     // Note: Check that the configured route will not match with your Next.js middleware, otherwise reporting of client-
//     // side errors will fail.
//     tunnelRoute: '/monitoring',

//     // Automatically tree-shake Sentry logger statements to reduce bundle size
//     disableLogger: true,

//     // Disable Sentry telemetry
//     telemetry: false
//   });
// }

const nextConfig = withNextIntl(configWithPlugins);
export default nextConfig;
