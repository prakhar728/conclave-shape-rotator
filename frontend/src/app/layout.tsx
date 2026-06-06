import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { WorkspaceProvider } from "@/components/workspace-provider";

// Inter everywhere — weight does the hierarchy work (serif display voice
// retired 2026-06-05 by user preference). JetBrains Mono for machine ids.
const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

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
        jetbrainsMono.variable,
        "font-sans",
        inter.variable,
      )}
    >
      <body className="min-h-full flex flex-col">
        <WorkspaceProvider>{children}</WorkspaceProvider>
      </body>
    </html>
  );
}
