import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { WorkspaceProvider } from "@/components/workspace-provider";
import { TncGate } from "@/components/tnc-gate";

// Inter for body, Space Grotesk for headings, JetBrains Mono for machine ids.
const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-heading" });

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
        inter.variable,
        spaceGrotesk.variable,
      )}
    >
      <body className="min-h-full flex flex-col">
        <WorkspaceProvider>
          <TncGate>{children}</TncGate>
        </WorkspaceProvider>
      </body>
    </html>
  );
}
