from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from rate_ingest.models import RateOffer


LOCATION_CATALOGUE_PARSER_FAMILIES = {
    "hapag_door_matrix",
    "hapag_india_rows",
    "offer_block",
    "site_to_site_rows",
}


@dataclass(frozen=True)
class CanonicalLocation:
    code: str
    display_name: str
    country_code: str
    subdivision_name: str | None = None
    un_locode: str | None = None


@dataclass(frozen=True)
class LocationResolution:
    location: CanonicalLocation
    matched_by: str


@dataclass(frozen=True)
class LocationIssue:
    role: str
    raw_name: str | None
    source_code: str | None
    source_reference: str | None
    sheet_name: str | None


def location_match_key(value: str | None) -> str:
    """Strict alias key: ignore case and harmless whitespace only."""
    return " ".join(str(value or "").strip().casefold().split())


def normalize_source_code(value: str | None) -> str | None:
    normalized = re.sub(r"\s+", "", str(value or "")).upper()
    return normalized or None


def location_code(display_name: str) -> str:
    value = display_name.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


class LocationCatalogue:
    def __init__(
        self,
        locations: Iterable[CanonicalLocation],
        aliases: Iterable[tuple[str, str]],
        source_codes: Iterable[tuple[str, str]],
    ) -> None:
        self.locations_by_code = {item.code: item for item in locations}
        self.aliases_by_key: dict[str, str] = {}
        for source_name, code in aliases:
            key = location_match_key(source_name)
            if not key:
                continue
            existing = self.aliases_by_key.get(key)
            if existing and existing != code:
                raise ValueError(
                    f"Location alias {source_name!r} maps to both {existing} and {code}"
                )
            self.aliases_by_key[key] = code
        self.location_by_source_code: dict[str, str] = {}
        for source_code, code in source_codes:
            key = normalize_source_code(source_code)
            if not key:
                continue
            existing = self.location_by_source_code.get(key)
            if existing and existing != code:
                raise ValueError(
                    f"Location source code {source_code!r} maps to both {existing} and {code}"
                )
            self.location_by_source_code[key] = code

    @classmethod
    def default(cls) -> "LocationCatalogue":
        return _build_default_catalogue()

    def resolve(
        self,
        raw_name: str | None,
        *,
        source_code: str | None = None,
    ) -> LocationResolution | None:
        code_key = normalize_source_code(source_code)
        if code_key:
            canonical_code = self.location_by_source_code.get(code_key)
            if canonical_code:
                return LocationResolution(
                    self.locations_by_code[canonical_code], "source_code"
                )
        name_key = location_match_key(raw_name)
        canonical_code = self.aliases_by_key.get(name_key)
        if canonical_code:
            return LocationResolution(self.locations_by_code[canonical_code], "alias")
        return None

    def rows(self) -> list[CanonicalLocation]:
        return sorted(self.locations_by_code.values(), key=lambda item: item.code)

    def alias_rows(self) -> list[tuple[str, str, str]]:
        return sorted(
            (
                (source_name, location_match_key(source_name), code)
                for source_name, code in _default_alias_pairs()
            ),
            key=lambda item: (item[2], item[1]),
        )

    def source_code_rows(self) -> list[tuple[str, str]]:
        return sorted(self.location_by_source_code.items())


def apply_location_catalogue(
    offers: list[RateOffer],
    catalogue: LocationCatalogue,
) -> list[LocationIssue]:
    issues: list[LocationIssue] = []
    for offer in offers:
        collection_name = offer.place_of_receipt or offer.origin
        collection_source_code = extract_collection_source_code(offer)
        collection = catalogue.resolve(
            collection_name,
            source_code=collection_source_code,
        )
        if collection:
            offer.collection_location_code = collection.location.code
            offer.collection_location_name = collection.location.display_name
        else:
            issues.append(
                LocationIssue(
                    role="collection",
                    raw_name=collection_name,
                    source_code=collection_source_code,
                    source_reference=offer.raw_row_reference,
                    sheet_name=offer.raw_sheet_name,
                )
            )

        destination_name = offer.final_destination or offer.pod
        destination_source_code = extract_destination_source_code(offer)
        destination = catalogue.resolve(
            destination_name,
            source_code=destination_source_code,
        )
        if destination:
            offer.destination_location_code = destination.location.code
            offer.destination_location_name = destination.location.display_name
        else:
            issues.append(
                LocationIssue(
                    role="destination",
                    raw_name=destination_name,
                    source_code=destination_source_code,
                    source_reference=offer.raw_row_reference,
                    sheet_name=offer.raw_sheet_name,
                )
            )
    return issues


