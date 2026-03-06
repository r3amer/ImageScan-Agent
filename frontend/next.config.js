/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  // 反向代理配置
  async rewrites() {
    const backendUrl = 'http://127.0.0.1:8000'  // 使用 127.0.0.1 避免 IPv6 解析
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: '/health',
        destination: `${backendUrl}/health`,
      },
    ]
  },
}

module.exports = nextConfig
