import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost" },
      { protocol: "http", hostname: "127.0.0.1" },
      { protocol: "https", hostname: "*.aryanoble.web.id" },
      { protocol: "https", hostname: "*.aryanoble.co.id" },
    ],
  },
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL
      ? process.env.NEXT_PUBLIC_API_URL.replace(/\/api\/?$/, "")
      : "http://127.0.0.1:8000";
    return [
      {
        source: "/api/storage/:path*",
        destination: `${backendUrl}/api/storage/:path*`,
      },
    ];
  },
};

export default nextConfig;
