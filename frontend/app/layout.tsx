import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'ImageScan | Container Security Scanner',
  description: 'Intelligent Docker image credential scanner powered by LLM',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
      </head>
      <body className="min-h-screen">
        {children}
      </body>
    </html>
  )
}
