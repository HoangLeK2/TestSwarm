import { pathToFileURL } from 'node:url';
import { resolve as resolvePath } from 'node:path';

const SRC_ALIAS_PREFIX = '@/';
const SRC_ROOT_URL = pathToFileURL(resolvePath('src')).href;
const TS_EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx', '.mjs'];

function hasKnownExtension(specifier) {
  return /\.[cm]?[jt]sx?$/.test(specifier);
}

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith(SRC_ALIAS_PREFIX)) {
    const path = `${SRC_ROOT_URL}/${specifier.slice(SRC_ALIAS_PREFIX.length)}`;
    for (const ext of ['', ...TS_EXTENSIONS]) {
      try {
        return await nextResolve(`${path}${ext}`, context);
      } catch (error) {
        if (error?.code !== 'ERR_MODULE_NOT_FOUND') throw error;
      }
    }
  }

  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (
      error?.code === 'ERR_MODULE_NOT_FOUND' &&
      (specifier.startsWith('./') || specifier.startsWith('../')) &&
      !hasKnownExtension(specifier)
    ) {
      for (const ext of TS_EXTENSIONS) {
        try {
          return await nextResolve(`${specifier}${ext}`, context);
        } catch (retryError) {
          if (retryError?.code !== 'ERR_MODULE_NOT_FOUND') throw retryError;
        }
      }
    }
    throw error;
  }
}
