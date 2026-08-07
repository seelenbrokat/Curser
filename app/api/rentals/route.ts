import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import bcrypt from "bcryptjs";
import { nanoid } from "nanoid";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { customerEmail, customerName, vehicleId, startDate } = body;

    let user = await prisma.user.findUnique({
      where: { email: customerEmail },
    });

    if (!user) {
      const tempPassword = nanoid(16);
      const hashedPassword = await bcrypt.hash(tempPassword, 10);
      
      user = await prisma.user.create({
        data: {
          email: customerEmail,
          name: customerName,
          password: hashedPassword,
          role: "customer",
        },
      });
    }

    const accessToken = nanoid(32);

    const rental = await prisma.rental.create({
      data: {
        userId: user.id,
        vehicleId,
        accessToken,
        startDate: new Date(startDate),
        status: "pending",
      },
      include: {
        vehicle: true,
        user: true,
      },
    });

    await prisma.inspection.create({
      data: {
        rentalPickupId: rental.id,
        type: "pickup",
        status: "pending",
      },
    });

    return NextResponse.json(rental);
  } catch (error) {
    console.error("Error creating rental:", error);
    return NextResponse.json(
      { error: "Fehler beim Erstellen der Vermietung" },
      { status: 500 }
    );
  }
}
