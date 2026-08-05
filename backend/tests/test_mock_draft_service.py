import random
from collections import Counter

from app.services.mock_draft_service import (
    MAX_PER_POSITION,
    bot_pick,
    grade,
    simulate_until_user,
    snake_slot,
    user_pick_numbers,
)


def _player(pid, name, position, adp, vor=0.0, stdev=5.0, **extra):
    return {
        "player_id": pid,
        "name": name,
        "position": position,
        "adp": adp,
        "adp_stdev": stdev,
        "vor": vor,
        "overall_rank": extra.pop("overall_rank", None),
        "adp_delta": extra.pop("adp_delta", None),
        "value_score": extra.pop("value_score", 0.0),
        **extra,
    }


def _pool(n=200):
    """A synthetic board: ADP ascending, VOR descending, positions cycling."""
    positions = ["RB", "WR", "QB", "TE", "WR", "RB"]
    pool = []
    for i in range(n):
        position = positions[i % len(positions)]
        pool.append(
            _player(
                f"p{i}",
                f"Player {i}",
                position,
                adp=float(i + 1),
                vor=max(0.0, 200.0 - i * 1.5),
                overall_rank=i + 1,
                adp_delta=0,
            )
        )
    # A couple of kickers and defenses, late like the real thing
    for i in range(6):
        pool.append(_player(f"k{i}", f"Kicker {i}", "K", adp=150.0 + i))
        pool.append(_player(f"d{i}", f"Defense {i}", "DEF", adp=160.0 + i))
    pool.sort(key=lambda p: p["adp"])
    return pool


class TestSnakeSlot:
    def test_first_round_runs_forward(self):
        assert [snake_slot(p, 12)[1] for p in range(1, 13)] == list(range(1, 13))

    def test_second_round_reverses(self):
        assert [snake_slot(p, 12)[1] for p in range(13, 25)] == list(range(12, 0, -1))

    def test_round_numbers(self):
        assert snake_slot(1, 12)[0] == 1
        assert snake_slot(12, 12)[0] == 1
        assert snake_slot(13, 12)[0] == 2
        assert snake_slot(25, 12)[0] == 3

    def test_turn_of_the_snake_is_back_to_back(self):
        # Slot 12 picks last in round 1 and first in round 2.
        assert snake_slot(12, 12)[1] == 12
        assert snake_slot(13, 12)[1] == 12


class TestUserPickNumbers:
    def test_matches_the_snake(self):
        picks = user_pick_numbers(12, 5, 4)
        assert picks == [5, 20, 29, 44]

    def test_every_round_gets_exactly_one_pick(self):
        assert len(user_pick_numbers(10, 3, 15)) == 15

    def test_slots_never_collide(self):
        seen: set[int] = set()
        for slot in range(1, 13):
            picks = set(user_pick_numbers(12, slot, 15))
            assert not (picks & seen)
            seen |= picks
        assert len(seen) == 12 * 15


class TestBotPick:
    def test_drafts_near_the_top_of_the_board(self):
        rng = random.Random(1)
        pool = _pool()
        chosen = bot_pick(pool, set(), Counter(), {}, rng)
        assert chosen["adp"] <= 20  # noise moves it, but not to round 10

    def test_respects_roster_caps(self):
        rng = random.Random(2)
        pool = [_player(f"q{i}", f"QB {i}", "QB", adp=float(i + 1)) for i in range(10)]
        roster = Counter({"QB": MAX_PER_POSITION["QB"]})
        assert bot_pick(pool, set(), roster, {}, rng) is None

    def test_skips_players_already_taken(self):
        rng = random.Random(3)
        pool = _pool(30)
        taken = {p["player_id"] for p in pool[:25]}
        chosen = bot_pick(pool, taken, Counter(), {}, rng)
        assert chosen is not None
        assert chosen["player_id"] not in taken

    def test_need_pulls_a_position_forward(self):
        # Same seed, same pool — only the stated need differs.
        pool = [
            _player("a", "Early RB", "RB", adp=1.0, stdev=0.1),
            _player("b", "Later TE", "TE", adp=9.0, stdev=0.1),
        ]
        no_need = bot_pick(pool, set(), Counter(), {}, random.Random(7))
        with_need = bot_pick(pool, set(), Counter(), {"TE": 1}, random.Random(7))
        assert no_need["player_id"] == "a"
        assert with_need["player_id"] == "b"

    def test_volatile_players_move_more_than_consensus_ones(self):
        steady = _player("s", "Steady", "RB", adp=20.0, stdev=0.5)
        volatile = _player("v", "Volatile", "WR", adp=20.0, stdev=25.0)
        pool = [steady, volatile]
        picks = [
            bot_pick(pool, set(), Counter(), {}, random.Random(i))["player_id"]
            for i in range(40)
        ]
        # With identical ADP, the wide-spread player should sometimes win and
        # sometimes lose — i.e. the draft isn't deterministic.
        assert 0 < picks.count("v") < 40


