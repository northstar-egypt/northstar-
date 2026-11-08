import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Sans_Arabic } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

// One design family for both scripts, so a page of Arabic player names and English labels reads
// as one voice. Latin first in the stack: the Arabic face only supplies the Arabic glyphs. Served
// from the app itself (next/font downloads them at build time), not fetched by the visitor.
const plex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex",
  display: "swap",
});
const plexArabic = IBM_Plex_Sans_Arabic({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-arabic",
  display: "swap",
});

export const metadata: Metadata = {
  title: "NorthStar",
  description:
    "A national talent database and intelligence platform for Egyptian sports.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${plex.variable} ${plexArabic.variable}`}>
      <body className="font-sans">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