def ensure_offer_locations(
    offer: RateOffer,
    catalogue: LocationCatalogue | None = None,
) -> RateOffer:
    if (
        offer.collection_location_code
        and offer.collection_location_name
        and offer.destination_location_code
        and offer.destination_location_name
    ):
        return offer
    apply_location_catalogue([offer], catalogue or LocationCatalogue.default())
    return offer


def extract_collection_source_code(offer: RateOffer) -> str | None:
    explicit = offer.raw_row_json.get("collection_source_code")
    if explicit:
        return normalize_source_code(str(explicit))
    collection_raw = str(offer.raw_row_json.get("collection_raw") or "")
    match = re.match(r"^\s*([A-Za-z]{2}[A-Za-z0-9]{3})\s*/", collection_raw)
    return normalize_source_code(match.group(1)) if match else None


def extract_destination_source_code(offer: RateOffer) -> str | None:
    explicit = offer.raw_row_json.get("destination_source_code")
    return normalize_source_code(str(explicit)) if explicit else None


_COLLECTION_DISPLAY_OVERRIDES = {
    "Antwerp, Antwerp, Belgium": "Antwerp, BE",
    "Rotterdam, Zuid-Holland, Netherlands": "Rotterdam, NL",
    "Barrow In Furness, GB": "Barrow-in-Furness, GB",
    "Burton on Trent, GB": "Burton-upon-Trent, GB",
    "Deeside Industrial Park, GB": "Deeside, GB",
    "Rushden Hertfordshire, GB": "Rushden, Hertfordshire, GB",
    "Rushden Northampton, GB": "Rushden, Northamptonshire, GB",
    "Water Orton Warwickshire, GB": "Water Orton, GB",
    "WillenhallWalsall, GB": "Willenhall, GB",
}


_COLLECTION_SUFFIXES = sorted(
    {
        " Brighton And Hove",
        " Northern Ireland",
        " Tyne and Wear",
        " Northamptonshire",
        " Nottinghamshire",
        " Cambridgeshire",
        " Gloucestershire BS",
        " Gloucestershire",
        " West Midlands",
        " W Midlands",
        " South Yorks",
        " Staffordshire",
        " Hertfordshire",
        " Warwickshire",
        " Lincolnshire",
        " Derbyshire NG",
        " Derbyshire",
        " West Sussex",
        " Bedfordshire",
        " Lanarkshire",
        " Lancashire",
        " Manchester M",
        " Manchester",
        " Rotherham S",
        " Norfolk NR",
        " Norfolk IP",
        " Norfolk",
        " Yorkshire DN",
        " Yorkshire",
        " London SE",
        " London UB",
        " London",
        " Hampshire",
        " Cambrigdeshire",
        " Cambridgeshire",
        " Somerset",
        " Kirklees",
        " Caerphilly",
        " Sefton",
        " Cheshire",
        " Wolverhampton",
        " Co Cork",
        " Kent ME",
        " Kent",
        " Essex",
        " Lancs",
        " Lincs",
        " Cambs",
        " Notts",
        " Shrops",
        " York YO",
        " Yorks",
        " Gloucs",
        " Worcester",
        " Tipperary",
        " Swindon",
        " Warwickshire",
        " Glam",
        " Tyne",
        " Redcar",
        " Birmingham",
        " Man",
        " Ches",
        " PE",
    },
    key=len,
    reverse=True,
)


_DESTINATION_ALIASES = {
    "Bangkok, TH": ("Bangkok, TH", "Lat Krabang"),
    "Binh Duong, VN": ("Binh Duong, VN", "Binh Duong Terminal"),
    "Da Nang, VN": ("Da Nang, VN",),
    "Ennore Chennai, IN": ("Ennore Chennai, IN",),
    "Hai Phong, VN": (
        "Hai Phong, VN",
        "Hai Phong",
        "Haiphong - Lach Huyen, VN",
        "Haiphong – Lach Huyen, VN",
    ),
    "Haldia Port, IN": ("Haldia Port, IN",),
    "Hazira, IN": ("Hazira, IN",),
    "Ho Chi Minh, VN": (
        "Ho Chi Minh, VN",
        "Ho Chi Minh City, VN",
        "Cat Lei Terminal",
        "Cat Lai Terminal",
    ),
    "Jakarta, ID": ("Jakarta, ID", "Jakarta"),
    "Jawaharlal Nehru, IN": (
        "Jawaharlal Nehru, IN",
        "Jawaharlal Nehru, MAHARASHTRA, India",
    ),
    "Kaohsiung, TW": ("Kaohsiung, TW",),
    "Laem Chabang, TH": ("Laem Chabang, TH", "Laem Chabang"),
    "Mundra, IN": ("Mundra, IN", "Mundra, GUJARAT, India"),
    "Penang, MY": ("Penang, MY",),
    "Pipavav, IN": ("Pipavav, IN",),
    "Port Klang, MY": ("Port Klang, MY",),
    "Port Qasim, PK": ("Port Qasim, PK",),
    "Semarang, ID": ("Semarang, ID",),
    "Surabaya, ID": ("Surabaya, ID",),
    "Taichung, TW": ("Taichung, TW",),
    "Tuticorin, IN": ("Tuticorin, IN", "Tuticorin", "Tuticorin, TAMIL NADU, India"),
    "Visakhapatnam, IN": ("Visakhapatnam, IN",),
    "Vung Tau, VN": ("Vung Tau, VN", "Vung Tau"),
}


