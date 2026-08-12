# Account Verification Production Rollout

Account verification compares the account assigned in Device Farm with the
identity currently visible in the Facebook app. It does not switch Facebook
sessions automatically.

## Safe Defaults

Production configuration defaults to:

```env
ACCOUNT_VERIFICATION_MODE=shadow
ACCOUNT_VERIFICATION_CONCURRENCY=8
ACCOUNT_VERIFICATION_TIMEOUT_SECONDS=6
FACEBOOK_VERIFICATION_PACKAGE=com.facebook.katana
FACEBOOK_VERIFICATION_RESOURCE_ID=
```

An empty resource ID intentionally produces `inconclusive` with reason
`trusted_selector_missing`. This is safer than matching an untrusted display
name, avatar, post author, mention, or generic profile element.

## Selector Qualification

Before setting `FACEBOOK_VERIFICATION_RESOURCE_ID`:

1. Open the account/profile switcher or another stable screen that exposes the
   active account's exact username or provider ID.
2. Capture the UIAutomator hierarchy from every supported Facebook build and
   locale.
3. Identify a resource ID whose node contains only the active account's exact
   identifier.
4. Validate that the selector does not also occur for post authors, comments,
   mentions, search results, display names, or switch-account candidates.
5. Test at least one expected match, one different active account, and one
   logged-out/unknown state.

Do not derive the selector from the example `like_btn` resource ID in hierarchy
documentation. It is unrelated to account identity.

## Rollout

1. Deploy in `shadow` mode with the qualified selector.
2. Monitor `verified`, `mismatch`, `inconclusive`, and `unsupported` results.
3. Investigate every mismatch and confirm there are no false positives across
   supported builds/locales.
4. Tune concurrency and timeout only after observing phone/relay capacity.
5. Change to `enforce` only when `verified` coverage is sufficient. In enforce
   mode, every status other than `verified` blocks execution.

Use `off` only as an explicit rollback. Keep `shadow` as the normal fallback
when a Facebook update invalidates the trusted selector.
