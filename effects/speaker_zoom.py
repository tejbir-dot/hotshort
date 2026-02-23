def build_zoom_filter(
    energy_curve,
    max_zoom=1.08
):
    if not energy_curve:
        return ""

    avg = sum(energy_curve) / len(energy_curve)
    z = min(max_zoom, 1.0 + avg * 0.08)

    return f"zoompan=z='{z}':d=1"
