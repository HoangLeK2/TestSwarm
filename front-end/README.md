# Device farm

A comprehensive product traceability and supply chain management platform built with Next.js 15 and modern web technologies. The system enables organizations to track products through GTIN (Global Trade Item Number) and SGTIN (Serialized Global Trade Item Number) standards, providing full supply chain visibility and anti-counterfeiting capabilities.

## System Overview

Device farm is an enterprise-grade traceability management system that facilitates:

- **Product Registration and Management**: Complete product lifecycle management with GTIN generation and validation
- **Serial Number Tracking**: SGTIN-based individual item tracking and authentication
- **Organization Management**: Multi-tenant architecture supporting organization hierarchies
- **Batch Management**: Production batch tracking and quality control
- **Statistical Analytics**: Real-time dashboard with industry insights and traceability metrics
- **Supply Chain Verification**: End-to-end product authentication and verification workflows

## Technical Architecture

### Core Technologies

- **Framework**: Next.js 15 with App Router
- **Runtime**: React 19
- **Language**: TypeScript 5.7
- **State Management**: Zustand
- **UI Framework**: Tailwind CSS with Shadcn/ui components
- **Data Fetching**: TanStack Query (React Query)
- **Form Management**: React Hook Form with Zod validation
- **Internationalization**: next-intl (English/Vietnamese support)
- **Rich Text Editor**: Lexical framework
- **Error Monitoring**: Sentry integration

### Development Tools

- **Package Manager**: pnpm
- **Linting**: ESLint with TypeScript integration
- **Formatting**: Prettier with Tailwind plugin
- **Git Hooks**: Husky with lint-staged
- **API Generation**: swagger-typescript-api
- **Build Tool**: Next.js with Turbopack

## Project Structure

```plaintext
src/
├── app/ # Next.js App Router directory
│ ├── (auth)/ # Auth route group
│ │ ├── (signin)/
│ ├── (dashboard)/ # Dashboard route group
│ │ ├── layout.tsx
│ │ ├── loading.tsx
│ │ └── page.tsx
│ └── api/ # API routes
│
├── components/ # Shared components
│ ├── ui/ # UI components (buttons, inputs, etc.)
│ └── layout/ # Layout components (header, sidebar, etc.)
│
├── features/ # Feature-based modules
│ ├── feature/
│ │ ├── components/ # Feature-specific components
│ │ ├── actions/ # Server actions
│ │ ├── schemas/ # Form validation schemas
│ │ └── utils/ # Feature-specific utilities
│ │
├── lib/ # Core utilities and configurations
│ ├── auth/ # Auth configuration
│ ├── db/ # Database utilities
│ └── utils/ # Shared utilities
│
├── hooks/ # Custom hooks
│ └── use-debounce.ts
│
├── stores/ # Zustand stores
│ └── dashboard-store.ts
│
└── types/ # TypeScript types
└── index.ts
```
