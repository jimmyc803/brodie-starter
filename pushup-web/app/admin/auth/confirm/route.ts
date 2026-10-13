import { ADMIN_REALM, isAllowlisted } from "@/lib/admin";

/**
 * Admin magic-link landing. The sign-in email sets redirect_to = {NEXT_PUBLIC_SITE_URL}/admin/auth/confirm, so the
 * Supabase email template link is `{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=email`.
 *
 * GET never spends the token (email link scanners prefetch links); it renders a button that POSTs it back.
 * POST requires a same-origin request AND the login-nonce cookie set by "Email me a code" in this browser, bound to
 * the same email the token belongs to (blocks login CSRF), then admin_allowlist membership. Shared realm code:
 * lib/auth-session.ts.
 */
export const { GET, POST } = ADMIN_REALM.confirmRoute({
  action: "/admin/auth/confirm",
  loginPath: "/admin/login",
  successPath: "/admin",
  heading: "Admin sign-in",
  authorize: async (email) => ((await isAllowlisted(email)) ? "ok" : "forbidden"),
});