class TestSimulateUntilUser:
    def test_stops_on_the_user_turn(self):
        made = simulate_until_user(_pool(), [], 12, 15, 5, random.Random(1))
        assert len(made) == 4  # picks 1-4, then it's slot 5's turn
        assert [m["team_slot"] for m in made] == [1, 2, 3, 4]

    def test_user_on_the_first_pick_means_no_bots_run(self):
        assert simulate_until_user(_pool(), [], 12, 15, 1, random.Random(1)) == []

    def test_never_repeats_a_player(self):
        pool = _pool(220)
        picks: list[dict] = []
        rng = random.Random(5)
        for _ in range(200):
            made = simulate_until_user(pool, picks, 12, 15, 5, rng)
            picks += made
            if len(picks) >= 12 * 15:
                break
            # Stand in for the user so the draft can proceed
            taken = {p["player_id"] for p in picks}
            nxt = next(p for p in pool if p["player_id"] not in taken)
            overall = len(picks) + 1
            rnd, slot = snake_slot(overall, 12)
            picks.append(
                {
                    "overall_pick": overall,
                    "round": rnd,
                    "team_slot": slot,
                    "player_id": nxt["player_id"],
                    "position": nxt["position"],
                    "is_user": True,
                    "snapshot": nxt,
                }
            )
        ids = [p["player_id"] for p in picks]
        assert len(ids) == len(set(ids))

    def test_terminates_and_fills_the_draft(self):
        pool = _pool(220)
        picks: list[dict] = []
        rng = random.Random(9)
        for _ in range(500):
            made = simulate_until_user(pool, picks, 12, 15, 1, rng)
            picks += made
            if len(picks) >= 12 * 15:
                break
            taken = {p["player_id"] for p in picks}
            nxt = next(p for p in pool if p["player_id"] not in taken)
            overall = len(picks) + 1
            rnd, slot = snake_slot(overall, 12)
            picks.append(
                {
                    "overall_pick": overall,
                    "round": rnd,
                    "team_slot": slot,
                    "player_id": nxt["player_id"],
                    "position": nxt["position"],
                    "is_user": True,
                    "snapshot": nxt,
                }
            )
        assert len(picks) == 12 * 15
        assert [p["overall_pick"] for p in picks] == list(range(1, 181))

    def test_bots_never_exceed_roster_caps(self):
        pool = _pool(220)
        picks: list[dict] = []
        rng = random.Random(11)
        for _ in range(500):
            made = simulate_until_user(pool, picks, 12, 15, 1, rng)
            picks += made
            if len(picks) >= 12 * 15:
                break
            taken = {p["player_id"] for p in picks}
            nxt = next(p for p in pool if p["player_id"] not in taken)
            overall = len(picks) + 1
            rnd, slot = snake_slot(overall, 12)
            picks.append(
                {
                    "overall_pick": overall,
                    "round": rnd,
                    "team_slot": slot,
                    "player_id": nxt["player_id"],
                    "position": nxt["position"],
                    "is_user": True,
                    "snapshot": nxt,
                }
            )
        for slot in range(2, 13):  # slot 1 is our stand-in user, not a bot
            counts = Counter(p["position"] for p in picks if p["team_slot"] == slot)
            for position, n in counts.items():
                assert n <= MAX_PER_POSITION.get(position, 6)


class TestGrade:
    def _picks(self):
        return [
            {"team_slot": 1, "snapshot": _player("a", "A", "RB", 1.0, vor=100.0,
                                                 overall_rank=1, adp_delta=5,
                                                 value_score=20.0)},
            {"team_slot": 1, "snapshot": _player("b", "B", "WR", 2.0, vor=-30.0,
                                                 overall_rank=90, adp_delta=-5,
                                                 value_score=-8.0)},
            {"team_slot": 2, "snapshot": _player("c", "C", "K", 150.0, vor=0.0)},
            {"team_slot": 2, "snapshot": _player("d", "D", "TE", 3.0, vor=40.0,
                                                 overall_rank=20, adp_delta=1,
                                                 value_score=2.0)},
        ]

    def test_negative_picks_do_not_subtract(self):
        # A -30 sleeper must not score worse than an empty roster spot.
        result = grade(self._picks(), teams=2, my_slot=1)
        assert result["your_total_vor"] == 100.0

    def test_ranks_teams_by_captured_value(self):
        result = grade(self._picks(), teams=2, my_slot=1)
        assert result["your_rank"] == 1
        assert result["standings"][0]["team_slot"] == 1
        assert result["standings"][0]["is_you"] is True

    def test_best_and_worst_come_from_rated_players_only(self):
        result = grade(self._picks(), teams=2, my_slot=2)
        # Team 2 holds a kicker and a TE; only the TE is rated.
        assert result["best_pick"]["name"] == "D"
        assert result["worst_pick"]["name"] == "D"

    def test_empty_roster_has_no_best_pick(self):
        result = grade(
            [{"team_slot": 2, "snapshot": _player("c", "C", "K", 150.0)}],
            teams=2,
            my_slot=1,
        )
        assert result["best_pick"] is None
        assert result["your_total_vor"] == 0.0
