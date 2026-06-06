/** @type {import('next').NextConfig} */
const nextConfig = {
  // ...existing code...
  webpack: (config, { dev, isServer }) => {
    if (dev) {
      config.watchOptions = {
        poll: 1000,         // 1초마다 폴링
        aggregateTimeout: 300,
      };
    }
    return config;
  },
};

export default nextConfig;