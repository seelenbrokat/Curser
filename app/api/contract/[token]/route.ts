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
        user: true,
        vehicle: true,
        pickupInspection: true,
        contract: true,
      },
    });

    if (!rental) {
      return NextResponse.json(
        { error: "Ungültiger Zugangslink" },
        { status: 404 }
      );
    }

    if (!rental.pickupInspection || rental.pickupInspection.status !== "completed") {
      return NextResponse.json(
        { error: "Inspektion noch nicht abgeschlossen" },
        { status: 400 }
      );
    }

    return NextResponse.json({
      rentalId: rental.id,
      customer: {
        name: rental.user.name,
        email: rental.user.email,
      },
      vehicle: {
        brand: rental.vehicle.brand,
        model: rental.vehicle.model,
        licensePlate: rental.vehicle.licensePlate,
        year: rental.vehicle.year,
        color: rental.vehicle.color,
      },
      startDate: rental.startDate,
      kmStand: rental.pickupInspection.kmStand,
      contractId: rental.contract?.id,
      alreadySigned: !!rental.contract?.signedAt,
    });
  } catch (error) {
    console.error("Error fetching contract:", error);
    return NextResponse.json(
      { error: "Fehler beim Laden des Vertrags" },
      { status: 500 }
    );
  }
}
