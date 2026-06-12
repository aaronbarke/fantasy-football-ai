import type { Metadata, Viewport } from "next";
import "./globals.css";
import Providers from "./providers";
import PwaRegister from "@/components/PwaRegister";

export const metadata: Metadata = {
  title: "Fantasy Football AI",
  description:
    "An AI assistant that knows your fantasy league as well as you do — and never forgets to check the injury report.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "FFAI", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  themeColor: "#16a34a",
};

const themeScript = `try{var t=localStorage.getItem('theme');if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme: dark)').matches))document.documentElement.classList.add('dark')}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
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
