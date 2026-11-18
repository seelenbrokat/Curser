from __future__ import annotations

# PostPac Priority/Economy: max. 30 kg pro Packstück
POST_MAX_WEIGHT_GRAMS = 30_000


def piece_weight_grams(total_grams: int, piece_count: int = 1) -> int:
    n = max(1, int(piece_count or 1))
    total = max(0, int(total_grams or 0))
    if n > 1:
        return max(1, total // n) if total else 0
    return total


def weight_warning(total_grams: int, piece_count: int = 1) -> str | None:
    """Warnung wenn Packstückgewicht über dem Post-Maximum liegt."""
    pw = piece_weight_grams(total_grams, piece_count)
    if pw <= POST_MAX_WEIGHT_GRAMS:
        return None
    kg = pw / 1000
    max_kg = POST_MAX_WEIGHT_GRAMS / 1000
    pieces = max(1, int(piece_count or 1))
    if pieces > 1:
        return (
            f"Gewicht {kg:.1f} kg pro Packstück überschreitet das Post-Maximum "
            f"({max_kg:.0f} kg). Bitte aufteilen oder reduzieren."
        )
    return (
        f"Gewicht {kg:.1f} kg überschreitet das Post-Maximum ({max_kg:.0f} kg). "
        f"Bitte aufteilen oder reduzieren."
    )
