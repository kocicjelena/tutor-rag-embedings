import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(req: NextRequest) {
  if (req.nextUrl.pathname.startsWith("/api/")) {
    const res = NextResponse.next();
    res.headers.set("Access-Control-Allow-Origin", "*");
    res.headers.set("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS");
    res.headers.set("Access-Control-Allow-Headers", "Content-Type,Authorization");
    return res;
  }
}

export const config = { matcher: "/api/:path*" };