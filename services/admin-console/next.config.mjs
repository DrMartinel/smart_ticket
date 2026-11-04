/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async redirects() {
    return [
      "/dashboard",
      "/reports",
      "/reports/:path*",
      "/security/summary",
      "/kb/authority",
      "/kb/authority-log",
      "/settings",
      "/settings/:path*",
    ]
      .map((source) => ({ source, destination: `/admin${source}`, permanent: true }))
      .concat({ source: "/admin/settings/stages", destination: "/admin/settings/workflows", permanent: true });
  },
};

export default nextConfig;
