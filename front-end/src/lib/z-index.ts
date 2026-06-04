/** Sheet, drawer overlay, sticky header. */
export const Z_OVERLAY = 50;

/** Portaled selects, popovers, dropdowns — above sheet, below dialog stack. */
export const Z_FLOATING = 10050;

/** Dialog overlay (see dialog.tsx DEFAULT_DIALOG_Z_INDEX). */
export const Z_DIALOG = 9999;

/** Campaign monitor modal — above global floating chrome (Z_FLOATING). */
export const Z_CAMPAIGN_MONITOR = 11000;

/** Portaled selects/menus/tooltips opened inside campaign monitor. */
export const Z_CAMPAIGN_MONITOR_FLOATING = Z_CAMPAIGN_MONITOR + 20;

/** Nested dialogs inside campaign monitor (artifact preview, DLQ confirm, detail sheet). */
export const Z_CAMPAIGN_MONITOR_NESTED = Z_CAMPAIGN_MONITOR + 30;
