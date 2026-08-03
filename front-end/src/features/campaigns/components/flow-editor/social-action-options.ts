export type SocialActionOption = {
  value: string;
  label: string;
};

const SOCIAL_ACTION_OPTIONS: Record<string, SocialActionOption[]> = {
  content_interaction: [
    { value: 'like', label: 'Thích bài viết' },
    { value: 'comment', label: 'Bình luận' },
    { value: 'share', label: 'Chia sẻ' }
  ],
  connection_request: [{ value: 'request', label: 'Gửi lời mời kết bạn' }],
  community_membership: [{ value: 'join', label: 'Tham gia nhóm' }]
};

export function getSocialActionOptions(type: string): SocialActionOption[] {
  return SOCIAL_ACTION_OPTIONS[type] ?? [];
}

export function defaultSocialAction(type: string): string {
  return getSocialActionOptions(type)[0]?.value ?? '';
}
