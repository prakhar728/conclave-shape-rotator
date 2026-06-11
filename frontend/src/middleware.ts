/**
 * Edge auth middleware — gates protected routes by the presence of the
 * `conclave_session` httpOnly cookie.
 *
 * We don't validate the token here (it's opaque server-state on FastAPI;
 * validation requires a DB hit). Presence is a cheap good-enough check:
 *   - real users have it after /auth/v1/verify-otp
 *   - protected pages call /api/auth/v1/me on mount; that's where actual
 *     validation happens, with a clean 401 → redirect path
 *
 * The middleware just prevents the obvious case of someone deep-linking
 * `/dashboard` while completely logged out.
 *
 * Mirror also pushes already-authed users away from `/login` and
 * `/signup` so they don't accidentally restart the OTP flow.
 */
import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "conclave_session";

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/workspace",
  "/meeting",
  "/invite",
  "/questions",
  "/entities",
  "/entity",
  "/obligations",
  "/search",
  "/graph",
  "/settings",
];
const AUTH_PAGES = new Set(["/login", "/signup"]);

export function middleware(req: NextRequest) {
  const hasSession = Boolean(req.cookies.get(SESSION_COOKIE)?.value);
  const url = req.nextUrl.clone();
  const path = url.pathname;

  const isProtected = PROTECTED_PREFIXES.some(
    (p) => path === p || path.startsWith(`${p}/`),
  );

  if (isProtected && !hasSession) {
    url.pathname = "/login";
    url.searchParams.set("next", path);
    return NextResponse.redirect(url);
  }

  if (AUTH_PAGES.has(path) && hasSession) {
    url.pathname = "/dashboard";
    url.searchParams.delete("next");
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/workspace/:path*",
    "/meeting/:path*",
    "/invite/:path*",
    "/questions/:path*",
    "/settings/:path*",
    "/login",
    "/signup",
  ],
};
