import './globals.css';
import type { ReactNode } from 'react';

export const metadata = {
  title: 'plano-3d · panel',
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
