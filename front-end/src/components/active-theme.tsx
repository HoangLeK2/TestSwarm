'use client';

import {
  ReactNode,
  createContext,
  useContext,
  useEffect,
  useState
} from 'react';

const COOKIE_NAME = 'active_theme';
const DEFAULT_THEME = 'blue';

function setThemeCookie(theme: string) {
  if (typeof window === 'undefined') return;

  document.cookie = `${COOKIE_NAME}=${theme}; path=/; max-age=31536000; SameSite=Lax; ${window.location.protocol === 'https:' ? 'Secure;' : ''}`;
}

type ThemeContextType = {
  activeTheme: string;
  setActiveTheme: (theme: string) => void;
};

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ActiveThemeProvider({
  children,
  initialTheme
}: {
  children: ReactNode;
  initialTheme?: string;
}) {
  const [activeTheme, setActiveThemeState] = useState<string>(
    () => initialTheme || DEFAULT_THEME
  );
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const setActiveTheme = (theme: string) => {
    setActiveThemeState(theme);

    if (typeof window === 'undefined') return;

    setThemeCookie(theme);

    // Remove old theme classes
    Array.from(document.body.classList)
      .filter((className) => className.startsWith('theme-'))
      .forEach((className) => {
        document.body.classList.remove(className);
      });

    // Add new theme classes
    document.body.classList.add(`theme-${theme}`);
    if (theme.endsWith('-scaled')) {
      document.body.classList.add('theme-scaled');
    }
  };

  const contextValue = {
    activeTheme,
    setActiveTheme
  };

  return (
    <ThemeContext.Provider value={contextValue}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useThemeConfig() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error(
      'useThemeConfig must be used within an ActiveThemeProvider'
    );
  }
  return context;
}
