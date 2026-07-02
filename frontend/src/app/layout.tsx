import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { RecordingProvider } from "@/components/recording-provider";
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
    "Confidential team memory — every meeting remembered, searchable, and provably private inside an attested TEE.",
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
          <RecordingProvider>
            <TncGate>{children}</TncGate>
          </RecordingProvider>
        </WorkspaceProvider>
      </body>
    </html>
  );
}
