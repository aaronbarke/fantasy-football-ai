"""Opponent defensive-injury model.

When an offense faces a defense that has lost a key starter, the positions that
defender normally suppresses get easier. This module turns a list of an
opponent's *officially-absent starting defenders* into a small, caliber-scaled,
capped percentage bump for a given offensive player.

Two signals drive it, both from Sleeper's depth chart (see DepthChartEntry):

- **Role** (from ``position`` + ``depth_chart_position``): edge rusher, interior
  D-line, off-ball linebacker, perimeter corner, slot/nickel corner, or safety.
  Each role maps to the offensive positions it affects — an edge rusher out
  (Parsons / Garrett) helps the QB and passing game; an interior run-stuffer out
  (Quinnen Williams) helps the RB; an off-ball LB out (Fred Warner) helps the TE
  and receiving back; a boundary corner out helps outside WRs; a nickel out
  helps the slot.
- **Caliber**: we have NO free structured measure of defensive quality
  (Sleeper's search_rank tracks fantasy popularity, not impact — it ranks Sauce
  Gardner below journeymen), so caliber comes from a small hand-maintained tier
  list below. A replacement-level starter barely moves the number; a genuine
  game-wrecker moves it a bit more, which is the whole point. The list needs a
  light refresh each preseason — that is the honest cost of not having a metric.

Only ``depth_chart_order == 1`` starters are considered (our sole proxy for "this
guy matters"), and — like the teammate-injury model — only *confirmed* absences
(Out / Doubtful / IR), never Questionable. The point conversion and the overall
cap live in projection_service; this module stays in percentage space so it is
unit-testable on its own.
"""

# --- caliber tiers ----------------------------------------------------------
# Hand-maintained. Names are matched case-insensitively against a defender's
# full_name. Keep small and current; everyone not listed is a plain starter.
_WRECKERS = {
    # game-wreckers whose absence noticeably eases the matchup
    "micah parsons", "myles garrett", "t.j. watt", "tj watt", "nick bosa",
    "maxx crosby", "aidan hutchinson", "chris jones", "quinnen williams",
    "dexter lawrence", "christian gonzalez", "patrick surtain ii",
    "patrick surtain", "sauce gardner", "derek stingley jr.", "derek stingley",
    "fred warner", "roquan smith", "trent mcduffie", "jalen carter",
}
_STARS = {
    # very good starters — a step below wreckers
    "will anderson", "montez sweat", "brian burns", "danielle hunter",
    "rashan gary", "trey hendrickson", "josh hines-allen", "cameron heyward",
    "vita vea", "jeffery simmons", "denzel ward", "jaycee horn",
    "marlon humphrey", "jaire alexander", "devon witherspoon", "riq woolen",
    "fred warner ii", "zaire franklin", "bobby wagner", "antoine winfield jr.",
    "antoine winfield", "kyle hamilton", "budda baker", "minkah fitzpatrick",
    "nik bonitto", "kobie turner",
}

CALIBER_WRECKER = 3.0
CALIBER_STAR = 2.0
CALIBER_STARTER = 1.0


def caliber_multiplier(full_name: str | None) -> float:
    if not full_name:
        return CALIBER_STARTER
    n = full_name.strip().lower()
    if n in _WRECKERS:
        return CALIBER_WRECKER
    if n in _STARS:
        return CALIBER_STAR
    return CALIBER_STARTER


# --- role classification ----------------------------------------------------
_EDGE_SLOTS = {"LOLB", "ROLB", "RDE", "LDE"}
_INTERIOR_SLOTS = {"DT", "NT", "LDT", "RDT", "NG"}
_OFFBALL_SLOTS = {"MLB", "LILB", "RILB", "WLB", "SLB", "ILB", "MIKE", "WILL", "SAM"}
_PERIMETER_CB_SLOTS = {"LCB", "RCB", "CB"}
_SLOT_CB_SLOTS = {"NB", "NCB", "SCB"}
_SAFETY_SLOTS = {"SS", "FS", "S"}


