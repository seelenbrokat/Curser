"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

type ContractData = {
  rentalId: string;
  customer: {
    name: string;
    email: string;
  };
  vehicle: {
    brand: string;
    model: string;
    licensePlate: string;
    year: number;
    color: string;
  };
  startDate: string;
  kmStand: number;
  contractId?: string;
  alreadySigned: boolean;
};

export default function ContractPage() {
  const params = useParams();
  const token = params.token as string;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [contractData, setContractData] = useState<ContractData | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [signing, setSigning] = useState(false);

  useEffect(() => {
    fetch(`/api/contract/${token}`)
      .then((res) => {
        if (!res.ok) throw new Error("Ungültiger Zugangslink");
        return res.json();
      })
      .then((data) => {
        setContractData(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [token]);

  const handleSign = async () => {
    if (!agreed) {
      alert("Bitte akzeptieren Sie die Vertragsbedingungen");
      return;
    }

    setSigning(true);
    try {
      const response = await fetch("/api/contract/sign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });

      if (!response.ok) throw new Error("Fehler beim Signieren");

      const data = await response.json();
      setContractData({ ...contractData!, alreadySigned: true, contractId: data.contractId });
    } catch (err) {
      alert("Fehler beim Signieren des Vertrags. Bitte versuchen Sie es erneut.");
    } finally {
      setSigning(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Lade Vertrag...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-white rounded-lg shadow p-8 text-center">
          <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-800 mb-2">Fehler</h2>
          <p className="text-gray-600">{error}</p>
        </div>
      </div>
    );
  }

  if (contractData?.alreadySigned) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-white rounded-lg shadow p-8 text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-gray-800 mb-2">
            Vertrag unterzeichnet!
          </h2>
          <p className="text-gray-600 mb-6">
            Ihr Mietvertrag wurde erfolgreich unterzeichnet. Gute Fahrt!
          </p>
          <div className="bg-gray-50 rounded-lg p-4 text-left">
            <p className="text-sm text-gray-600">
              <strong>Vertragsnummer:</strong> {contractData.contractId}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-lg shadow p-8 mb-6">
          <h1 className="text-3xl font-bold text-gray-800 mb-6 text-center">
            Mietvertrag
          </h1>

          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-semibold text-gray-800 mb-3">
                Vertragsparteien
              </h2>
              <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                <p className="text-sm">
                  <strong>Mieter:</strong> {contractData?.customer.name}
                </p>
                <p className="text-sm">
                  <strong>E-Mail:</strong> {contractData?.customer.email}
                </p>
              </div>
            </div>

            <div>
              <h2 className="text-lg font-semibold text-gray-800 mb-3">
                Fahrzeugdetails
              </h2>
              <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                <p className="text-sm">
                  <strong>Fahrzeug:</strong> {contractData?.vehicle.brand} {contractData?.vehicle.model}
                </p>
                <p className="text-sm">
                  <strong>Kennzeichen:</strong> {contractData?.vehicle.licensePlate}
                </p>
                <p className="text-sm">
                  <strong>Farbe:</strong> {contractData?.vehicle.color}
                </p>
                <p className="text-sm">
                  <strong>Baujahr:</strong> {contractData?.vehicle.year}
                </p>
                <p className="text-sm">
                  <strong>Kilometerstand bei Übergabe:</strong> {contractData?.kmStand.toLocaleString()} km
                </p>
              </div>
            </div>

            <div>
              <h2 className="text-lg font-semibold text-gray-800 mb-3">
                Mietdauer
              </h2>
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-sm">
                  <strong>Mietbeginn:</strong>{" "}
                  {new Date(contractData?.startDate || "").toLocaleDateString("de-DE", {
                    day: "2-digit",
                    month: "2-digit",
                    year: "numeric",
                  })}
                </p>
              </div>
            </div>

            <div>
              <h2 className="text-lg font-semibold text-gray-800 mb-3">
                Vertragsbedingungen
              </h2>
              <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 space-y-3 max-h-64 overflow-y-auto">
                <p>
                  <strong>§ 1 Mietgegenstand</strong><br />
                  Der Vermieter überlässt dem Mieter das oben genannte Fahrzeug zur Nutzung.
                </p>
                <p>
                  <strong>§ 2 Zustand des Fahrzeugs</strong><br />
                  Der Mieter bestätigt, dass er das Fahrzeug in einwandfreiem Zustand übernommen hat.
                  Der Zustand wurde durch Fotos dokumentiert.
                </p>
                <p>
                  <strong>§ 3 Nutzung</strong><br />
                  Das Fahrzeug darf nur vom Mieter oder von im Vertrag genannten Personen genutzt werden.
                  Die Nutzung erfolgt auf eigene Verantwortung.
                </p>
                <p>
                  <strong>§ 4 Rückgabe</strong><br />
                  Das Fahrzeug ist im gleichen Zustand zurückzugeben. Bei Rückgabe erfolgt eine erneute
                  Inspektion mit Fotodokumentation.
                </p>
                <p>
                  <strong>§ 5 Haftung</strong><br />
                  Der Mieter haftet für alle Schäden am Fahrzeug, die während der Mietdauer entstehen.
                </p>
              </div>
            </div>

            <div className="border-t pt-6">
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agreed}
                  onChange={(e) => setAgreed(e.target.checked)}
                  className="mt-1 w-5 h-5 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
                />
                <span className="text-sm text-gray-700">
                  Ich habe die Vertragsbedingungen gelesen und akzeptiere diese. 
                  Ich bestätige, dass alle Angaben korrekt sind und das Fahrzeug im 
                  dokumentierten Zustand übernommen wurde.
                </span>
              </label>
            </div>

            <button
              onClick={handleSign}
              disabled={!agreed || signing}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-4 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {signing ? "Wird unterzeichnet..." : "Vertrag unterzeichnen"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
