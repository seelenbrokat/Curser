import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

async function main() {
  const hashedPassword = await bcrypt.hash("admin123", 10);
  
  const admin = await prisma.user.upsert({
    where: { email: "admin@example.com" },
    update: {},
    create: {
      email: "admin@example.com",
      name: "Admin",
      password: hashedPassword,
      role: "admin",
    },
  });

  console.log("Admin user created:", admin.email);

  const vehicle1 = await prisma.vehicle.upsert({
    where: { licensePlate: "B-XY-1234" },
    update: {},
    create: {
      licensePlate: "B-XY-1234",
      brand: "BMW",
      model: "3er",
      year: 2022,
      color: "Schwarz",
      description: "Limousine, Diesel, Automatik",
    },
  });

  const vehicle2 = await prisma.vehicle.upsert({
    where: { licensePlate: "M-AB-5678" },
    update: {},
    create: {
      licensePlate: "M-AB-5678",
      brand: "Mercedes",
      model: "C-Klasse",
      year: 2023,
      color: "Silber",
      description: "Kombi, Benzin, Automatik",
    },
  });

  console.log("Sample vehicles created:", vehicle1.licensePlate, vehicle2.licensePlate);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
