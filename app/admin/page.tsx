import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import Link from "next/link";

export default async function AdminDashboard() {
  const session = await getServerSession(authOptions);

  if (!session) {
    redirect("/auth/signin");
  }

  const vehicles = await prisma.vehicle.findMany({
    orderBy: { createdAt: "desc" },
  });

  const rentals = await prisma.rental.findMany({
    include: {
      user: true,
      vehicle: true,
    },
    orderBy: { createdAt: "desc" },
  });

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <h1 className="text-xl font-bold text-gray-800">
              Fahrzeugverleih - Admin
            </h1>
            <div className="flex items-center gap-4">
              <span className="text-sm text-gray-600">
                {session.user?.email}
              </span>
              <Link
                href="/api/auth/signout"
                className="text-sm text-red-600 hover:text-red-700"
              >
                Abmelden
              </Link>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold text-gray-800">
                Fahrzeuge
              </h2>
              <Link
                href="/admin/vehicles/new"
                className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                Neues Fahrzeug
              </Link>
            </div>
            <div className="space-y-3">
              {vehicles.length === 0 ? (
                <p className="text-gray-500 text-sm">
                  Keine Fahrzeuge vorhanden
                </p>
              ) : (
                vehicles.map((vehicle) => (
                  <div
                    key={vehicle.id}
                    className="border border-gray-200 rounded-lg p-4 hover:border-indigo-300 transition-colors"
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <h3 className="font-semibold text-gray-800">
                          {vehicle.brand} {vehicle.model}
                        </h3>
                        <p className="text-sm text-gray-600">
                          {vehicle.licensePlate} • {vehicle.color} • {vehicle.year}
                        </p>
                      </div>
                      <Link
                        href={`/admin/vehicles/${vehicle.id}`}
                        className="text-indigo-600 hover:text-indigo-700 text-sm"
                      >
                        Details
                      </Link>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold text-gray-800">
                Vermietungen
              </h2>
              <Link
                href="/admin/rentals/new"
                className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                Neue Vermietung
              </Link>
            </div>
            <div className="space-y-3">
              {rentals.length === 0 ? (
                <p className="text-gray-500 text-sm">
                  Keine Vermietungen vorhanden
                </p>
              ) : (
                rentals.map((rental) => (
                  <div
                    key={rental.id}
                    className="border border-gray-200 rounded-lg p-4 hover:border-green-300 transition-colors"
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <h3 className="font-semibold text-gray-800">
                          {rental.vehicle.brand} {rental.vehicle.model}
                        </h3>
                        <p className="text-sm text-gray-600">
                          Kunde: {rental.user.name || rental.user.email}
                        </p>
                        <p className="text-xs text-gray-500 mt-1">
                          Status: {rental.status}
                        </p>
                      </div>
                      <Link
                        href={`/admin/rentals/${rental.id}`}
                        className="text-green-600 hover:text-green-700 text-sm"
                      >
                        Details
                      </Link>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
