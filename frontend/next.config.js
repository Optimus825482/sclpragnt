/** @type {import('next').NextConfig} */
const { execSync } = require("child_process");

const getBuildId = () => {
  try {
    const commit = execSync("git rev-parse --short HEAD").toString().trim();
    return `${Date.now().toString(36)}-${commit}`;
  } catch {
    return Date.now().toString(36);
  }
};

const BUILD_ID = getBuildId();

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  generateBuildId: () => BUILD_ID,
  env: {
    NEXT_PUBLIC_BUILD_ID: BUILD_ID,
  },
};

module.exports = nextConfig;
