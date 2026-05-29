/** Supported social platforms for accounts and account groups. */
export const ACCOUNT_PLATFORM_OPTIONS = [
  'facebook',
  'instagram',
  'tiktok',
  'linkedin'
] as const;

export type AccountPlatform = (typeof ACCOUNT_PLATFORM_OPTIONS)[number];

export const ACCOUNT_PLATFORM_SELECT_OPTIONS: Array<{
  value: AccountPlatform;
  labelKey:
    | 'platformFacebook'
    | 'platformInstagram'
    | 'platformTiktok'
    | 'platformLinkedin';
}> = [
  { value: 'facebook', labelKey: 'platformFacebook' },
  { value: 'instagram', labelKey: 'platformInstagram' },
  { value: 'tiktok', labelKey: 'platformTiktok' },
  { value: 'linkedin', labelKey: 'platformLinkedin' }
];
