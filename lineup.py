#!/usr/bin/env python3
"""Create a satirical Team of the Weak football graphic.

The renderer targets a 1080x1350 RGBA canvas. Player coordinates are the
upper-left corners of cards (not their centers). The standard 4-2-3-1 uses
11 of the supplied slots; ST and LM/W are the two optional flex positions,
while CF is an alternate for ST. See README.md for the full roster format.

Examples:
    python lineup.py --mode manual --roster data/roster.csv
    FOOTBALL_DATA_TOKEN=... python lineup.py --mode live --league PL
    python lineup.py --roster data/roster.json --output output/weak_xi.png

The football-data.org API is an optional input source. If it is unavailable,
missing a token, rate-limited, or returns an unusable squad, a local roster is
used when available. No external assets are required to render an image.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import textwrap
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import requests
except ImportError as exc:  # pragma: no cover - environment dependent
    raise SystemExit("Missing dependency 'requests'. Install with: pip install requests") from exc

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError as exc:  # pragma: no cover - environment dependent
    raise SystemExit("Missing dependency 'Pillow'. Install with: pip install Pillow") from exc

LOG = logging.getLogger("lineup")
CANVAS_SIZE = (1080, 1350)
API_BASE = "https://api.football-data.org/v4"
LEAGUES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
}

# All requested coordinate slots. The conventional 4-2-3-1 starters are marked
# in ACTIVE_POSITIONS; the remaining positions are available via --include-flex.
POSITION_COORDS: dict[str, tuple[int, int]] = {
    "ST": (310, 220), "CF": (580, 220),
    "LAM": (100, 360), "CAM": (340, 430), "RAM": (580, 430), "LM/W": (820, 360),
    "CDM-L": (220, 600), "CDM-R": (580, 600),
    "LB": (100, 760), "CB1": (340, 760), "CB2": (580, 760), "RB": (820, 760),
    "GK": (460, 1000),
}
ACTIVE_POSITIONS = ("ST", "LAM", "CAM", "RAM", "CDM-L", "CDM-R", "LB", "CB1", "CB2", "RB", "GK")
FLEX_POSITIONS = ("CF", "LM/W")
CARD_SIZE = (140, 155)


@dataclass
class Player:
    """A player record accepted from CSV, JSON, or football-data.org."""

    name: str
    position: str = ""
    player_id: str = ""
    club: str = ""
    club_code: str = ""
    image: str = ""
    goals: float = 0.0
    display_name: str = ""
    display_club_code: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "Player":
        """Create a player from a case-insensitive mapping."""
        normalized = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
        name = str(normalized.get("name", normalized.get("player", ""))).strip()
        if not name:
            raise ValueError("Roster row is missing a player name")
        return cls(
            name=name,
            position=str(normalized.get("position", "")).strip(),
            player_id=str(normalized.get("id", normalized.get("player_id", ""))).strip(),
            club=str(normalized.get("club", normalized.get("team", ""))).strip(),
            club_code=str(normalized.get("club_code", "")).strip(),
            image=str(normalized.get("image", normalized.get("photo", ""))).strip(),
            goals=_safe_float(normalized.get("goals", 0)),
            display_name=str(normalized.get("display_name", "")).strip(),
            display_club_code=str(normalized.get("display_club_code", "")).strip(),
            extra={k: v for k, v in normalized.items() if k not in {
                "name", "player", "position", "id", "player_id", "club", "team",
                "club_code", "image", "photo", "goals", "display_name", "display_club_code"
            }},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "position": self.position, "id": self.player_id,
            "club": self.club, "club_code": self.club_code, "image": self.image,
            "goals": self.goals, "display_name": self.display_name,
            "display_club_code": self.display_club_code,
        }


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def slugify(value: str) -> str:
    """Return an ASCII filename-friendly version of a name."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def ensure_directories(root: Path) -> None:
    """Create the standard input and output directories if absent."""
    for directory in ("assets", "cutouts", "cutouts/raw", "crests", "output", "data"):
        (root / directory).mkdir(parents=True, exist_ok=True)


