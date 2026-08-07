import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fahrzeugverleih - Inspektion",
  description: "Digitale Fahrzeuginspektion für Mietfahrzeuge",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="de">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
