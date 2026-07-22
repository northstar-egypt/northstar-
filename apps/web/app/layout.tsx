import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
