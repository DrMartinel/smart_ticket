import type { Metadata } from "next";
import { Suspense } from "react";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Serif } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import AppShell from "@/components/AppShell";
import { TourProvider } from "@/components/tour/TourProvider";
import { Toaster } from "@/components/ui/toast";

const sans = IBM_Plex_Sans({ subsets: ["latin", "latin-ext", "vietnamese"], weight: ["400", "500", "600"], variable: "--font-plex-sans" });
const serif = IBM_Plex_Serif({ subsets: ["latin", "latin-ext", "vietnamese"], weight: ["500", "600"], variable: "--font-plex-serif" });
const mono = IBM_Plex_Mono({ subsets: ["latin", "latin-ext", "vietnamese"], weight: ["400", "500"], variable: "--font-plex-mono" });

export const metadata: Metadata = {
  title: "Smart Ticket · Support console",
  description: "Tickets, review, routing and help-page governance for Smart Ticket Triage. Humans decide, AI proposes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable} ${mono.variable}`}>
      <body>
        <AuthProvider>
          <Suspense>
            <Toaster>
              <TourProvider>
                <AppShell>{children}</AppShell>
              </TourProvider>
            </Toaster>
          </Suspense>
        </AuthProvider>
      </body>
    </html>
  );
}
