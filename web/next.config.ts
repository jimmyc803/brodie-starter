import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: { serverActions: { bodySizeLimit: "4mb" } },
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
