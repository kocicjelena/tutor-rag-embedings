import type { Metadata } from "next";
import { GlobalProvider } from "@/context/GlobalContext";
import "./globals.css";

export const metadata: Metadata = {
  title: "mcp-py — LLM / RAG / MCP showcase",
  description:
    "Document RAG over local SQLite vectors, answered by Ollama or Claude at your choice.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      {/*
        One provider, mounted once, above every page. `layout.tsx` stays a Server Component —
        GlobalProvider is the "use client" boundary, so pages that never touch the store are not
        dragged into the client bundle by it.
      */}
      <body>
        <GlobalProvider>{children}</GlobalProvider>
      </body>
    </html>
  );
}