def defender_role(position: str | None, slot: str | None) -> str | None:
    """Collapse (position, depth_chart_position) into one coverage/rush role."""
    pos = (position or "").upper()
    s = (slot or "").upper()
    if s in _SLOT_CB_SLOTS:
        return "slot_cb"
    if s in _PERIMETER_CB_SLOTS or pos == "CB":
        return "perimeter_cb"
    if s in _SAFETY_SLOTS or pos in ("S", "FS", "SS"):
        return "safety"
    if s in _INTERIOR_SLOTS or pos in ("DT", "NT"):
        return "interior"
    if s in _EDGE_SLOTS or pos == "DE":
        return "edge"
    if s in _OFFBALL_SLOTS or pos in ("LB", "ILB", "OLB"):
        # OLB is ambiguous (edge vs off-ball); the slot tags above catch true
        # edge OLBs, so anything left here is treated as off-ball coverage.
        return "offball_lb"
    return None


# role → {offensive position: effect weight}. Weight 1.0 is the role's primary
# victim; secondaries are partial. WR entries are resolved by alignment below.
_ROLE_EFFECTS: dict[str, dict[str, float]] = {
    "edge": {"QB": 1.0, "WR": 0.5, "TE": 0.4},            # clean pocket → passing
    "interior": {"RB": 1.0, "QB": 0.4},                   # blown-up run lanes
    "offball_lb": {"TE": 1.0, "RB": 0.6},                 # coverage + run fits
    "perimeter_cb": {"WR_PERIMETER": 1.0, "WR": 0.5},     # boundary receivers
    "slot_cb": {"WR_SLOT": 1.0, "TE": 0.3},               # slot receivers (+ some TE)
    "safety": {"WR": 0.4, "TE": 0.4, "QB": 0.3},          # deep shell
}

# Per-absent-starter base bump before caliber scaling (a plain starter out is a
# 2.5% nudge to his role's primary victim — deliberately small).
BASE_BUMP_PCT = 0.025


def _wr_effect_weight(effects: dict[str, float], alignment: str | None) -> float:
    """Resolve a corner's WR effect for a specific receiver's alignment.

    Perimeter corner out → boundary (LWR/RWR) WRs get the aligned weight, slot
    WRs only the generic residual; nickel out → the reverse. Unknown alignment
    splits the difference so we neither miss nor over-credit.
    """
    perimeter = effects.get("WR_PERIMETER", 0.0)
    slot = effects.get("WR_SLOT", 0.0)
    generic = effects.get("WR", 0.0)
    a = (alignment or "").upper()
    if a == "SWR":
        return max(slot, generic) if slot else generic
    if a in ("LWR", "RWR"):
        return max(perimeter, generic) if perimeter else generic
    # unknown alignment: half of whichever aligned effect this role carries
    return max(generic, 0.5 * (perimeter + slot))


def defense_injury_pct(
    off_position: str | None,
    off_alignment: str | None,
    out_defenders: list[dict],
) -> tuple[float, list[str]]:
    """Total percentage bump for an offensive player facing ``out_defenders``.

    ``out_defenders`` is the opponent's confirmed-out starting defenders, each a
    dict with ``name``, ``position`` and ``slot`` (depth_chart_position).
    Returns ``(pct, reasons)`` where pct is additive-in-percent (e.g. 0.05 = +5%)
    and reasons are human-readable contributors. ``(0.0, [])`` when nothing
    applies — so a healthy opponent defense leaves the projection untouched.
    """
    pos = (off_position or "").upper()
    if not out_defenders or pos not in ("QB", "RB", "WR", "TE"):
        return 0.0, []

    pct = 0.0
    reasons: list[str] = []
    for d in out_defenders:
        role = defender_role(d.get("position"), d.get("slot"))
        if role is None:
            continue
        effects = _ROLE_EFFECTS.get(role, {})
        if pos == "WR":
            weight = _wr_effect_weight(effects, off_alignment)
        else:
            weight = effects.get(pos, 0.0)
        if weight <= 0:
            continue
        mult = caliber_multiplier(d.get("name"))
        contrib = BASE_BUMP_PCT * mult * weight
        if contrib <= 0:
            continue
        pct += contrib
        reasons.append(f"{d['name']} ({d.get('status') or 'Out'})")
    return pct, reasons