def load_roster(path: Path) -> list[Player]:
    """Load players from a JSON list/object or a CSV file."""
    if not path.is_file():
        raise FileNotFoundError(f"Roster file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    elif suffix == ".json":
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload.get("players", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("JSON roster must be a list or an object containing a 'players' list")
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("YAML roster support requires PyYAML; install with: pip install PyYAML") from exc
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML roster: {exc}") from exc
        rows = payload.get("players", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("YAML roster must be a list or an object containing a 'players' list")
    else:
        raise ValueError("Roster format must be .csv, .json, .yaml, or .yml")
    players = [Player.from_mapping(row) for row in rows if isinstance(row, dict)]
    if not players:
        raise ValueError(f"No valid players found in roster: {path}")
    return players


class FootballDataClient:
    """Small football-data.org v4 client with timeouts and API-friendly errors.

    A token is read from FOOTBALL_DATA_TOKEN unless passed explicitly. The
    live selector reads standings, fetches squads for the six lowest-ranked clubs,
    and uses scorer totals inversely to rank available players; this limits API calls
    while still yielding current league-squad data.
    """

    def __init__(self, token: Optional[str] = None, timeout: float = 12.0):
        self.token = token or os.environ.get("FOOTBALL_DATA_TOKEN", "")
        self.timeout = timeout
        self.session = requests.Session()
        if self.token:
            self.session.headers.update({"X-Auth-Token": self.token})

    def _get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("FOOTBALL_DATA_TOKEN is not set")
        response = self.session.get(f"{API_BASE}/{endpoint.lstrip('/')}", params=params, timeout=self.timeout)
        if response.status_code == 429:
            raise RuntimeError("football-data.org rate limit reached (HTTP 429)")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected API response at {endpoint}")
        return payload

    def fetch_league_roster(self, league: str, season: Optional[int] = None) -> list[Player]:
        """Fetch available squad members from the lowest-ranked clubs in a league."""
        league = league.upper()
        if league not in LEAGUES:
            raise ValueError(f"Unsupported league {league!r}; use one of {', '.join(LEAGUES)}")
        params = {"season": season} if season else None
        standings = self._get(f"competitions/{league}/standings", params=params)
        tables = standings.get("standings", [])
        table = next((item.get("table", []) for item in tables if item.get("type") == "TOTAL"), [])
        if not table and tables:
            table = tables[0].get("table", [])
        team_ids: list[tuple[int, str]] = []
        # Bottom-of-table clubs are the source pool for a deliberately weak XI.
        for item in (table[-6:] if len(table) > 6 else table):
            team = item.get("team", {})
            if team.get("id"):
                team_ids.append((int(team["id"]), str(team.get("name", ""))))
        if not team_ids:
            teams_payload = self._get(f"competitions/{league}/teams", params=params)
            team_ids = [(int(team["id"]), str(team.get("name", "")))
                        for team in teams_payload.get("teams", [])[:6] if team.get("id")]
        scorer_goals: dict[int, float] = {}
        try:
            scorers = self._get(f"competitions/{league}/scorers", {**(params or {}), "limit": 100})
            for row in scorers.get("scorers", []):
                person = row.get("player", {})
                if person.get("id"):
                    scorer_goals[int(person["id"])] = _safe_float(row.get("goals"))
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            LOG.info("Scorer data unavailable; using squad order: %s", exc)

        players: list[Player] = []
        for team_id, team_name in team_ids:
            try:
                payload = self._get(f"teams/{team_id}")
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                LOG.warning("Could not load %s squad: %s", team_name, exc)
                continue
            club = payload.get("name", team_name)
            crest = payload.get("shortName", "")
            for person in payload.get("squad", []):
                if not person.get("name"):
                    continue
                pid = str(person.get("id", ""))
                players.append(Player(
                    name=str(person["name"]), position=str(person.get("position") or ""),
                    player_id=pid, club=club, club_code=str(crest),
                    goals=scorer_goals.get(int(pid), 0.0) if pid.isdigit() else 0.0,
                ))
        if not players:
            raise RuntimeError("The API returned no usable squad players")
        return players


def apply_overrides(players: Iterable[Player], path: Path) -> list[Player]:
    """Apply overrides keyed by player id or case-insensitive real name.

    Example: {"players":{"Marcus Rashford":{"display_name":"RASHFORD"}},
    "clubs":{"Manchester United":"MUN"}}. Each player may also be an
    object containing display_name and display_club_code.
    """
    result = list(players)
    if not path.is_file():
        LOG.info("No override file at %s; continuing without overrides", path)
        return result
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("Overrides JSON must contain an object")
    player_rules = config.get("players", {})
    club_rules = config.get("clubs", {})
    if not isinstance(player_rules, dict) or not isinstance(club_rules, dict):
        raise ValueError("Override 'players' and 'clubs' values must be objects")
    normalized_rules = {str(key).casefold(): value for key, value in player_rules.items()}
    for player in result:
        rule = normalized_rules.get(player.player_id.casefold()) if player.player_id else None
        rule = rule or normalized_rules.get(player.name.casefold())
        if isinstance(rule, str):
            player.display_name = rule
        elif isinstance(rule, dict):
            player.display_name = str(rule.get("display_name", player.display_name))
            player.display_club_code = str(rule.get("display_club_code", player.display_club_code))
        if player.club in club_rules:
            player.display_club_code = str(club_rules[player.club])
        if player.display_club_code:
            player.club_code = player.display_club_code
    return result


def canonical_position(raw: str) -> str:
    """Normalize common API/manual position labels to a formation position."""
    value = raw.strip().upper().replace(" ", "")
    aliases = {
        "GOALKEEPER": "GK", "GOALIE": "GK", "GK": "GK",
        "LEFTBACK": "LB", "LB": "LB", "RIGHTBACK": "RB", "RB": "RB",
        "CENTREBACK": "CB", "CENTERBACK": "CB", "DEFENDER": "CB", "DEFENCE": "CB", "DEFENSE": "CB",
        "CB": "CB", "CB1": "CB", "CB2": "CB",
        "CDM": "CDM", "CDML": "CDM", "CDMR": "CDM", "CDM-L": "CDM", "CDM-R": "CDM",
        "DEFENSIVEMIDFIELD": "CDM", "DEFENSIVEMIDFIELDER": "CDM",
        "MIDFIELD": "MID", "MIDFIELDER": "MID", "ATTACKINGMIDFIELD": "CAM", "CAM": "CAM",
        "LAM": "WING", "RAM": "WING", "LM/W": "WING", "LMW": "WING",
        "WINGER": "WING", "LEFTWINGER": "WING", "RIGHTWINGER": "WING", "WING": "WING",
        "FORWARD": "FW", "OFFENCE": "FW", "OFFENSE": "FW", "STRIKER": "ST", "ST": "ST",
        "CF": "CF",
    }
    return aliases.get(value, value)


def select_starting_xi(players: list[Player], include_flex: bool = False) -> dict[str, Player]:
    """Choose an XI using position fit and low goal totals as a tie-breaker.

    The selected standard formation is ST, three attacking midfielders, two
    holding midfielders, a back four, and a goalkeeper. Missing roles are
    filled from the best remaining available players so imperfect source data
    still produces a complete graphic. With include_flex, CF and LM/W are
    added as two extra bench/flex cards without displacing the XI.
    """
    remaining = list(players)
    selected: dict[str, Player] = {}
    aliases = {
        "GK": {"GK"}, "LB": {"LB", "CB", "DEF"}, "CB1": {"CB", "DEF", "LB", "RB"},
        "CB2": {"CB", "DEF", "LB", "RB"}, "RB": {"RB", "CB", "DEF"},
        "CDM-L": {"CDM", "MID"}, "CDM-R": {"CDM", "MID"},
        "LAM": {"WING", "CAM", "MID", "FW"}, "CAM": {"CAM", "MID", "WING"},
        "RAM": {"WING", "CAM", "MID", "FW"}, "ST": {"ST", "FW", "CF"},
        "CF": {"CF", "ST", "FW"}, "LM/W": {"WING", "MID"},
    }
    # Fill scarce roles first; low goal totals among equally suitable players
    # act as a deliberately crude proxy for disappointing performance.
    order = ["GK", "LB", "RB", "CB1", "CB2", "CDM-L", "CDM-R", "LAM", "CAM", "RAM", "ST"]
    if include_flex:
        order.extend(FLEX_POSITIONS)
    for slot in order:
        candidates = [(i, p) for i, p in enumerate(remaining) if canonical_position(p.position) in aliases[slot]]
        if not candidates:
            candidates = list(enumerate(remaining))
        if not candidates:
            break
        # For defensive slots, preserve likely attackers for forward positions.
        def score(item: tuple[int, Player]) -> tuple[int, float, int]:
            index, player = item
            pos = canonical_position(player.position)
            preferred = pos in aliases[slot]
            return (int(preferred), -player.goals, -index)
        index, chosen = max(candidates, key=score)
        selected[slot] = chosen
        remaining.pop(index)
    return selected


def find_asset(directory: Path, explicit: str, player: Player, suffixes: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")) -> Optional[Path]:
    """Resolve an explicit asset path, then search by player id and name."""
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = directory.parent / path if path.parts and path.parts[0] in {"cutouts", "crests"} else directory / path
        if path.is_file():
            return path
    for stem in (player.player_id, slugify(player.name)):
        if stem:
            for suffix in suffixes:
                path = directory / f"{stem}{suffix}"
                if path.is_file():
                    return path
    return None


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a widely available bold font, falling back to Pillow's bitmap font."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def create_pitch() -> Image.Image:
    """Draw a self-contained royal-blue pitch when pitch_bg.png is missing."""
    image = Image.new("RGBA", CANVAS_SIZE, (26, 66, 174, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    # Subtle alternating bands preserve contrast and give the field depth.
    for y in range(0, CANVAS_SIZE[1], 180):
        draw.rectangle((0, y, CANVAS_SIZE[0], min(y + 90, CANVAS_SIZE[1])), fill=(31, 75, 185, 255))
    line = (255, 255, 255, 255)
    draw.rectangle((38, 38, 1042, 1312), outline=line, width=4)
    draw.line((38, 675, 1042, 675), fill=line, width=4)
    draw.ellipse((390, 557, 690, 857), outline=line, width=4)
    draw.ellipse((530, 697, 550, 717), fill=line)
    # Penalty areas at top and bottom, plus six-yard boxes.
    draw.rectangle((280, 38, 800, 220), outline=line, width=4)
    draw.rectangle((410, 38, 670, 115), outline=line, width=4)
    draw.rectangle((280, 1130, 800, 1312), outline=line, width=4)
    draw.rectangle((410, 1235, 670, 1312), outline=line, width=4)
    return image


def create_fallback_card(size: tuple[int, int] = CARD_SIZE) -> Image.Image:
    """Draw a hexagon-window style card and a white nameplate."""
    w, h = size
    card = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    points = [(w // 2, 0), (w - 6, 27), (w - 6, h - 4), (6, h - 4), (6, 27)]
    draw.polygon(points, fill=(243, 246, 255, 255), outline=(255, 255, 255, 255))
    draw.line(points + [points[0]], fill=(255, 255, 255, 255), width=3)
    # Transparent hexagon window reveals the pitch and player cutout underneath.
    window = [(w // 2, 10), (w - 18, 33), (w - 18, h - 37), (w // 2, h - 24), (18, h - 37), (18, 33)]
    draw.polygon(window, fill=(0, 0, 0, 0), outline=(255, 255, 255, 255))
    draw.rectangle((9, h - 35, w - 9, h - 5), fill=(255, 255, 255, 255))
    draw.line((11, h - 36, w - 11, h - 36), fill=(255, 255, 255, 255), width=2)
    return card


def _load_rgba(path: Optional[Path]) -> Optional[Image.Image]:
    if path is None or not path.is_file():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except (OSError, ValueError) as exc:
        LOG.warning("Could not open image %s: %s", path, exc)
        return None


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, initial_size: int) -> ImageFont.ImageFont:
    size = initial_size
    while size > 9:
        font = _font(size)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
        size -= 1
    return _font(9)


def _draw_player_card(canvas: Image.Image, player: Player, position: str, xy: tuple[int, int], root: Path) -> None:
    """Composite one card; missing assets are represented with vivid placeholders."""
    x, y = xy
    assets = root / "assets"
    frame = _load_rgba(assets / "card_hexagon.png") or create_fallback_card()
    frame = ImageOps.fit(frame, CARD_SIZE, method=Image.Resampling.LANCZOS)
    # Player art goes below the card frame, so the frame's window and nameplate remain visible.
    cutout_dir = root / "cutouts"
    player_path = find_asset(cutout_dir, player.image, player)
    cutout = _load_rgba(player_path)
    if cutout:
        cutout.thumbnail((112, 108), Image.Resampling.LANCZOS)
        px = (CARD_SIZE[0] - cutout.width) // 2
        py = 5 + max(0, (108 - cutout.height) // 2)
        canvas.alpha_composite(cutout, (x + px, y + py))
    else:
        # Placeholder silhouette with a unique accent based on the player name.
        color_value = sum(ord(char) for char in player.name) % 150
        color = (90 + color_value // 3, 150 + color_value // 5, 235, 255)
        placeholder = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
        pd = ImageDraw.Draw(placeholder)
        cx = CARD_SIZE[0] // 2
        pd.ellipse((cx - 19, 25, cx + 19, 63), fill=color)
        pd.rounded_rectangle((cx - 34, 59, cx + 34, 118), radius=20, fill=color)
        canvas.alpha_composite(placeholder, (x, y))
    canvas.alpha_composite(frame, (x, y))

    # Club badge overlaps the upper-left card corner. A circular fallback is intentional.
    crest_path = root / "crests" / f"{slugify(player.club_code or player.club)}.png"
    crest = _load_rgba(crest_path)
    badge_size = 42
    if crest:
        crest.thumbnail((badge_size, badge_size), Image.Resampling.LANCZOS)
        badge = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
        badge.alpha_composite(crest, ((badge_size - crest.width) // 2, (badge_size - crest.height) // 2))
    else:
        badge = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        hue = sum(ord(char) for char in (player.club_code or player.club)) % 180
        badge_color = (55 + hue // 3, 45 + hue // 4, 90 + hue // 2, 255)
        bd.ellipse((2, 2, 40, 40), fill=badge_color, outline=(255, 255, 255, 255), width=3)
        label = (player.club_code or player.club or "FC")[:3].upper()
        font = _font(10)
        bounds = bd.textbbox((0, 0), label, font=font)
        bd.text(((42 - (bounds[2] - bounds[0])) / 2, (42 - (bounds[3] - bounds[1])) / 2 - 1), label, font=font, fill="white")
    canvas.alpha_composite(badge, (x - 8, y - 7))

    # The nameplate is opaque white even if the supplied card frame lacks one.
    draw = ImageDraw.Draw(canvas)
    plate_top = y + CARD_SIZE[1] - 35
    draw.rectangle((x + 9, plate_top, x + CARD_SIZE[0] - 9, y + CARD_SIZE[1] - 5), fill="white")
    label = (player.display_name or player.name).upper().strip()
    label = re.sub(r"\s+", " ", label)
    draw.text((x + CARD_SIZE[0] / 2, plate_top + 1), label,
              font=_fit_text(draw, label, CARD_SIZE[0] - 18, 13), fill=(20, 28, 48), anchor="mt")
    draw.text((x + CARD_SIZE[0] / 2, plate_top + 17), position,
              font=_font(8), fill=(75, 86, 112), anchor="mt")


def render_graphic(selected: dict[str, Player], output: Path, root: Path,
                   include_flex: bool = False, league_label: str = "") -> Path:
    """Render a 1080x1350 transparent-layer composition and save a PNG."""
    pitch_path = root / "assets" / "pitch_bg.png"
    pitch = _load_rgba(pitch_path)
    if pitch is None:
        LOG.info("pitch_bg.png missing or invalid; drawing fallback pitch")
        pitch = create_pitch()
    else:
        pitch = ImageOps.fit(pitch, CANVAS_SIZE, method=Image.Resampling.LANCZOS)
    canvas = pitch.copy()
    # Header ribbon keeps the satire title legible against any user-supplied pitch.
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((340, 27, 740, 92), radius=13, fill=(13, 22, 49, 255), outline=(255, 255, 255, 255), width=2)
    title_font = _font(34)
    draw.text((540, 58), "TEAM OF THE WEAK", font=title_font, fill=(255, 255, 255, 255), anchor="mm")
    if league_label:
        draw.text((540, 101), league_label.upper(), font=_font(14), fill=(255, 255, 255, 255), anchor="mt")
    positions = list(ACTIVE_POSITIONS) + (list(FLEX_POSITIONS) if include_flex else [])
    missing: list[str] = []
    for position in positions:
        player = selected.get(position)
        if player is None:
            missing.append(position)
            continue
        _draw_player_card(canvas, player, position, POSITION_COORDS[position], root)
    if missing:
        LOG.warning("No players selected for positions: %s", ", ".join(missing))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    return output


def remove_backgrounds(raw_dir: Path, output_dir: Path) -> int:
    """Optionally remove backgrounds from images in cutouts/raw using rembg.

    Install the optional dependency with ``pip install rembg``. The function
    imports it lazily, so normal rendering does not require rembg or its model.
    """
    try:
        from rembg import remove
    except ImportError as exc:
        raise RuntimeError("Background removal requires optional dependency: pip install rembg") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for source in sorted(raw_dir.iterdir()):
        if not source.is_file() or source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            with Image.open(source) as image:
                result = remove(image.convert("RGBA"))
                result.save(output_dir / f"{source.stem}.png")
                count += 1
        except Exception as exc:  # keep processing the rest of the folder
            LOG.warning("Background removal failed for %s: %s", source, exc)
    return count


def build_parser() -> argparse.ArgumentParser:
    """Build the command line interface."""
    parser = argparse.ArgumentParser(
        description="Generate a satirical 4-2-3-1 Team of the Weak graphic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            API token: set FOOTBALL_DATA_TOKEN in the environment.
            Manual rosters: CSV, JSON, or YAML; see data/roster.csv and README.md.
            Example: python lineup.py --mode live --league PL --include-flex
        """),
    )
    parser.add_argument("--mode", choices=("manual", "live"), default="manual", help="roster source")
    parser.add_argument("--league", choices=tuple(LEAGUES), default="PL", help="football-data.org league code")
    parser.add_argument("--season", type=int, help="season start year, e.g. 2025")
    parser.add_argument("--roster", type=Path, help="manual/fallback CSV or JSON roster (default data/roster.csv)")
    parser.add_argument("--output", type=Path, help="output PNG path (default output/team_of_the_weak.png)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent, help="project/assets root")
    parser.add_argument("--overrides", type=Path, help="override JSON (default overrides.json at project root)")
    parser.add_argument("--include-flex", action="store_true", help="also render CF and LM/W flex cards (13 total)")
    parser.add_argument("--remove-backgrounds", action="store_true", help="process cutouts/raw using optional rembg")
    parser.add_argument("--verbose", action="store_true", help="show informational logs")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point; API failures gracefully fall back to a local roster."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")
    root = args.root.resolve()
    ensure_directories(root)
    if args.remove_backgrounds:
        try:
            count = remove_backgrounds(root / "cutouts" / "raw", root / "cutouts")
            LOG.info("Prepared %d cutout(s)", count)
        except RuntimeError as exc:
            LOG.error("%s", exc)
            return 2

    roster_path = args.roster or (root / "data" / "roster.csv")
    players: list[Player]
    if args.mode == "live":
        try:
            players = FootballDataClient().fetch_league_roster(args.league, args.season)
            LOG.info("Loaded %d players from %s", len(players), LEAGUES[args.league])
        except (requests.RequestException, ValueError, RuntimeError, KeyError) as exc:
            LOG.warning("Live data unavailable (%s); trying local roster %s", exc, roster_path)
            try:
                players = load_roster(roster_path)
            except (OSError, ValueError, RuntimeError) as local_exc:
                LOG.error("Could not load fallback roster: %s", local_exc)
                return 2
    else:
        try:
            players = load_roster(roster_path)
        except (OSError, ValueError, RuntimeError) as exc:
            LOG.error("Could not load roster: %s", exc)
            return 2

    override_path = args.overrides or (root / "overrides.json")
    try:
        players = apply_overrides(players, override_path)
    except (OSError, ValueError, TypeError) as exc:
        LOG.error("Could not read overrides: %s", exc)
        return 2
    selected = select_starting_xi(players, args.include_flex)
    output = args.output or (root / "output" / "team_of_the_weak.png")
    if not output.is_absolute():
        output = root / output
    label = LEAGUES[args.league] if args.mode == "live" else "Manual roster"
    try:
        saved = render_graphic(selected, output, root, args.include_flex, label)
    except (OSError, ValueError) as exc:
        LOG.error("Could not render graphic: %s", exc)
        return 2
    print(f"Created {saved} ({len(selected)} selected players; canvas {CANVAS_SIZE[0]}x{CANVAS_SIZE[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
