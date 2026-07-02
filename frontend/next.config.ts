import type { NextConfig } from "next";

/**
 * Conclave frontend config.
 *
 * Rewrites: `/api/*` on the Next.js dev server (3001) proxies to the
 * FastAPI backend at `http://localhost:8000/*`. Same-origin in the browser
 * means no CORS plumbing and httpOnly cookies "just work". In prod both
 * services sit behind a single domain via reverse proxy, so the same
 * `/api/*` paths still resolve.
 *
 * `NEXT_PUBLIC_API_BASE` overrides the dev target if you want to point at
 * a remote backend — keep it set to http://localhost:8000 for the §14
 * local-dev runbook.
 *
 * NOTE: order matters in rewrites; more specific paths first.
 */
const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      // Auth lives at /auth/v1/* on FastAPI (not under /api). Surface it
      // through /api/auth/v1/* on the frontend so all backend calls share
      // the same /api/ prefix from the browser's perspective.
      {
        source: "/api/auth/:path*",
        destination: `${apiBase}/auth/:path*`,
      },
      // Transcripts read endpoints (legacy, no /api prefix on FastAPI).
      {
        source: "/api/transcripts/:path*",
        destination: `${apiBase}/transcripts/:path*`,
      },
      // Attestation lives at /attestation (no /api prefix on FastAPI).
      {
        source: "/api/attestation",
        destination: `${apiBase}/attestation`,
      },
      // Everything else (workspaces, etc.) — FastAPI already mounts them
      // under /api.
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
