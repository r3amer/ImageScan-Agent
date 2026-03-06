import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // 高对比度暗色主题 - 提升可读性
        terminal: {
          black: '#050505',        // 更深的背景
          dark: '#0d0d0d',         // 卡片背景
          gray: '#141414',         // 次级背景
          light: '#e0e0e0',        // 主要文字 - 大幅提升亮度
          muted: '#9ca3af',        // 次要文字 - 中等亮度
          dim: '#4b5563',          // 暗淡文字 - 保持可读
        },
        neon: {
          green: '#00ff41',        // 经典终端绿
          green_dim: 'rgba(0, 255, 65, 0.15)',
          orange: '#ff9500',       // 更亮的橙色
          red: '#ff3366',          // 更亮的红色
          cyan: '#00f3ff',         // 更亮的青色
        }
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        terminal: ['"Fira Code"', 'monospace'],
      },
      backgroundImage: {
        'scanline': 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0, 255, 65, 0.03) 2px, rgba(0, 255, 65, 0.03) 4px)',
        'grid-pattern': 'linear-gradient(to right, #1a1a1a 1px, transparent 1px), linear-gradient(to bottom, #1a1a1a 1px, transparent 1px)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'scan': 'scan 2s linear infinite',
        'blink': 'blink 1s step-end infinite',
      },
      keyframes: {
        scan: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100%)' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
      },
    },
  },
  plugins: [],
}
export default config
