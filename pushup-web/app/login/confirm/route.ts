import { USER_REALM } from "@/lib/me";

/**
 * Competitor magic-link landing ({NEXT_PUBLIC_SITE_URL}/login/confirm, sent as redirect_to by /login). Same guarded
 * flow as the admin console (lib/auth-session.ts): GET only renders a confirm button; POST must be same-origin and
 * carry this browser's login nonce bound to the link's email. Gated by NEXT_PUBLIC_WEB_JOIN at the page level: the
 * nonce can only be issued by /login's action, which refuses when the feature is off.
 */
export const { GET, POST } = USER_REALM.confirmRoute({
  action: "/login/confirm",
  loginPath: "/login",
  successPath: "/me",
  heading: "Brodie sign-in",
});
