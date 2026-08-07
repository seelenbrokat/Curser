import Link from "next/link";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="max-w-md w-full bg-white rounded-2xl shadow-xl p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-800 mb-2">
            Fahrzeugverleih
          </h1>
          <p className="text-gray-600">
            Digitale Fahrzeuginspektion
          </p>
        </div>

        <div className="space-y-4">
          <Link
            href="/admin"
            className="block w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-3 px-6 rounded-lg text-center transition-colors"
          >
            Admin-Bereich
          </Link>
          
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-300"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-white text-gray-500">oder</span>
            </div>
          </div>

          <div className="text-center">
            <p className="text-sm text-gray-600 mb-3">
              Sie haben einen Zugangslink erhalten?
            </p>
            <p className="text-xs text-gray-500">
              Öffnen Sie den Link aus Ihrer E-Mail, um mit der Fahrzeuginspektion zu beginnen.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
