import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { writeFile, mkdir } from "fs/promises";
import { join } from "path";

export async function POST(request: Request) {
  try {
    const formData = await request.formData();
    const token = formData.get("token") as string;
    const inspectionId = formData.get("inspectionId") as string;
    const kmStand = formData.get("kmStand") as string;

    if (!token || !inspectionId || !kmStand) {
      return NextResponse.json(
        { error: "Fehlende Daten" },
        { status: 400 }
      );
    }

    const uploadDir = join(process.cwd(), "public", "uploads", inspectionId);
    await mkdir(uploadDir, { recursive: true });

    const photoUrls: Record<string, string> = {};
    let kmStandUrl = "";

    for (const [key, value] of formData.entries()) {
      if (key.startsWith("photo-")) {
        const file = value as File;
        const bytes = await file.arrayBuffer();
        const buffer = Buffer.from(bytes);
        
        const filename = `${key}-${Date.now()}.jpg`;
        const filepath = join(uploadDir, filename);
        await writeFile(filepath, buffer);
        
        const publicUrl = `/uploads/${inspectionId}/${filename}`;
        
        if (key === "photo-kmstand") {
          kmStandUrl = publicUrl;
        } else {
          const position = key.replace("photo-", "");
          photoUrls[position] = publicUrl;
        }
      }
    }

    await prisma.inspection.update({
      where: { id: inspectionId },
      data: {
        status: "completed",
        kmStand: parseInt(kmStand),
        kmStandImageUrl: kmStandUrl,
        completedAt: new Date(),
      },
    });

    for (const [position, url] of Object.entries(photoUrls)) {
      await prisma.inspectionPhoto.create({
        data: {
          inspectionId,
          position,
          imageUrl: url,
          isValid: true,
          analysisResult: "approved",
        },
      });
    }

    const inspection = await prisma.inspection.findUnique({
      where: { id: inspectionId },
      include: {
        rentalPickup: true,
        rentalReturn: true,
      },
    });

    const rental = inspection?.rentalPickup || inspection?.rentalReturn;
    
    if (rental && inspection?.type === "pickup") {
      await prisma.rental.update({
        where: { id: rental.id },
        data: { status: "active" },
      });
    } else if (rental && inspection?.type === "return") {
      await prisma.rental.update({
        where: { id: rental.id },
        data: { 
          status: "completed",
          endDate: new Date(),
        },
      });
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Error submitting inspection:", error);
    return NextResponse.json(
      { error: "Fehler beim Speichern der Inspektion" },
      { status: 500 }
    );
  }
}
