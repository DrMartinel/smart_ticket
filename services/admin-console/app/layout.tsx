import type { Metadata } from "next";
import { Suspense } from "react";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import AppShell from "@/components/AppShell";
import { TourProvider } from "@/components/tour/TourProvider";

const sans = IBM_Plex_Sans({ subsets: ["latin", "latin-ext"], weight: ["400", "500", "600"], variable: "--font-plex-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

export const metadata: Metadata = {
  title: "Smart Ticket · Support console",
  description: "Tickets, review, routing and help-page governance for Smart Ticket Triage. Humans decide, AI proposes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <AuthProvider>
          <Suspense>
            <TourProvider>
              <AppShell>{children}</AppShell>
            </TourProvider>
          </Suspense>
        </AuthProvider>
      </body>
    </html>
  );
}
