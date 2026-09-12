/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  turbopack: { root: __dirname },
};

module.exports = nextConfig;
