import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import Link from "next/link";
import ReturnButton from "@/components/ReturnButton";

export default async function RentalDetails({
  params,
}: {
  params: { id: string };
}) {
  const session = await getServerSession(authOptions);

  if (!session) {
    redirect("/auth/signin");
  }

  const rental = await prisma.rental.findUnique({
    where: { id: params.id },
    include: {
      user: true,
      vehicle: true,
      pickupInspection: {
        include: {
          photos: true,
        },
      },
      returnInspection: {
        include: {
          photos: true,
        },
      },
      contract: true,
    },
  });

  if (!rental) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-bold text-gray-800 mb-2">
            Vermietung nicht gefunden
          </h2>
          <Link href="/admin" className="text-indigo-600 hover:text-indigo-700">
            Zurück zum Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const inspectionLink = `${process.env.NEXTAUTH_URL}/inspection/${rental.accessToken}`;

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <h1 className="text-xl font-bold text-gray-800">
              Vermietungsdetails
            </h1>
            <Link
              href="/admin"
              className="text-sm text-indigo-600 hover:text-indigo-700"
            >
              Zurück zum Dashboard
            </Link>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              Kundeninformationen
            </h2>
            <div className="space-y-2">
              <p className="text-sm">
                <strong>Name:</strong> {rental.user.name}
              </p>
              <p className="text-sm">
                <strong>E-Mail:</strong> {rental.user.email}
              </p>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              Fahrzeuginformationen
            </h2>
            <div className="space-y-2">
              <p className="text-sm">
                <strong>Fahrzeug:</strong> {rental.vehicle.brand}{" "}
                {rental.vehicle.model}
              </p>
              <p className="text-sm">
                <strong>Kennzeichen:</strong> {rental.vehicle.licensePlate}
              </p>
              <p className="text-sm">
                <strong>Farbe:</strong> {rental.vehicle.color}
              </p>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              Mietinformationen
            </h2>
            <div className="space-y-2">
              <p className="text-sm">
                <strong>Status:</strong>{" "}
                <span
                  className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                    rental.status === "active"
                      ? "bg-green-100 text-green-800"
                      : rental.status === "completed"
                      ? "bg-blue-100 text-blue-800"
                      : "bg-yellow-100 text-yellow-800"
                  }`}
                >
                  {rental.status}
                </span>
              </p>
              <p className="text-sm">
                <strong>Startdatum:</strong>{" "}
                {new Date(rental.startDate).toLocaleDateString("de-DE")}
              </p>
              {rental.endDate && (
                <p className="text-sm">
                  <strong>Enddatum:</strong>{" "}
                  {new Date(rental.endDate).toLocaleDateString("de-DE")}
                </p>
              )}
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              Zugangslink
            </h2>
            <div className="bg-gray-50 rounded-lg p-3 mb-3">
              <p className="text-xs font-mono text-gray-700 break-all">
                {inspectionLink}
              </p>
            </div>
            <button
              onClick={() => {
                navigator.clipboard.writeText(inspectionLink);
                alert("Link kopiert!");
              }}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold py-2 px-4 rounded-lg transition-colors"
            >
              Link kopieren
            </button>
          </div>
        </div>

        <div className="mt-6 space-y-6">
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              Abholung (Pickup)
            </h2>
            {rental.pickupInspection ? (
              <div>
                <p className="text-sm mb-2">
                  <strong>Status:</strong>{" "}
                  <span
                    className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                      rental.pickupInspection.status === "completed"
                        ? "bg-green-100 text-green-800"
                        : "bg-yellow-100 text-yellow-800"
                    }`}
                  >
                    {rental.pickupInspection.status}
                  </span>
                </p>
                {rental.pickupInspection.kmStand && (
                  <p className="text-sm mb-2">
                    <strong>KM-Stand:</strong>{" "}
                    {rental.pickupInspection.kmStand.toLocaleString()} km
                  </p>
                )}
                {rental.pickupInspection.completedAt && (
                  <p className="text-sm mb-4">
                    <strong>Abgeschlossen:</strong>{" "}
                    {new Date(
                      rental.pickupInspection.completedAt
                    ).toLocaleString("de-DE")}
                  </p>
                )}
                {rental.pickupInspection.photos.length > 0 && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-4">
                    {rental.pickupInspection.photos.map((photo) => (
                      <div key={photo.id} className="relative">
                        <img
                          src={photo.imageUrl}
                          alt={photo.position}
                          className="w-full h-24 object-cover rounded-lg"
                        />
                        <span className="absolute bottom-1 left-1 bg-black bg-opacity-60 text-white text-xs px-2 py-1 rounded">
                          {photo.position}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500">Noch keine Inspektion</p>
            )}
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              Rückgabe (Return)
            </h2>
            {rental.returnInspection ? (
              <div>
                <p className="text-sm mb-2">
                  <strong>Status:</strong>{" "}
                  <span
                    className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                      rental.returnInspection.status === "completed"
                        ? "bg-green-100 text-green-800"
                        : "bg-yellow-100 text-yellow-800"
                    }`}
                  >
                    {rental.returnInspection.status}
                  </span>
                </p>
                {rental.returnInspection.kmStand && (
                  <p className="text-sm mb-2">
                    <strong>KM-Stand:</strong>{" "}
                    {rental.returnInspection.kmStand.toLocaleString()} km
                  </p>
                )}
                {rental.returnInspection.completedAt && (
                  <p className="text-sm mb-4">
                    <strong>Abgeschlossen:</strong>{" "}
                    {new Date(
                      rental.returnInspection.completedAt
                    ).toLocaleString("de-DE")}
                  </p>
                )}
                {rental.returnInspection.photos.length > 0 && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-4">
                    {rental.returnInspection.photos.map((photo) => (
                      <div key={photo.id} className="relative">
                        <img
                          src={photo.imageUrl}
                          alt={photo.position}
                          className="w-full h-24 object-cover rounded-lg"
                        />
                        <span className="absolute bottom-1 left-1 bg-black bg-opacity-60 text-white text-xs px-2 py-1 rounded">
                          {photo.position}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : rental.status === "active" ? (
              <div>
                <p className="text-sm text-gray-500 mb-4">
                  Noch keine Rückgabe-Inspektion
                </p>
                <ReturnButton rentalId={rental.id} />
              </div>
            ) : (
              <p className="text-sm text-gray-500">
                Rückgabe noch nicht initiiert
              </p>
            )}
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              Vertrag
            </h2>
            {rental.contract ? (
              <div>
                <p className="text-sm mb-2">
                  <strong>Vertragsnummer:</strong> {rental.contract.id}
                </p>
                {rental.contract.signedAt && (
                  <p className="text-sm">
                    <strong>Unterzeichnet:</strong>{" "}
                    {new Date(rental.contract.signedAt).toLocaleString("de-DE")}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500">Noch kein Vertrag</p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
