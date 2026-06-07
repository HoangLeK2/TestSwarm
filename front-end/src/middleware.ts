import createMiddleware from 'next-intl/middleware';
import { routing } from './i18n/routing';

export default createMiddleware(routing);

export const config = {
  // Match all pathnames except for
  // - … if they start with backend/media proxy routes (`/api`, `/stream`, `/screenshot`)
  // - … if they start with `/trpc`, `/_next` or `/_vercel`
  // - … the ones containing a dot (e.g. `favicon.ico`)
  matcher: '/((?!api|stream|screenshot|trpc|_next|_vercel|.*\\..*).*)'
};
