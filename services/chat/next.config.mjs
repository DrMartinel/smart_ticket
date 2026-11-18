/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async redirects() {
    return [{ source: "/assistant", destination: "/", permanent: true }];
  },
};

export default nextConfig;