_HAPAG_VARIANT_TO_DISPLAY = {
    "Ashby-De-La-Zouch": "Ashby-de-la-Zouch, GB",
    "Barking": "Barking, GB",
    "Barrow-In-Furness": "Barrow-in-Furness, GB",
    "Blackburn": "Blackburn, GB",
    "Bolton": "Bolton, GB",
    "Bradford": "Bradford, GB",
    "Braintree": "Braintree, GB",
    "Burton-Upon-Trent": "Burton-upon-Trent, GB",
    "Buxton": "Buxton, GB",
    "Deeside": "Deeside, GB",
    "Eastleigh/Hants": "Eastleigh, GB",
    "Ely": "Ely, GB",
    "Godalming": "Godalming, GB",
    "Hatfield": "Hatfield, GB",
    "Hayes/Middlesex": "Hayes, GB",
    "Hook": "Hook, GB",
    "Leeds": "Leeds, GB",
    "Luton": "Luton, GB",
    "Melksham": "Melksham, GB",
    "Newton": "Newton, GB",
    "Poole": "Poole, GB",
    "Preston": "Preston, GB",
    "Rainham": "Rainham, GB",
    "Ramsgate": "Ramsgate, GB",
    "Ravensthorpe": "Ravensthorpe, GB",
    "Ripon": "Ripon, GB",
    "Rochford/Essex": "Rochford, GB",
    "Sheerness": "Sheerness, GB",
    "Southall": "Southall, GB",
    "Southwark": "Southwark, GB",
    "Swindon": "Swindon, GB",
    "West Bromich": "West Bromwich, GB",
    "Winchester, Hampshire": "Winchester, GB",
    "Winsford": "Winsford, GB",
}


_HAPAG_SOURCE_ROWS = """
GBADZ|Ashby-De-La-Zouch
GBALF|Alfreton
GBARU|Arundel
GBASH|Ashbourne
GBAVR|Andover
GBBHM|Birmingham
GBBIF|Barrow-In-Furness
GBBKG|Barking
GBBLB|Blackburn
GBBLF|Blandford Forum
GBBLT|Bolton
GBBRF|Bradford
GBBRI|Braintree
GBBTR|Burton-Upon-Trent
GBBUX|Buxton
GBCOL|Colchester
GBCRH|Cradley Heath
GBDFD|Dartford
GBDON|Doncaster
GBDSE|Deeside
GBDWY|Dewsbury
GBEAT|Eastleigh/Hants
GBELY|Ely
GBENF|Enfield
GBERI|Erith
GBGOD|Godalming
GBGOO|Goole
GBGOS|Gosport
GBGTM|Grantham
GBHAI|Hailsham
GBHAT|Hatfield
GBHHE|Hemel Hempstead
GBHMI|Hayes/Middlesex
GBHTP|Hartlepool
GBIPS|Ipswich
GBKLN|King's Lynn
GBLBA|Leeds
GBLCS|Leicester
GBLEH|Leatherhead
GBLON|London
GBMBY|Melton Mowbray
GBMDT|Maidstone
GBMIK|Milton Keynes
GBMLH|Melksham
GBMNC|Manchester
GBMTC|Mitcham
GBMXB|Mexborough
GBNRW|Norwich
GBNTG|Nottingham
GBNWO|Newton
GBOOK|Hook
GBPME|Portsmouth
GBPOO|Poole
GBPRE|Preston
GBRAH|Rainham
GBRDN|Reading
GBRIP|Ripon
GBRMG|Ramsgate
GBRUG|Rugby
GBRVH|Ravensthorpe
GBSCP|Scunthorpe
GBSHE|Sheffield
GBSHS|Sheerness
GBSIT|Sittingbourne
GBSLL|Southall
GBSME|Smethwick
GBSNN|Swindon
GBSOT|Stoke-On-Trent
GBSTK|Stockport
GBTAW|Tamworth
GBTPN|Tipton
GBWBL|Wimblington
GBWEB|West Bromich
GBWEL|Wellingborough
GBWIF|Winsford
GBWNE|Winchester, Hampshire
GBYEO|Yeovil
GBYRK|York
""".strip()


