import { NextResponse } from "next/server";
import { analyzeVehicleImage, analyzeKmStandImage } from "@/lib/image-analysis";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { imageData, licensePlate, position, type } = body;

    if (!imageData) {
      return NextResponse.json(
        { error: "Kein Bild übermittelt" },
        { status: 400 }
      );
    }

    let result;
    
    if (type === "kmstand") {
      result = await analyzeKmStandImage(imageData);
    } else {
      result = await analyzeVehicleImage(imageData, licensePlate, position);
    }

    return NextResponse.json(result);
  } catch (error) {
    console.error("Error analyzing image:", error);
    return NextResponse.json(
      { error: "Fehler bei der Bildanalyse" },
      { status: 500 }
    );
  }
}
