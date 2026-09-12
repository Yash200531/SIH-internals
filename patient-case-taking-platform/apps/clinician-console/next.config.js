/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  output: "standalone",
  outputFileTracingRoot: `${__dirname}/../..`,
  turbopack: { root: `${__dirname}/../..` },
};

module.exports = nextConfig;