def _canonical_collection_display(source_name: str) -> str:
    if source_name in _COLLECTION_DISPLAY_OVERRIDES:
        return _COLLECTION_DISPLAY_OVERRIDES[source_name]
    match = re.match(r"^(.*),\s*(GB|IE)$", source_name)
    if not match:
        return source_name
    base, country_code = match.groups()
    for suffix in _COLLECTION_SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    base = base.strip()
    return f"{base}, {country_code}"


def _add_location(
    locations: dict[str, CanonicalLocation],
    display_name: str,
    *,
    un_locode: str | None = None,
) -> CanonicalLocation:
    country_match = re.search(r",\s*([A-Z]{2})$", display_name)
    if not country_match:
        raise ValueError(f"Canonical location lacks a country code: {display_name}")
    country_code = country_match.group(1)
    display_parts = [part.strip() for part in display_name.split(",")]
    subdivision_name = display_parts[-2] if len(display_parts) > 2 else None
    code = location_code(display_name)
    existing = locations.get(code)
    if existing and existing.display_name != display_name:
        raise ValueError(
            f"Canonical location code {code} is shared by {existing.display_name} and {display_name}"
        )
    item = CanonicalLocation(
        code=code,
        display_name=display_name,
        country_code=country_code,
        subdivision_name=subdivision_name,
        un_locode=un_locode or (existing.un_locode if existing else None),
    )
    locations[code] = item
    return item


def _default_catalogue_parts() -> tuple[
    list[CanonicalLocation],
    list[tuple[str, str]],
    list[tuple[str, str]],
]:
    locations: dict[str, CanonicalLocation] = {}
    aliases: list[tuple[str, str]] = []
    source_codes: list[tuple[str, str]] = []

    source_path = Path(__file__).with_name("bundled_collection_locations.txt")
    collection_sources = [
        line.strip()
        for line in source_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for source_name in collection_sources:
        display_name = _canonical_collection_display(source_name)
        item = _add_location(locations, display_name)
        aliases.append((source_name, item.code))
        aliases.append((display_name, item.code))

    for display_name, source_names in _DESTINATION_ALIASES.items():
        item = _add_location(locations, display_name)
        for source_name in source_names:
            aliases.append((source_name, item.code))

    for display_name in _HAPAG_VARIANT_TO_DISPLAY.values():
        item = _add_location(locations, display_name)
        aliases.append((display_name, item.code))

    short_names: dict[str, list[str]] = {}
    for item in locations.values():
        short_name = re.sub(r",\s*[A-Z]{2}$", "", item.display_name)
        short_names.setdefault(location_match_key(short_name), []).append(item.code)
    for short_key, codes in short_names.items():
        if len(codes) == 1:
            aliases.append((short_key, codes[0]))

    alias_lookup = {location_match_key(name): code for name, code in aliases}
    for source_name, display_name in _HAPAG_VARIANT_TO_DISPLAY.items():
        item = _add_location(locations, display_name)
        aliases.append((source_name, item.code))
        alias_lookup[location_match_key(source_name)] = item.code

    for row in _HAPAG_SOURCE_ROWS.splitlines():
        source_code, source_name = row.split("|", 1)
        canonical_code = alias_lookup.get(location_match_key(source_name))
        if not canonical_code:
            display_name = _HAPAG_VARIANT_TO_DISPLAY.get(source_name)
            if not display_name:
                raise ValueError(f"Hapag location is not catalogued: {source_name}")
            canonical_code = _add_location(locations, display_name).code
        source_codes.append((source_code, canonical_code))

    return list(locations.values()), aliases, source_codes


def _default_alias_pairs() -> list[tuple[str, str]]:
    _, aliases, _ = _default_catalogue_parts()
    return aliases


@lru_cache(maxsize=1)
def _build_default_catalogue() -> LocationCatalogue:
    locations, aliases, source_codes = _default_catalogue_parts()
    return LocationCatalogue(locations, aliases, source_codes)
