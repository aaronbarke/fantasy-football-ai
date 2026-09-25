const isProd = process.env.NODE_ENV === "production";

function origin(url) {
  try {
    return new URL(url).origin;
  } catch {
    return "";
  }
}

const apiOrigin = origin(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000");

// Where the app actually loads things from: the API, Sleeper/ESPN player and
// team images, and Google Identity Services for "Continue with Google".
// Blocking everything else means injected script can't ship tokens off to an
// attacker's server with fetch, and the app can't be framed for clickjacking.
const contentSecurityPolicy = [
  "default-src 'self'",
  // Next.js hydrates the App Router with inline <script> tags, so inline
  // scripts stay allowed until the app adopts nonce-based CSP.
  "script-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/client",
  "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
  "img-src 'self' data: blob: https://sleepercdn.com https://a.espncdn.com",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin} https://accounts.google.com/gsi/`,
  "frame-src https://accounts.google.com/gsi/",
  "worker-src 'self'",
  "manifest-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  },
  // Google's sign-in popup has to be able to message back to this window.
  { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
  // Dev mode needs eval for hot reloading, so the CSP is production-only.
  ...(isProd
    ? [
        { key: "Content-Security-Policy", value: contentSecurityPolicy },
        {
          key: "Strict-Transport-Security",
          value: "max-age=63072000; includeSubDomains; preload",
        },
      ]
    : []),
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

module.exports = nextConfig;
