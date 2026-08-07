import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { token } = body;

    const rental = await prisma.rental.findUnique({
      where: { accessToken: token },
      include: {
        contract: true,
      },
    });

    if (!rental) {
      return NextResponse.json(
        { error: "Ungültiger Zugangslink" },
        { status: 404 }
      );
    }

    let contract = rental.contract;

    if (!contract) {
      contract = await prisma.contract.create({
        data: {
          rentalId: rental.id,
        },
      });
    }

    if (!contract.signedAt) {
      contract = await prisma.contract.update({
        where: { id: contract.id },
        data: {
          signedAt: new Date(),
        },
      });
    }

    return NextResponse.json({ 
      success: true,
      contractId: contract.id,
    });
  } catch (error) {
    console.error("Error signing contract:", error);
    return NextResponse.json(
      { error: "Fehler beim Unterzeichnen des Vertrags" },
      { status: 500 }
    );
  }
}
