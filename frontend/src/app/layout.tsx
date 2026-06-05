import type { Metadata } from "next";
import { Geist, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";

// Geist for body — clean Proton-style utilitarian sans (BUILD_DOC §4).
const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

// Instrument Serif for display headings + the wordmark — the "Editorial
// Vault" voice: classic dossier gravitas over a utilitarian body. The face
// ships 400-only (normal + italic); weight discipline is the point.
const instrumentSerif = Instrument_Serif({
  weight: "400",
  style: ["normal", "italic"],
  subsets: ["latin"],
  variable: "--font-serif",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Conclave",
  description:
    "A privacy-preserving knowledge layer for your team's conversations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={cn(
        "h-full",
        "antialiased",
        "dark",
        jetbrainsMono.variable,
        instrumentSerif.variable,
        "font-sans",
        geist.variable,
      )}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
