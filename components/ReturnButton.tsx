"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function ReturnButton({ rentalId }: { rentalId: string }) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleReturn = async () => {
    if (!confirm("Möchten Sie die Rückgabe initiieren?")) {
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`/api/rentals/${rentalId}/return`, {
        method: "POST",
      });

      if (!response.ok) {
        throw new Error("Fehler beim Initiieren der Rückgabe");
      }

      alert("Rückgabe-Inspektion wurde erstellt. Der Kunde kann nun den Link verwenden.");
      router.refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Ein Fehler ist aufgetreten");
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleReturn}
      disabled={loading}
      className="bg-orange-600 hover:bg-orange-700 text-white font-semibold py-2 px-4 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {loading ? "Wird erstellt..." : "Rückgabe initiieren"}
    </button>
  );
}
