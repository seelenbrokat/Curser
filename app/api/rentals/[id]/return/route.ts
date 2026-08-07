import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const session = await getServerSession(authOptions);

    if (!session) {
      return NextResponse.json(
        { error: "Nicht autorisiert" },
        { status: 401 }
      );
    }

    const { id } = await params;

    const rental = await prisma.rental.findUnique({
      where: { id },
      include: {
        returnInspection: true,
      },
    });

    if (!rental) {
      return NextResponse.json(
        { error: "Vermietung nicht gefunden" },
        { status: 404 }
      );
    }

    if (rental.returnInspection) {
      return NextResponse.json(
        { error: "Rückgabe-Inspektion existiert bereits" },
        { status: 400 }
      );
    }

    await prisma.inspection.create({
      data: {
        rentalReturnId: rental.id,
        type: "return",
        status: "pending",
      },
    });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Error initiating return:", error);
    return NextResponse.json(
      { error: "Fehler beim Initiieren der Rückgabe" },
      { status: 500 }
    );
  }
}
