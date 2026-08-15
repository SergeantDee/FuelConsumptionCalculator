from __future__ import annotations


def legacy_pilot_info(location: str) -> tuple[float, float, float]:
    normalized = location.lower()
    if "antwerp" in normalized:
        return (72.0, 13.0, 6.0)
    if "tangier" in normalized:
        return (3.0, 1.75, 1.75)
    if "santos" in normalized:
        return (4.8, 2.46, 2.46)
    if "paranagua" in normalized:
        return (17.3, 2.3, 2.3)
    if "montevideo" in normalized:
        return (24.5, 2.0, 2.0)
    if "buenos" in normalized:
        return (130.5, 11.5, 11.5)
    if "itapoa" in normalized:
        return (20.0, 1.0, 1.0)
    if "southampton" in normalized:
        return (28.0, 1.0, 1.0)
    if "rotterdam" in normalized:
        return (9.7, 2.5, 2.5)
    if "hamburg" in normalized:
        return (76.4, 7.5, 7.5)
    if "bremerhaven" in normalized:
        return (45.0, 3.25, 3.25)
    return (0.0, 1.0, 1.0)


def legacy_sea_distance(origin_port: str, destination_port: str, next_port: str = "") -> float | None:
    left = origin_port.lower()
    current = destination_port.lower()
    next_location = next_port.lower()
    if "antwerp" in left and "eca out" in current:
        return 336.0
    if "eca out" in left and "eca in" in current:
        return 961.1
    if "eca in" in left and "tangier" in current:
        return 23.0
    if "tangier" in left and "eca out" in current:
        return 23.0 if ("santos" in next_location or "paranagua" in next_location) else 25.6
    if "eca out" in left and "santos" in current:
        return 4436.2
    if "santos" in left and "paranagua" in current:
        return 153.5
    if "paranagua" in left and "montevideo" in current:
        return 756.7
    if "montevideo" in left and "buenos" in current:
        return 2.3
    if "buenos" in left and "itapoa" in current:
        return 700.0
    if "itapoa" in left and "paranagua" in current:
        return 45.0
    if "paranagua" in left and "santos" in current:
        return 149.0
    if "santos" in left and "eca in" in current:
        return 4418.0
    if "eca in" in left and "southampton" in current:
        return 197.9
    if "southampton" in left and "rotterdam" in current:
        return 234.0
    if "rotterdam" in left and "hamburg" in current:
        return 230.0
    if "hamburg" in left and "bremerhaven" in current:
        return 30.0
    if "bremerhaven" in left and "antwerp" in current:
        return 281.0
    return None
