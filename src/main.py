from __future__ import annotations

import os
import re
import secrets
import unicodedata
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    import indian_pincode as india_pin
except ImportError:  # pragma: no cover - optional only if dependency missing
    india_pin = None

APP_NAME = "AddressGuard API"
APP_VERSION = "1.1.0"


def _env(name: str, default: str = "") -> str:
    """Read env var; works for local .env and Cloudflare Workers secrets/vars."""
    return (os.getenv(name) or default).strip()

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "Normalize address fields, run format/completeness checks, and for India "
        "cross-check PIN codes against official India Post state/district data. "
        "This service does not prove that an address exists or is deliverable."
    ),
    contact={"name": "AddressGuard API Support"},
    license_info={"name": "Proprietary"},
)


class AddressInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    address_line1: str = Field(min_length=1, max_length=200, description="Street address, building, or house number")
    address_line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country_code: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code, e.g. IN, US, GB")

    @field_validator("country_code")
    @classmethod
    def uppercase_country_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError("country_code must be a two-letter country code")
        return value

    @field_validator("address_line1", "city")
    @classmethod
    def nonblank_required_fields(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("address_line2", "state", "postal_code")
    @classmethod
    def clean_optional_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class BatchAddressInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    addresses: list[AddressInput] = Field(min_length=1, max_length=100)


class Issue(BaseModel):
    code: str
    field: str
    message: str
    severity: str = "warning"


class ValidationResponse(BaseModel):
    is_valid: bool
    verification_level: str
    normalized_address: dict
    issues: list[Issue]
    checks: dict[str, bool]
    note: str


# These are basic format checks, not authoritative postal-code validation.
POSTAL_PATTERNS = {
    "IN": re.compile(r"^[1-9][0-9]{5}$"),
    "US": re.compile(r"^[0-9]{5}(?:-[0-9]{4})?$"),
    "CA": re.compile(r"^[A-Z][0-9][A-Z] [0-9][A-Z][0-9]$"),
    "GB": re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$"),
    "AU": re.compile(r"^[0-9]{4}$"),
    "DE": re.compile(r"^[0-9]{5}$"),
    "FR": re.compile(r"^[0-9]{5}$"),
    "JP": re.compile(r"^[0-9]{3}-[0-9]{4}$"),
    "BR": re.compile(r"^[0-9]{5}-[0-9]{3}$"),
    "NZ": re.compile(r"^[0-9]{4}$"),
}


def normalize_postal_code(country: str, value: str) -> str:
    """Uppercase and tidy spacing so common valid inputs (e.g. '560 001', 'nw16xe') pass."""
    compact = re.sub(r"[\s-]+", "", value).upper()
    if country in {"IN", "AU", "DE", "FR", "NZ"}:
        return compact
    if country == "US":
        return f"{compact[:5]}-{compact[5:]}" if len(compact) == 9 else compact
    if country in {"GB", "CA"} and len(compact) > 3:
        return f"{compact[:-3]} {compact[-3:]}"
    if country == "JP" and len(compact) == 7:
        return f"{compact[:3]}-{compact[3:]}"
    if country == "BR" and len(compact) == 8:
        return f"{compact[:5]}-{compact[5:]}"
    return " ".join(value.split()).upper()

# ISO 3166-1 alpha-2 officially assigned country/territory codes (249).
ISO_COUNTRY_CODES = {
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT",
    "AU", "AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI",
    "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY",
    "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
    "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
    "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK",
    "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
    "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
    "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR",
    "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
    "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS",
    "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
    "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW",
    "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
    "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
    "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
    "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM",
    "SN", "SO", "SR", "SS", "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF",
    "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR", "TT", "TV", "TW",
    "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
}
COMMON_COUNTRY_CODES = ISO_COUNTRY_CODES  # backwards-compatible name

NOTE = (
    "Format/completeness checks only (plus India PIN↔location match when available). "
    "A valid result does not confirm that the address exists, is occupied, or can "
    "receive mail or deliveries."
)

# Common alternate spellings / short names for Indian states and major cities.
# Keys are normalized (upper, no punctuation). Values map to canonical names used
# in the India Post directory so user input can match.
_IN_NAME_ALIASES: dict[str, str] = {
    "BANGALORE": "BENGALURU",
    "BENGALURU": "BENGALURU",
    "BOMBAY": "MUMBAI",
    "MUMBAI": "MUMBAI",
    "MADRAS": "CHENNAI",
    "CHENNAI": "CHENNAI",
    "CALCUTTA": "KOLKATA",
    "KOLKATA": "KOLKATA",
    "POONA": "PUNE",
    "PUNE": "PUNE",
    "TRIVANDRUM": "THIRUVANANTHAPURAM",
    "THIRUVANANTHAPURAM": "THIRUVANANTHAPURAM",
    "COCHIN": "KOCHI",
    "KOCHI": "KOCHI",
    "GURGAON": "GURUGRAM",
    "GURUGRAM": "GURUGRAM",
    "NOIDA": "NOIDA",
    "NEW DELHI": "NEW DELHI",
    "DELHI": "DELHI",
    "NCR": "DELHI",
    "ORISSA": "ODISHA",
    "ODISHA": "ODISHA",
    "UTTARANCHAL": "UTTARAKHAND",
    "UTTARAKHAND": "UTTARAKHAND",
    "PONDICHERRY": "PUDUCHERRY",
    "PUDUCHERRY": "PUDUCHERRY",
    "ANDAMAN": "ANDAMAN AND NICOBAR ISLANDS",
    "ANDAMAN AND NICOBAR": "ANDAMAN AND NICOBAR ISLANDS",
    "ANDAMAN AND NICOBAR ISLANDS": "ANDAMAN AND NICOBAR ISLANDS",
    "J AND K": "JAMMU AND KASHMIR",
    "JAMMU AND KASHMIR": "JAMMU AND KASHMIR",
    "JK": "JAMMU AND KASHMIR",
    "HP": "HIMACHAL PRADESH",
    "HIMACHAL": "HIMACHAL PRADESH",
    "HIMACHAL PRADESH": "HIMACHAL PRADESH",
    "UP": "UTTAR PRADESH",
    "UTTAR PRADESH": "UTTAR PRADESH",
    "MP": "MADHYA PRADESH",
    "MADHYA PRADESH": "MADHYA PRADESH",
    "AP": "ANDHRA PRADESH",
    "ANDHRA PRADESH": "ANDHRA PRADESH",
    "TN": "TAMIL NADU",
    "TAMIL NADU": "TAMIL NADU",
    "TAMILNADU": "TAMIL NADU",
    "WB": "WEST BENGAL",
    "WEST BENGAL": "WEST BENGAL",
    "KA": "KARNATAKA",
    "KARNATAKA": "KARNATAKA",
    "MH": "MAHARASHTRA",
    "MAHARASHTRA": "MAHARASHTRA",
    "GJ": "GUJARAT",
    "GUJARAT": "GUJARAT",
    "RJ": "RAJASTHAN",
    "RAJASTHAN": "RAJASTHAN",
    "PB": "PUNJAB",
    "PUNJAB": "PUNJAB",
    "HR": "HARYANA",
    "HARYANA": "HARYANA",
    "KL": "KERALA",
    "KERALA": "KERALA",
    "TS": "TELANGANA",
    "TELANGANA": "TELANGANA",
    "CG": "CHHATTISGARH",
    "CHHATTISGARH": "CHHATTISGARH",
    "CHATTISGARH": "CHHATTISGARH",
    "JH": "JHARKHAND",
    "JHARKHAND": "JHARKHAND",
    "BR": "BIHAR",
    "BIHAR": "BIHAR",
    "AS": "ASSAM",
    "ASSAM": "ASSAM",
    "GA": "GOA",
    "GOA": "GOA",
}

def _normalize_name(value: str | None) -> str:
    """Uppercase, strip accents/punctuation, collapse whitespace for comparison."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9\s]", " ", text)
    return " ".join(text.upper().split())


def _canonical_in_name(value: str | None) -> str:
    norm = _normalize_name(value)
    return _IN_NAME_ALIASES.get(norm, norm)


def _names_match(user_value: str | None, candidates: list[str]) -> bool:
    """True if user_value matches any candidate after alias/normalization, or is a substring."""
    if not user_value or not candidates:
        return False
    user = _canonical_in_name(user_value)
    if not user:
        return False
    for cand in candidates:
        c = _canonical_in_name(cand)
        if not c:
            continue
        if user == c:
            return True
        # Allow "Bengaluru" vs "BENGALURU URBAN", "Mumbai" vs "MUMBAI SUBURBAN", etc.
        if user in c or c in user:
            return True
        # Token overlap for multi-word (e.g. "New Delhi" vs "NEW DELHI")
        user_tokens = set(user.split())
        cand_tokens = set(c.split())
        if user_tokens and user_tokens <= cand_tokens:
            return True
    return False


def lookup_india_pin(postal_code: str) -> dict | None:
    """Return India Post state/districts for a PIN, or None if unknown / data unavailable."""
    if india_pin is None or not postal_code:
        return None
    if not india_pin.validate(postal_code):
        return None
    details = india_pin.get_details(postal_code)
    if not details:
        return None
    return {
        "pincode": details.get("pincode", postal_code),
        "state": details.get("state"),
        "states": list(details.get("states") or []),
        "districts": list(details.get("districts") or []),
    }


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_rapidapi_proxy_secret: Annotated[str | None, Header(alias="X-RapidAPI-Proxy-Secret")] = None,
) -> None:
    # Convenient for local development. Set ADDRESSGUARD_API_KEY (and/or
    # MARKETPLACE_PROXY_SECRET) in production to enable authentication.
    # On Cloudflare Workers use: npx wrangler secret put ADDRESSGUARD_API_KEY
    api_key = _env("ADDRESSGUARD_API_KEY")
    proxy_secret = _env("MARKETPLACE_PROXY_SECRET")
    if not api_key and not proxy_secret:
        return
    if api_key and x_api_key and secrets.compare_digest(x_api_key, api_key):
        return
    if proxy_secret and x_rapidapi_proxy_secret and secrets.compare_digest(
        x_rapidapi_proxy_secret, proxy_secret
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_api_key", "message": "Provide a valid X-API-Key header."},
    )


Auth = Annotated[None, Depends(require_api_key)]


def validate_address(address: AddressInput) -> ValidationResponse:
    country = address.country_code.upper()
    issues: list[Issue] = []
    checks = {
        "required_fields_present": bool(address.address_line1 and address.city and country),
        "country_code_format": bool(re.fullmatch(r"[A-Z]{2}", country)),
        "country_code_recognized": country in ISO_COUNTRY_CODES,
        "postal_code_format": True,
        "india_pin_known": None,
        "india_state_match": None,
        "india_city_district_match": None,
    }
    verification_level = "format_only"
    india_lookup: dict | None = None

    if country not in ISO_COUNTRY_CODES:
        issues.append(Issue(
            code="unknown_country_code",
            field="country_code",
            message="This country code is not an officially assigned ISO 3166-1 alpha-2 code. Check the code.",
        ))

    postal = normalize_postal_code(country, address.postal_code) if address.postal_code else None

    if not postal:
        checks["postal_code_format"] = False
        required = country in POSTAL_PATTERNS
        issues.append(Issue(
            code="postal_code_missing",
            field="postal_code",
            message=(
                f"A postal code is required for {country} addresses."
                if required
                else "No postal code was supplied. Some destinations do not require one."
            ),
            severity="warning" if required else "info",
        ))
    elif country in POSTAL_PATTERNS:
        if not POSTAL_PATTERNS[country].fullmatch(postal):
            checks["postal_code_format"] = False
            issues.append(Issue(
                code="postal_code_format_invalid",
                field="postal_code",
                message=f"The postal code does not match the API's basic format rule for {country}.",
            ))
    else:
        issues.append(Issue(
            code="postal_code_format_not_checked",
            field="postal_code",
            message=f"No built-in postal-code pattern is configured for {country}; format was not verified.",
            severity="info",
        ))

    # India PIN → state / district cross-check (official India Post directory).
    if country == "IN" and postal and checks["postal_code_format"]:
        india_lookup = lookup_india_pin(postal)
        if india_lookup is None and india_pin is not None:
            checks["india_pin_known"] = False
            issues.append(Issue(
                code="india_pin_unknown",
                field="postal_code",
                message=(
                    f"PIN {postal} is not present in the India Post directory snapshot. "
                    "It may be new, reserved, or mistyped."
                ),
            ))
        elif india_lookup is not None:
            checks["india_pin_known"] = True
            verification_level = "india_pin_matched"
            expected_states = india_lookup.get("states") or (
                [india_lookup["state"]] if india_lookup.get("state") else []
            )
            expected_districts = india_lookup.get("districts") or []

            # State check
            if address.state:
                state_ok = _names_match(address.state, expected_states)
                checks["india_state_match"] = state_ok
                if not state_ok:
                    issues.append(Issue(
                        code="india_state_mismatch",
                        field="state",
                        message=(
                            f"State '{address.state}' does not match India Post data for PIN {postal} "
                            f"(expected: {', '.join(expected_states) or 'unknown'})."
                        ),
                    ))
            else:
                checks["india_state_match"] = None
                issues.append(Issue(
                    code="india_state_suggested",
                    field="state",
                    message=(
                        f"India Post lists state(s) {', '.join(expected_states)} for PIN {postal}. "
                        "Consider filling state for stronger validation."
                    ),
                    severity="info",
                ))

            # City / district check — city often holds district or city name
            city_ok = _names_match(address.city, expected_districts) or _names_match(
                address.city, expected_states
            )
            # Also accept common city aliases that map into these districts
            if not city_ok and expected_districts:
                # e.g. user city "Bangalore" → BENGALURU, district "BENGALURU URBAN"
                city_canon = _canonical_in_name(address.city)
                for dist in expected_districts:
                    if city_canon and city_canon in _canonical_in_name(dist):
                        city_ok = True
                        break
            checks["india_city_district_match"] = city_ok
            if not city_ok:
                issues.append(Issue(
                    code="india_city_district_mismatch",
                    field="city",
                    message=(
                        f"City '{address.city}' does not match India Post district(s) for PIN {postal} "
                        f"(expected district(s): {', '.join(expected_districts) or 'unknown'}). "
                        "This is a common signal for COD / address fraud."
                    ),
                ))

    normalized = {
        "address_line1": " ".join(address.address_line1.split()),
        "address_line2": " ".join(address.address_line2.split()) if address.address_line2 else None,
        "city": " ".join(address.city.split()),
        "state": " ".join(address.state.split()) if address.state else None,
        "postal_code": postal,
        "country_code": country,
    }
    if india_lookup:
        normalized["india_post"] = {
            "state": india_lookup.get("state"),
            "states": india_lookup.get("states"),
            "districts": india_lookup.get("districts"),
        }

    blocking_codes = {
        "unknown_country_code",
        "postal_code_format_invalid",
        "india_pin_unknown",
        "india_state_mismatch",
        "india_city_district_mismatch",
    }
    if country in POSTAL_PATTERNS:
        blocking_codes.add("postal_code_missing")
    is_valid = checks["required_fields_present"] and not any(
        issue.code in blocking_codes for issue in issues
    )

    # Drop null check keys so response stays clean for non-IN addresses
    checks_out = {k: v for k, v in checks.items() if v is not None}

    return ValidationResponse(
        is_valid=is_valid,
        verification_level=verification_level,
        normalized_address=normalized,
        issues=issues,
        checks=checks_out,
        note=NOTE,
    )


@app.get("/", tags=["General"])
def root():
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "message": "Validate and normalize address data with a simple JSON API.",
    }


@app.get("/health", tags=["General"])
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.post("/v1/validate", response_model=ValidationResponse, tags=["Addresses"], dependencies=[Depends(require_api_key)])
def validate_endpoint(address: AddressInput):
    """Validate required fields and common postal-code formats."""
    return validate_address(address)


@app.post("/v1/normalize", tags=["Addresses"], dependencies=[Depends(require_api_key)])
def normalize_endpoint(address: AddressInput):
    """Return cleaned address fields without claiming real-world verification."""
    result = validate_address(address)
    return {
        "normalized_address": result.normalized_address,
        "verification_level": result.verification_level,
        "note": NOTE,
    }


@app.post("/v1/batch-validate", tags=["Addresses"], dependencies=[Depends(require_api_key)])
def batch_validate_endpoint(payload: BatchAddressInput):
    """Validate up to 100 addresses in one request."""
    results = [validate_address(address).model_dump() for address in payload.addresses]
    return {
        "count": len(results),
        "valid_count": sum(1 for result in results if result["is_valid"]),
        "invalid_count": sum(1 for result in results if not result["is_valid"]),
        "results": results,
        "note": NOTE,
    }


# Cloudflare Workers ASGI entrypoint (required for Python Workers)
# Local uvicorn still works: uvicorn src.main:app --reload
try:
    from workers import asgi

    Default = asgi.entrypoint(app)
except ImportError:  # pragma: no cover - local / non-Workers runtime
    pass
