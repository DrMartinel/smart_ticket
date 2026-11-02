import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";
import { Suspense } from "react";
import { AuthProvider } from "@/lib/auth";
import { TourProvider } from "@/components/tour/TourProvider";

const sans = IBM_Plex_Sans({ subsets: ["latin", "latin-ext"], weight: ["400", "500", "600"], variable: "--font-plex-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

export const metadata: Metadata = {
  title: "IT Help",
  description: "Ask IT a question. Answers come from approved knowledge-base pages; anything else goes to a person.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <AuthProvider>
          <Suspense>
            <TourProvider>{children}</TourProvider>
          </Suspense>
        </AuthProvider>
      </body>
    </html>
  );
}
