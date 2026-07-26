import "./globals.css";
import type { Metadata } from "next";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "ApexAI",
  description: "Multi-tenant AI agent platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
