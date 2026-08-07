"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import CameraCapture from "@/components/CameraCapture";

type Vehicle = {
  brand: string;
  model: string;
  licensePlate: string;
  color: string;
  year: number;
};

type Photo = {
  position: string;
  imageData: string;
  file: File;
  isAnalyzing: boolean;
  isValid: boolean;
  feedback: string;
};

type InspectionData = {
  rentalId: string;
  vehicle: Vehicle;
  inspectionId: string;
  type: "pickup" | "return";
};

const REQUIRED_POSITIONS = [
  { key: "front", label: "Vorderseite" },
  { key: "back", label: "Rückseite" },
  { key: "left", label: "Linke Seite" },
  { key: "right", label: "Rechte Seite" },
];

export default function InspectionPage() {
  const params = useParams();
  const router = useRouter();
  const token = params.token as string;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [inspectionData, setInspectionData] = useState<InspectionData | null>(null);
  const [photos, setPhotos] = useState<Record<string, Photo>>({});
  const [kmStandPhoto, setKmStandPhoto] = useState<Photo | null>(null);
  const [kmStand, setKmStand] = useState("");
  const [currentStep, setCurrentStep] = useState<"photos" | "kmstand" | "complete">("photos");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch(`/api/inspection/${token}`)
      .then((res) => {
        if (!res.ok) throw new Error("Ungültiger Zugangslink");
        return res.json();
      })
      .then((data) => {
        setInspectionData(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [token]);

  const handlePhotoCapture = async (position: string, imageData: string, file: File) => {
    setPhotos((prev) => ({
      ...prev,
      [position]: {
        position,
        imageData,
        file,
        isAnalyzing: true,
        isValid: false,
        feedback: "",
      },
    }));

    try {
      const response = await fetch("/api/analyze-image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          imageData,
          licensePlate: inspectionData?.vehicle.licensePlate,
          position,
          type: "vehicle",
        }),
      });

      const result = await response.json();

      setPhotos((prev) => ({
        ...prev,
        [position]: {
          ...prev[position],
          isAnalyzing: false,
          isValid: result.isValid,
          feedback: result.feedback,
        },
      }));
    } catch (err) {
      setPhotos((prev) => ({
        ...prev,
        [position]: {
          ...prev[position],
          isAnalyzing: false,
          isValid: false,
          feedback: "Fehler bei der Analyse. Bitte versuchen Sie es erneut.",
        },
      }));
    }
  };

  const handleKmStandCapture = async (imageData: string, file: File) => {
    setKmStandPhoto({
      position: "kmstand",
      imageData,
      file,
      isAnalyzing: true,
      isValid: false,
      feedback: "",
    });

    try {
      const response = await fetch("/api/analyze-image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          imageData,
          type: "kmstand",
        }),
      });

      const result = await response.json();

      setKmStandPhoto((prev) => prev ? {
        ...prev,
        isAnalyzing: false,
        isValid: result.isValid,
        feedback: result.feedback,
      } : null);
    } catch (err) {
      setKmStandPhoto((prev) => prev ? {
        ...prev,
        isAnalyzing: false,
        isValid: false,
        feedback: "Fehler bei der Analyse. Bitte versuchen Sie es erneut.",
      } : null);
    }
  };

  const canProceedToKmStand = () => {
    return REQUIRED_POSITIONS.every(
      (pos) => photos[pos.key]?.isValid
    );
  };

  const canSubmit = () => {
    return canProceedToKmStand() && 
           kmStandPhoto?.isValid && 
           kmStand.length > 0;
  };

  const handleSubmit = async () => {
    if (!canSubmit()) return;

    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("token", token);
      formData.append("inspectionId", inspectionData!.inspectionId);
      formData.append("kmStand", kmStand);

      REQUIRED_POSITIONS.forEach((pos) => {
        if (photos[pos.key]) {
          formData.append(`photo-${pos.key}`, photos[pos.key].file);
        }
      });

      if (kmStandPhoto) {
        formData.append("photo-kmstand", kmStandPhoto.file);
      }

      const response = await fetch("/api/inspection/submit", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) throw new Error("Fehler beim Absenden");

      setCurrentStep("complete");
    } catch (err) {
      alert("Fehler beim Absenden der Inspektion. Bitte versuchen Sie es erneut.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Lade Daten...</p>
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

  if (currentStep === "complete") {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-white rounded-lg shadow p-8 text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-gray-800 mb-2">
            Inspektion abgeschlossen!
          </h2>
          <p className="text-gray-600 mb-6">
            Ihre Fahrzeuginspektion wurde erfolgreich übermittelt. 
            {inspectionData?.type === "pickup" 
              ? " Sie können nun mit der Fahrt beginnen."
              : " Vielen Dank für die Rückgabe des Fahrzeugs."}
          </p>
          {inspectionData?.type === "pickup" && (
            <button
              onClick={() => router.push(`/contract/${token}`)}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-3 px-6 rounded-lg transition-colors"
            >
              Zum Mietvertrag
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <h1 className="text-2xl font-bold text-gray-800 mb-2">
            Fahrzeuginspektion
          </h1>
          <div className="text-sm text-gray-600">
            <p><strong>Fahrzeug:</strong> {inspectionData?.vehicle.brand} {inspectionData?.vehicle.model}</p>
            <p><strong>Kennzeichen:</strong> {inspectionData?.vehicle.licensePlate}</p>
            <p><strong>Farbe:</strong> {inspectionData?.vehicle.color}</p>
          </div>
        </div>

        {currentStep === "photos" && (
          <div className="space-y-6">
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-sm text-blue-800">
                <strong>Hinweis:</strong> Bitte fotografieren Sie das Fahrzeug von allen vier Seiten. 
                Die KI wird prüfen, ob die Fotos das richtige Fahrzeug zeigen und von ausreichender Qualität sind.
              </p>
            </div>

            {REQUIRED_POSITIONS.map((pos) => (
              <div key={pos.key} className="bg-white rounded-lg shadow p-6">
                <h3 className="text-lg font-semibold text-gray-800 mb-4">
                  {pos.label}
                </h3>
                
                {!photos[pos.key] ? (
                  <CameraCapture
                    position={pos.key}
                    onCapture={(imageData, file) => handlePhotoCapture(pos.key, imageData, file)}
                  />
                ) : (
                  <div>
                    <img
                      src={photos[pos.key].imageData}
                      alt={pos.label}
                      className="w-full rounded-lg mb-4"
                    />
                    
                    {photos[pos.key].isAnalyzing ? (
                      <div className="flex items-center justify-center py-4">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mr-3"></div>
                        <span className="text-gray-600">Analysiere Foto...</span>
                      </div>
                    ) : (
                      <div className={`p-4 rounded-lg mb-4 ${
                        photos[pos.key].isValid 
                          ? "bg-green-50 border border-green-200" 
                          : "bg-red-50 border border-red-200"
                      }`}>
                        <p className={`text-sm ${
                          photos[pos.key].isValid ? "text-green-800" : "text-red-800"
                        }`}>
                          {photos[pos.key].feedback}
                        </p>
                      </div>
                    )}

                    <button
                      onClick={() => setPhotos((prev) => {
                        const newPhotos = { ...prev };
                        delete newPhotos[pos.key];
                        return newPhotos;
                      })}
                      className="w-full bg-gray-200 hover:bg-gray-300 text-gray-800 font-semibold py-2 px-4 rounded-lg transition-colors"
                    >
                      Neues Foto aufnehmen
                    </button>
                  </div>
                )}
              </div>
            ))}

            <button
              onClick={() => setCurrentStep("kmstand")}
              disabled={!canProceedToKmStand()}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-4 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Weiter zum Kilometerstand
            </button>
          </div>
        )}

        {currentStep === "kmstand" && (
          <div className="space-y-6">
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-sm text-blue-800">
                <strong>Hinweis:</strong> Fotografieren Sie nun das Tachometer, sodass der Kilometerstand klar erkennbar ist.
              </p>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-lg font-semibold text-gray-800 mb-4">
                Kilometerstand
              </h3>

              {!kmStandPhoto ? (
                <CameraCapture
                  position="kmstand"
                  onCapture={handleKmStandCapture}
                />
              ) : (
                <div>
                  <img
                    src={kmStandPhoto.imageData}
                    alt="Kilometerstand"
                    className="w-full rounded-lg mb-4"
                  />

                  {kmStandPhoto.isAnalyzing ? (
                    <div className="flex items-center justify-center py-4">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mr-3"></div>
                      <span className="text-gray-600">Analysiere Foto...</span>
                    </div>
                  ) : (
                    <div className={`p-4 rounded-lg mb-4 ${
                      kmStandPhoto.isValid
                        ? "bg-green-50 border border-green-200"
                        : "bg-red-50 border border-red-200"
                    }`}>
                      <p className={`text-sm ${
                        kmStandPhoto.isValid ? "text-green-800" : "text-red-800"
                      }`}>
                        {kmStandPhoto.feedback}
                      </p>
                    </div>
                  )}

                  {kmStandPhoto.isValid && (
                    <div className="mb-4">
                      <label htmlFor="kmStand" className="block text-sm font-medium text-gray-700 mb-2">
                        Kilometerstand eingeben
                      </label>
                      <input
                        id="kmStand"
                        type="number"
                        value={kmStand}
                        onChange={(e) => setKmStand(e.target.value)}
                        placeholder="z.B. 45230"
                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                      />
                    </div>
                  )}

                  <button
                    onClick={() => setKmStandPhoto(null)}
                    className="w-full bg-gray-200 hover:bg-gray-300 text-gray-800 font-semibold py-2 px-4 rounded-lg transition-colors mb-4"
                  >
                    Neues Foto aufnehmen
                  </button>
                </div>
              )}
            </div>

            <div className="flex gap-4">
              <button
                onClick={() => setCurrentStep("photos")}
                className="flex-1 bg-gray-200 hover:bg-gray-300 text-gray-800 font-semibold py-4 px-6 rounded-lg transition-colors"
              >
                Zurück
              </button>
              <button
                onClick={handleSubmit}
                disabled={!canSubmit() || submitting}
                className="flex-1 bg-green-600 hover:bg-green-700 text-white font-semibold py-4 px-6 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? "Wird gesendet..." : "Inspektion abschließen"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
