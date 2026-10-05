/** Supported social platforms for accounts and account groups. */
export const ACCOUNT_PLATFORM_OPTIONS = [
  'instagram',
  'tiktok',
  'linkedin'
] as const;

export type AccountPlatform = (typeof ACCOUNT_PLATFORM_OPTIONS)[number];

export const ACCOUNT_PLATFORM_SELECT_OPTIONS: Array<{
  value: AccountPlatform;
  labelKey: 'platformInstagram' | 'platformTiktok' | 'platformLinkedin';
}> = [
  { value: 'instagram', labelKey: 'platformInstagram' },
  { value: 'tiktok', labelKey: 'platformTiktok' },
  { value: 'linkedin', labelKey: 'platformLinkedin' }
];
