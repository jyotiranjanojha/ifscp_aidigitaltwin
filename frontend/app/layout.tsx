import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AI Digital Twin - Supply Chain Simulator',
  description: 'Upload Blue Yonder S&OP files, adjust risk parameters, and visualize optimized supply chain allocations',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-gray-50 dark:bg-gray-900 antialiased">
        {children}
      </body>
    </html>
  );
}