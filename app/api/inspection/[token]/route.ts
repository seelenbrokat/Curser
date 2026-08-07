import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ token: string }> }
) {
  try {
    const { token } = await params;

    const rental = await prisma.rental.findUnique({
      where: { accessToken: token },
      include: {
        vehicle: true,
        pickupInspection: true,
        returnInspection: true,
      },
    });

    if (!rental) {
      return NextResponse.json(
        { error: "Ungültiger Zugangslink" },
        { status: 404 }
      );
    }

    const inspection = rental.pickupInspection?.status === "pending" 
      ? rental.pickupInspection 
      : rental.returnInspection?.status === "pending"
      ? rental.returnInspection
      : null;

    if (!inspection) {
      return NextResponse.json(
        { error: "Keine offene Inspektion gefunden" },
        { status: 404 }
      );
    }

    return NextResponse.json({
      rentalId: rental.id,
      inspectionId: inspection.id,
      type: inspection.type,
      vehicle: {
        brand: rental.vehicle.brand,
        model: rental.vehicle.model,
        licensePlate: rental.vehicle.licensePlate,
        color: rental.vehicle.color,
        year: rental.vehicle.year,
      },
    });
  } catch (error) {
    console.error("Error fetching inspection:", error);
    return NextResponse.json(
      { error: "Fehler beim Laden der Inspektion" },
      { status: 500 }
    );
  }
}
