# Team of the Weak

A standalone Python/Pillow pipeline for making a satirical football lineup image on a **1080 × 1350** vertical pitch. It supports local CSV/JSON/YAML rosters and football-data.org v4 squad data for the Premier League, La Liga, Bundesliga, Serie A, and Ligue 1. It includes robust image fallbacks, optional player cutouts, club badges, and configurable meme-name overrides.

## Quick start

```bash
python -m pip install -r requirements.txt
python lineup.py --mode manual
```

The default manual roster is `data/roster.csv`; the result is `output/team_of_the_weak.png`. The program creates `assets/`, `cutouts/`, `cutouts/raw/`, `crests/`, `data/`, and `output/` if they do not exist. No assets are necessary to render: a royal-blue pitch, hexagon cards, player silhouettes, and club badges are drawn when the corresponding files are missing.

To show the optional CF and LM/W flex cards as well as the standard XI:

```bash
python lineup.py --mode manual --include-flex
```

This renders 13 cards: the 11 conventional 4-2-3-1 roles plus two flexible/alternate roles. Without `--include-flex`, ST is used as the lone striker, LAM/CAM/RAM are the three advanced midfielders, and CF and LM/W are omitted. Every requested slot retains its exact coordinate. Coordinates are the card's upper-left corner on the canvas.

## Live league mode

Obtain a football-data.org API token and expose it as an environment variable; do not put it in this repository:

```bash
export FOOTBALL_DATA_TOKEN='your-token'
python lineup.py --mode live --league PL --season 2025
```

Supported league codes: `PL` (Premier League), `PD` (La Liga), `BL1` (Bundesliga), `SA` (Serie A), and `FL1` (Ligue 1). `--season` is optional and is the season's starting year. The live client queries league standings and scorer data, then loads squad lists for up to six bottom-ranked clubs. Among players who fit a role, lower goal totals are used as a deliberately crude satirical tie-breaker. The API does not provide a universal weekly player-rating/"worst XI" feed, so the generated team is a squad-based selection rather than an official statistical weekly ranking. If standings cannot be read, the client falls back to the first six clubs returned by the competition endpoint.

If the token is absent, the API is rate-limited, the network/API fails, or no usable players are returned, live mode tries the configured local roster (`data/roster.csv` by default). To supply a different fallback file use `--roster path/to/roster.json`. Manual mode never calls the API.

## Roster formats

CSV columns: `name` (required), `position`, `id`/`player_id`, `club`, `club_code`, `image`, and `goals`. YAML and JSON accept a list of player objects or an object containing a `players` list. Unknown additional CSV columns are ignored. Example:

```csv
id,name,position,club,club_code,image,goals
101,Example Forward,ST,Example FC,EXFC,,7
102,Example Keeper,GK,Example FC,EXFC,,0
```

Positions accept common role names such as `Goalkeeper`, `Defender`, `Midfielder`, `Forward`, `GK`, `LB`, `CB`, `CDM`, `CAM`, `Winger`, `ST`, and the supplied slot names (`CDM-L`, `CB1`, etc.). Selection prefers matching positions and uses lower goal totals as a satirical tie-breaker; if a roster has no exact role fit, the best remaining available player fills that slot. Provide at least 11 distinct players for a normal XI (13 when using both flex slots).

## Satirical overrides

`overrides.json` maps real player IDs or case-insensitive names to display names. It also maps full club names to meme codes. Player-specific club codes can be set with `display_club_code`:

```json
{
  "players": {
    "Marcus Rashford": {"display_name": "RASHFORD"},
    "12345": {"display_name": "OFFSIDEMEN", "display_club_code": "MUN-CURSE"}
  },
  "clubs": {
    "Manchester United": "MANCURSE"
  }
}
```

A player override may also be a string, e.g. `"Marcus Rashford": "RASHFORD"`. Override paths are configurable with `--overrides path/to/overrides.json`.

## Image assets

- `assets/pitch_bg.png`: pitch background (any dimensions; fitted to 1080 × 1350).
- `assets/card_hexagon.png`: transparent card frame with a hexagon opening and nameplate (fitted to the card).
- `cutouts/<player-id>.png` or `cutouts/<player-name-slug>.png`: transparent player cutouts. The roster's `image` field may point to a file, either relative to `cutouts/` or project root.
- `crests/<club-code-slug>.png`: club crest; the slug is lower-case with punctuation replaced by underscores (e.g. `MUN` becomes `mun.png`).

Invalid or missing images do not stop rendering. A stylized silhouette appears in the hexagon and a colored badge is generated for missing club crests. To process images placed in `cutouts/raw/`, install the optional `rembg` package and run:

```bash
python -m pip install rembg
python lineup.py --mode manual --remove-backgrounds
```

The cutouts are written into `cutouts/` as transparent PNG files. This optional feature may download a rembg model on its first run.

## CLI reference

```text
python lineup.py [--mode manual|live] [--league PL|PD|BL1|SA|FL1]
                 [--season YEAR] [--roster FILE] [--output PNG]
                 [--root DIR] [--overrides JSON] [--include-flex]
                 [--remove-backgrounds] [--verbose]
```

Use `python lineup.py --help` for the full usage text. The application logic is self-contained in `lineup.py`; install Pillow and requests for rendering/API access, plus PyYAML for YAML roster files (all are listed in `requirements.txt`).
