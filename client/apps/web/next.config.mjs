import { execSync } from "node:child_process"

// Auto-populate NEXT_PUBLIC_BUILD_SHA from Vercel's git env (set in every
// Vercel build) or fall back to local `git rev-parse` so the attestation
// widget always has a real SHA to display. NEXT_PUBLIC_IMAGE_DIGEST still
// needs to be set explicitly per deploy — we don't know which docker image
// the CVM is running just from the frontend repo.
function readBuildSha() {
  if (process.env.NEXT_PUBLIC_BUILD_SHA) return process.env.NEXT_PUBLIC_BUILD_SHA
  if (process.env.VERCEL_GIT_COMMIT_SHA) return process.env.VERCEL_GIT_COMMIT_SHA.slice(0, 12)
  try {
    return execSync("git rev-parse --short=12 HEAD", { stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim()
  } catch {
    return "unknown"
  }
}

process.env.NEXT_PUBLIC_BUILD_SHA = readBuildSha()

/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["@workspace/ui"],
}

export default nextConfig
