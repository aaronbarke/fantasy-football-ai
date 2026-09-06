import type { Metadata, Viewport } from "next";
import "./globals.css";
import Providers from "./providers";
import PwaRegister from "@/components/PwaRegister";

export const metadata: Metadata = {
  title: "FFAI · Your fantasy football workspace",
  description:
    "Bring your fantasy roster, research, and next decision together. Game plans, player comparisons, and draft tools for your league.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "FFAI", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  themeColor: "#195638",
};

const themeScript = `try{var t=localStorage.getItem('theme');if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme: dark)').matches))document.documentElement.classList.add('dark')}catch(e){}`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <Providers>{children}</Providers>
        <PwaRegister />
      </body>
    </html>
  );
}
