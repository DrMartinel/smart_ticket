import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import NavBar from "@/components/NavBar";

export const metadata: Metadata = {
  title: "Smart Ticket Triage",
  description: "AI-assisted ITSM ticket triage — humans decide, AI proposes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <NavBar />
          <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
