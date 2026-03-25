/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['class'],
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}'
  ],
  prefix: '',
  theme: {
    container: {
      center: true,
      padding: '1rem',
      screens: {
        '2xl': '1400px'
      }
    },
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))'
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))'
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))'
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))'
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))'
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))'
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))'
        },
        chart: {
          1: 'hsl(var(--chart-1))',
          2: 'hsl(var(--chart-2))',
          3: 'hsl(var(--chart-3))',
          4: 'hsl(var(--chart-4))',
          5: 'hsl(var(--chart-5))'
        },
        sidebar: {
          DEFAULT: 'hsl(var(--sidebar-background))',
          foreground: 'hsl(var(--sidebar-foreground))',
          primary: 'hsl(var(--sidebar-primary))',
          'primary-foreground': 'hsl(var(--sidebar-primary-foreground))',
          accent: 'hsl(var(--sidebar-accent))',
          'accent-foreground': 'hsl(var(--sidebar-accent-foreground))',
          border: 'hsl(var(--sidebar-border))',
          ring: 'hsl(var(--sidebar-ring))',
          active: 'hsl(var(--sidebar-active))',
          'active-foreground': 'hsl(var(--sidebar-active-foreground))'
        },
        success: {
          DEFAULT: 'hsl(var(--success))',
          foreground: 'hsl(var(--success-foreground))'
        },
        error: {
          DEFAULT: 'hsl(var(--error))',
          foreground: 'hsl(var(--error-foreground))'
        },
        warning: {
          DEFAULT: 'hsl(var(--warning))',
          foreground: 'hsl(var(--warning-foreground))'
        },
        info: {
          DEFAULT: 'hsl(var(--info))',
          foreground: 'hsl(var(--info-foreground))'
        }
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
        xl: 'calc(var(--radius) + 4px)'
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' }
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' }
        },
        'caret-blink': {
          '0%,70%,100%': { opacity: '1' },
          '20%,50%': { opacity: '0' }
        },
        reveal: {
          from: {
            'clip-path': 'circle(0% at var(--x, 50%) var(--y, 50%))',
            opacity: '0.7'
          },
          to: {
            'clip-path': 'circle(150% at var(--x, 50%) var(--y, 50%))',
            opacity: '1'
          }
        },
        // VC Revoke Animations
        'dashed-flow': {
          from: { backgroundPosition: '64px 0' },
          to: { backgroundPosition: '0 0' }
        },
        'dashed-flow-left': {
          from: { backgroundPosition: '0 0' },
          to: { backgroundPosition: '64px 0' }
        },
        'arrow-flow': {
          '0%': {
            right: '0',
            opacity: '1',
            boxShadow:
              '0 0 8px rgba(251, 146, 60, 0.4), 0 2px 4px rgba(0, 0, 0, 0.1)'
          },
          '25%': {
            boxShadow:
              '0 0 16px rgba(251, 146, 60, 0.6), 0 2px 8px rgba(0, 0, 0, 0.15)'
          },
          '50%': {
            boxShadow:
              '0 0 8px rgba(251, 146, 60, 0.4), 0 2px 4px rgba(0, 0, 0, 0.1)'
          },
          '75%': {
            boxShadow:
              '0 0 16px rgba(251, 146, 60, 0.6), 0 2px 8px rgba(0, 0, 0, 0.15)'
          },
          '95%': { opacity: '1' },
          '100%': {
            right: '100%',
            opacity: '0',
            boxShadow:
              '0 0 8px rgba(251, 146, 60, 0.4), 0 2px 4px rgba(0, 0, 0, 0.1)'
          }
        },
        'step-pulse': {
          '0%, 100%': {
            transform: 'scale(1)',
            boxShadow:
              '0 0 0 0 rgba(251, 146, 60, 0.7), 0 2px 4px rgba(0, 0, 0, 0.1)'
          },
          '50%': {
            transform: 'scale(1.05)',
            boxShadow:
              '0 0 0 8px rgba(251, 146, 60, 0), 0 4px 12px rgba(251, 146, 60, 0.3)'
          }
        },
        'step-pulse-left': {
          '0%, 100%': {
            transform: 'scale(1)',
            boxShadow:
              '0 0 0 0 rgba(127, 174, 249, 0.7), 0 2px 4px rgba(0, 0, 0, 0.1)'
          },
          '50%': {
            transform: 'scale(1.05)',
            boxShadow:
              '0 0 0 8px rgba(127, 174, 249, 0), 0 4px 12px rgba(127, 174, 249, 0.3)'
          }
        }
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'caret-blink': 'caret-blink 1.25s ease-out infinite',
        reveal: 'reveal 0.4s ease-in-out forwards',
        // VC Revoke Animations
        'dashed-flow': 'dashed-flow 2s linear infinite',
        'dashed-flow-left': 'dashed-flow-left 2s linear infinite',
        'arrow-flow': 'arrow-flow 4s linear infinite',
        'step-pulse': 'step-pulse 2s ease-in-out infinite',
        'step-idle': 'step-pulse-left 2s ease-in-out infinite'
      },
      boxShadow: {
        xs: '0 1px 2px 0 rgb(0 0 0 / 0.05)'
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui'],
        mono: ['var(--font-mono)', 'ui-monospace', 'monospace']
      },
      spacing: {
        header: 'var(--header-height)'
      },
      fontSize: {
        base: ['var(--text-base, 0.875rem)', { lineHeight: '1.5' }],
        sm: ['var(--text-sm, 0.8125rem)', { lineHeight: '1.5' }],
        lg: ['var(--text-lg, 1rem)', { lineHeight: '1.5' }]
      }
    }
  },
  plugins: [require('tailwindcss-animate')]
};
