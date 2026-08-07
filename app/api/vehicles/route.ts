import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const vehicles = await prisma.vehicle.findMany({
      orderBy: { createdAt: "desc" },
    });
    return NextResponse.json(vehicles);
  } catch (error) {
    return NextResponse.json(
      { error: "Fehler beim Laden der Fahrzeuge" },
      { status: 500 }
    );
  }
}
