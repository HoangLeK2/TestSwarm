import test from 'node:test';
import assert from 'node:assert/strict';

import { formatPublicAuthError } from './public-auth-error';

test('formatPublicAuthError hides network diagnostics on public auth screens', () => {
  const message = formatPublicAuthError(
    { code: 'ERR_NETWORK', message: 'Network Error' },
    'Đăng nhập thất bại',
    'Không kết nối được máy chủ. Vui lòng thử lại sau.'
  );

  assert.equal(message, 'Không kết nối được máy chủ. Vui lòng thử lại sau.');
  assert.doesNotMatch(message, /docker|NEXT_PUBLIC|front-end\/\.env|8081/i);
});

test('formatPublicAuthError keeps backend auth error details', () => {
  assert.equal(
    formatPublicAuthError(
      { response: { data: { detail: { code: 'INVALID_CREDENTIALS' } } } },
      'Đăng nhập thất bại',
      'Không kết nối được máy chủ. Vui lòng thử lại sau.'
    ),
    'Sai thông tin đăng nhập'
  );
});
