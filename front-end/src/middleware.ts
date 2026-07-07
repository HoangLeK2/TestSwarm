import createMiddleware from 'next-intl/middleware';
import { routing } from './i18n/routing';

export default createMiddleware(routing);

export const config = {
  // Match all pathnames except for
  // - … `/api` (legacy same-origin calls — must not get a locale prefix)
  // - … media streaming routes served by the farm backend
  // - … if they start with `/trpc`, `/_next` or `/_vercel`
  // - … the ones containing a dot (e.g. `favicon.ico`)
  matcher:
    '/((?!api|stream|screenshot|screenshot-b64|trpc|_next|_vercel|.*\\..*).*)'
};
