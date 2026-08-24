"""Bilingual message catalogue for the WhatsApp advisory bot.

Every farmer-facing string exists in English (``en``) and Kannada (``kn``).
Templates use ``str.format`` placeholders; :func:`t` renders one and falls back
to English if a key is somehow missing from the Kannada table, rather than
returning an empty message.

Kannada input is accepted as well as produced: :data:`CROP_INPUT_ALIASES` and
:data:`DISTRICT_INPUT_ALIASES` let a farmer reply "ಟೊಮಾಟೊ" or "ಕೋಲಾರ".
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

LANGUAGES = ("en", "kn")
DEFAULT_LANGUAGE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "welcome": {
        "en": (
            "🌱 Welcome to NEYOGI — crop and market advisory for Karnataka's "
            "vegetable belt.\n\n"
            "To register, reply with your *district* name."
        ),
        "kn": (
            "🌱 ನೇಯೋಗಿಗೆ ಸುಸ್ವಾಗತ — ಕರ್ನಾಟಕದ ತರಕಾರಿ ಬೆಳೆಗಾರರಿಗಾಗಿ ಬೆಳೆ ಮತ್ತು "
            "ಮಾರುಕಟ್ಟೆ ಸಲಹೆ.\n\n"
            "ನೋಂದಣಿಗಾಗಿ ನಿಮ್ಮ *ಜಿಲ್ಲೆಯ* ಹೆಸರನ್ನು ಕಳುಹಿಸಿ."
        ),
    },
    "ask_district": {
        "en": "Which district are you farming in? Supported: {districts}",
        "kn": "ನೀವು ಯಾವ ಜಿಲ್ಲೆಯಲ್ಲಿ ಕೃಷಿ ಮಾಡುತ್ತಿದ್ದೀರಿ? ಲಭ್ಯವಿರುವ ಜಿಲ್ಲೆಗಳು: {districts}",
    },
    "district_not_recognised": {
        "en": (
            "I could not match “{value}” to a district NEYOGI covers.\n"
            "Supported districts: {districts}"
        ),
        "kn": (
            "“{value}” ಜಿಲ್ಲೆ ಸಿಗಲಿಲ್ಲ.\n"
            "ಲಭ್ಯವಿರುವ ಜಿಲ್ಲೆಗಳು: {districts}"
        ),
    },
    "ask_crops": {
        "en": (
            "Got it — {district}.\n\n"
            "Which crops do you grow? Reply with one or more, separated by "
            "commas: Tomato, Onion, Potato, Leafy Greens."
        ),
        "kn": (
            "ಸರಿ — {district}.\n\n"
            "ನೀವು ಯಾವ ಬೆಳೆಗಳನ್ನು ಬೆಳೆಯುತ್ತೀರಿ? ಅಲ್ಪವಿರಾಮದಿಂದ ಬೇರ್ಪಡಿಸಿ ಒಂದು ಅಥವಾ "
            "ಹೆಚ್ಚಿನವನ್ನು ಕಳುಹಿಸಿ: ಟೊಮಾಟೊ, ಈರುಳ್ಳಿ, ಆಲೂಗಡ್ಡೆ, ಸೊಪ್ಪು."
        ),
    },
    "crops_not_recognised": {
        "en": (
            "I could not match “{value}” to a crop NEYOGI tracks.\n"
            "Supported crops: Tomato, Onion, Potato, Leafy Greens."
        ),
        "kn": (
            "“{value}” ಬೆಳೆ ಸಿಗಲಿಲ್ಲ.\n"
            "ಲಭ್ಯವಿರುವ ಬೆಳೆಗಳು: ಟೊಮಾಟೊ, ಈರುಳ್ಳಿ, ಆಲೂಗಡ್ಡೆ, ಸೊಪ್ಪು."
        ),
    },
    "registered": {
        "en": (
            "✅ Registered.\n"
            "District: {district}\n"
            "Crops: {crops}\n\n"
            "You will get a weekly briefing. Send *PRICE* for today's mandi "
            "rates, *SUPPLY* for the supply outlook, *KANNADA* to switch "
            "language, or *STOP* to unsubscribe."
        ),
        "kn": (
            "✅ ನೋಂದಣಿ ಪೂರ್ಣಗೊಂಡಿದೆ.\n"
            "ಜಿಲ್ಲೆ: {district}\n"
            "ಬೆಳೆಗಳು: {crops}\n\n"
            "ನಿಮಗೆ ವಾರಕ್ಕೊಮ್ಮೆ ಮಾಹಿತಿ ಬರುತ್ತದೆ. ಇಂದಿನ ಮಾರುಕಟ್ಟೆ ದರಕ್ಕಾಗಿ *PRICE*, "
            "ಪೂರೈಕೆ ಮುನ್ಸೂಚನೆಗಾಗಿ *SUPPLY*, ಇಂಗ್ಲಿಷ್‌ಗೆ *ENGLISH*, ಚಂದಾ ರದ್ದುಗೊಳಿಸಲು "
            "*STOP* ಎಂದು ಕಳುಹಿಸಿ."
        ),
    },
    "help": {
        "en": (
            "NEYOGI commands:\n"
            "*PRICE* — latest mandi rates for your crops\n"
            "*SUPPLY* — projected supply vs mandi arrivals\n"
            "*KANNADA* / *ENGLISH* — change language\n"
            "*STOP* — unsubscribe, *START* — rejoin"
        ),
        "kn": (
            "ನೇಯೋಗಿ ಆದೇಶಗಳು:\n"
            "*PRICE* — ನಿಮ್ಮ ಬೆಳೆಗಳ ಇತ್ತೀಚಿನ ಮಾರುಕಟ್ಟೆ ದರ\n"
            "*SUPPLY* — ಅಂದಾಜು ಪೂರೈಕೆ ಮತ್ತು ಮಾರುಕಟ್ಟೆ ಆವಕ\n"
            "*ENGLISH* — ಇಂಗ್ಲಿಷ್‌ಗೆ ಬದಲಿಸಿ\n"
            "*STOP* — ಚಂದಾ ರದ್ದು, *START* — ಮತ್ತೆ ಸೇರಿ"
        ),
    },
    "language_set": {
        "en": "Language set to English.",
        "kn": "ಭಾಷೆ ಕನ್ನಡಕ್ಕೆ ಬದಲಾಯಿಸಲಾಗಿದೆ.",
    },
    "price_header": {
        "en": "📊 Mandi rates — {district}, {date}",
        "kn": "📊 ಮಾರುಕಟ್ಟೆ ದರ — {district}, {date}",
    },
    "price_line": {
        "en": "{crop} · {market}: ₹{modal}/quintal (₹{low}–₹{high})",
        "kn": "{crop} · {market}: ₹{modal}/ಕ್ವಿಂಟಾಲ್ (₹{low}–₹{high})",
    },
    "price_cached_notice": {
        "en": (
            "⚠️ These are cached rates from {date}. The live AGMARKNET feed "
            "was unreachable."
        ),
        "kn": (
            "⚠️ ಇವು {date} ರಂದಿನ ಸಂಗ್ರಹಿತ ದರಗಳು. ನೇರ AGMARKNET ಸಂಪರ್ಕ ಲಭ್ಯವಿರಲಿಲ್ಲ."
        ),
    },
    "price_unavailable": {
        "en": "No mandi price data is available for {crops} in {district} right now.",
        "kn": "{district} ಜಿಲ್ಲೆಯಲ್ಲಿ {crops} ಬೆಳೆಗೆ ಸದ್ಯಕ್ಕೆ ಮಾರುಕಟ್ಟೆ ದರ ಮಾಹಿತಿ ಲಭ್ಯವಿಲ್ಲ.",
    },
    "supply_header": {
        "en": "🌾 Supply outlook — {district}, {date}",
        "kn": "🌾 ಪೂರೈಕೆ ಮುನ್ಸೂಚನೆ — {district}, {date}",
    },
    "supply_line": {
        "en": "{crop}: {area} ha classified, ~{volume} MT projected against {arrivals} MT arrivals ({ratio}×)",
        "kn": "{crop}: {area} ಹೆಕ್ಟೇರ್, ಅಂದಾಜು {volume} ಟನ್, ಮಾರುಕಟ್ಟೆ ಆವಕ {arrivals} ಟನ್ ({ratio} ಪಟ್ಟು)",
    },
    "supply_oversupply_warning": {
        "en": (
            "⚠️ {crop}: projected supply is {ratio}× recent mandi arrivals. "
            "Consider staggering harvest or checking alternative markets."
        ),
        "kn": (
            "⚠️ {crop}: ಅಂದಾಜು ಪೂರೈಕೆ ಇತ್ತೀಚಿನ ಮಾರುಕಟ್ಟೆ ಆವಕದ {ratio} ಪಟ್ಟು ಇದೆ. "
            "ಕೊಯ್ಲನ್ನು ಹಂತಹಂತವಾಗಿ ಮಾಡಿ ಅಥವಾ ಬೇರೆ ಮಾರುಕಟ್ಟೆಯನ್ನು ಪರಿಶೀಲಿಸಿ."
        ),
    },
    "supply_withheld": {
        "en": "{crop}: {area} ha classified. Projected tonnage unavailable — {reason}",
        "kn": "{crop}: {area} ಹೆಕ್ಟೇರ್. ಅಂದಾಜು ಇಳುವರಿ ಲಭ್ಯವಿಲ್ಲ — {reason}",
    },
    "district_unvalidated": {
        "en": (
            "ℹ️ {district} has no field-verified parcels yet, so NEYOGI does not "
            "publish crop-area or supply estimates for it. Mandi prices are "
            "still available."
        ),
        "kn": (
            "ℹ️ {district} ಜಿಲ್ಲೆಯಲ್ಲಿ ಇನ್ನೂ ಕ್ಷೇತ್ರ-ಪರಿಶೀಲಿತ ತಾಕುಗಳಿಲ್ಲ, ಆದ್ದರಿಂದ "
            "ಬೆಳೆ ವಿಸ್ತೀರ್ಣ ಅಥವಾ ಪೂರೈಕೆ ಅಂದಾಜು ನೀಡಲಾಗುವುದಿಲ್ಲ. ಮಾರುಕಟ್ಟೆ ದರಗಳು "
            "ಲಭ್ಯವಿವೆ."
        ),
    },
    "weekly_briefing_header": {
        "en": "🌱 NEYOGI weekly briefing — {district}, {date}",
        "kn": "🌱 ನೇಯೋಗಿ ವಾರದ ಮಾಹಿತಿ — {district}, {date}",
    },
    "not_registered": {
        "en": "You are not registered yet. Reply with your district name to start.",
        "kn": "ನೀವು ಇನ್ನೂ ನೋಂದಾಯಿಸಿಲ್ಲ. ಪ್ರಾರಂಭಿಸಲು ನಿಮ್ಮ ಜಿಲ್ಲೆಯ ಹೆಸರನ್ನು ಕಳುಹಿಸಿ.",
    },
    "unsubscribed": {
        "en": "You have been unsubscribed from NEYOGI alerts. Send START to rejoin.",
        "kn": "ನೇಯೋಗಿ ಸಂದೇಶಗಳಿಂದ ನಿಮ್ಮ ಚಂದಾ ರದ್ದಾಗಿದೆ. ಮತ್ತೆ ಸೇರಲು START ಕಳುಹಿಸಿ.",
    },
    "resubscribed": {
        "en": "Welcome back — you will receive NEYOGI briefings again.",
        "kn": "ಮತ್ತೆ ಸ್ವಾಗತ — ನಿಮಗೆ ನೇಯೋಗಿ ಮಾಹಿತಿ ಮತ್ತೆ ಬರುತ್ತದೆ.",
    },
    "service_degraded": {
        "en": "⚠️ Some NEYOGI data sources are unavailable right now, so this reply may be incomplete.",
        "kn": "⚠️ ಸದ್ಯಕ್ಕೆ ಕೆಲವು ನೇಯೋಗಿ ಮಾಹಿತಿ ಮೂಲಗಳು ಲಭ್ಯವಿಲ್ಲ, ಆದ್ದರಿಂದ ಈ ಉತ್ತರ ಅಪೂರ್ಣವಾಗಿರಬಹುದು.",
    },
}

#: Crop names as a farmer might type them, in either script.
CROP_INPUT_ALIASES: dict[str, str] = {
    "tomato": "Tomato",
    "tomatoes": "Tomato",
    "tamatar": "Tomato",
    "ಟೊಮಾಟೊ": "Tomato",
    "ಟೊಮೇಟೊ": "Tomato",
    "onion": "Onion",
    "onions": "Onion",
    "eerulli": "Onion",
    "ಈರುಳ್ಳಿ": "Onion",
    "potato": "Potato",
    "potatoes": "Potato",
    "aloo": "Potato",
    "alugadde": "Potato",
    "ಆಲೂಗಡ್ಡೆ": "Potato",
    "leafy greens": "Leafy Greens",
    "leafy": "Leafy Greens",
    "greens": "Leafy Greens",
    "spinach": "Leafy Greens",
    "palak": "Leafy Greens",
    "soppu": "Leafy Greens",
    "ಸೊಪ್ಪು": "Leafy Greens",
    "ಪಾಲಕ್": "Leafy Greens",
}

#: District names in Kannada script, mapped to the English spelling used
#: throughout the system. GAUL resolution happens separately, server-side.
DISTRICT_INPUT_ALIASES: dict[str, str] = {
    "ಕೋಲಾರ": "Kolar",
    "ಚಿಕ್ಕಬಳ್ಳಾಪುರ": "Chikkaballapur",
    "ಬೆಂಗಳೂರು ಗ್ರಾಮಾಂತರ": "Bengaluru Rural",
    "ಬೆಂಗಳೂರು ಗ್ರಾಮೀಣ": "Bengaluru Rural",
    "ರಾಮನಗರ": "Ramanagara",
    "ತುಮಕೂರು": "Tumakuru",
    "ಹಾಸನ": "Hassan",
    "ಮಂಡ್ಯ": "Mandya",
    "ಚಿಕ್ಕಮಗಳೂರು": "Chikkamagaluru",
}

#: Crop names rendered back to the farmer in their language.
CROP_DISPLAY: dict[str, dict[str, str]] = {
    "Tomato": {"en": "Tomato", "kn": "ಟೊಮಾಟೊ"},
    "Onion": {"en": "Onion", "kn": "ಈರುಳ್ಳಿ"},
    "Potato": {"en": "Potato", "kn": "ಆಲೂಗಡ್ಡೆ"},
    "Leafy Greens": {"en": "Leafy Greens", "kn": "ಸೊಪ್ಪು"},
    "Fallow/Non-Crop": {"en": "Fallow", "kn": "ಪಾಳು"},
}

DISTRICT_DISPLAY: dict[str, str] = {v: k for k, v in DISTRICT_INPUT_ALIASES.items()}


def normalise_language(value: str | None) -> str:
    if not value:
        return DEFAULT_LANGUAGE
    lowered = str(value).strip().lower()
    return lowered if lowered in LANGUAGES else DEFAULT_LANGUAGE


def t(key: str, language: str = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    """Render a catalogue string.

    Falls back to English when a key has no entry for the requested language,
    and returns the raw template if a placeholder is missing rather than
    raising mid-conversation.
    """
    entry = MESSAGES.get(key)
    if entry is None:
        logger.error("Missing i18n key %r", key)
        return ""
    language = normalise_language(language)
    template = entry.get(language) or entry.get(DEFAULT_LANGUAGE, "")
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError) as exc:
        logger.error("i18n key %r missing placeholder: %s", key, exc)
        return template


def crop_name(crop: str, language: str = DEFAULT_LANGUAGE) -> str:
    return CROP_DISPLAY.get(crop, {}).get(normalise_language(language), crop)


def district_name(district: str, language: str = DEFAULT_LANGUAGE) -> str:
    if normalise_language(language) == "kn":
        return DISTRICT_DISPLAY.get(district, district)
    return district


def parse_crops(text: str) -> tuple[list[str], list[str]]:
    """Split a free-text reply into recognised crops and unrecognised tokens."""
    recognised: list[str] = []
    unknown: list[str] = []
    for token in str(text).replace("\n", ",").split(","):
        cleaned = " ".join(token.strip().lower().split())
        if not cleaned:
            continue
        crop = CROP_INPUT_ALIASES.get(cleaned)
        if crop:
            if crop not in recognised:
                recognised.append(crop)
        else:
            unknown.append(token.strip())
    return recognised, unknown


def parse_district(text: str, supported: list[str]) -> str | None:
    """Match a free-text reply to a supported district, in either script."""
    cleaned = " ".join(str(text).strip().split())
    if cleaned in DISTRICT_INPUT_ALIASES:
        candidate = DISTRICT_INPUT_ALIASES[cleaned]
        return candidate if candidate in supported else None

    lowered = cleaned.lower()
    for district in supported:
        if district.lower() == lowered:
            return district
    # Accept an unambiguous prefix ("Chikkaballa" -> "Chikkaballapur"), but
    # never a guess between two candidates.
    matches = [d for d in supported if d.lower().startswith(lowered)] if lowered else []
    return matches[0] if len(matches) == 1 else None
