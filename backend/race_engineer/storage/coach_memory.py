"""Persistent, local coaching memory. It lives in the EXISTING catalog database (migration 5): no second database.

* ``coach_tips``   - every instruction given, with its lifecycle: nuovo -> mostrato -> applicato | da_rivalutare | non_verificabile,
                     and the measured outcome of the following laps.
* ``coach_habits`` - per track/vehicle/corner/finding: how often it was seen (separates a habit from an occasional mistake).
* ``coach_laps``   - the end-of-lap review of each lap (progress over time).
Real and synthetic data are kept apart (``synthetic`` column) exactly like the personal references.
Callers serialise access (the LiveEngineer lock): the catalog connection is shared.
"""
from __future__ import annotations

import json
import time

OPEN = ("nuovo", "mostrato")
CLOSED = ("applicato", "da_rivalutare", "non_verificabile")
DEFAULT_PREFS = {"min_confidence": "bassa", "verbosity": "normale", "show_review_s": 25, "max_tips_per_corner": 1}
LEVELS = {"bassa": 0, "media": 1, "alta": 2}
HABIT_MIN_LAPS = 3
HABIT_MIN_RATIO = 0.5


class CoachMemory:
    def __init__(self, catalog, clock=time.time):
        self.cat, self.clock = catalog, clock
        self.db = catalog.db

    # ------------------------------------------------------------------ preferences (existing settings table)
    def prefs(self) -> dict:
        if getattr(self, "_prefs", None) is None:
            p = dict(DEFAULT_PREFS)
            p.update(self.cat.get_setting("coach_prefs", {}) or {})
            self._prefs = p
        return dict(self._prefs)

    def set_prefs(self, new: dict) -> dict:
        p = self.prefs()
        for k, v in (new or {}).items():
            if k == "min_confidence" and v in LEVELS:
                p[k] = v
            elif k == "verbosity" and v in ("breve", "normale"):
                p[k] = v
            elif k == "show_review_s" and isinstance(v, (int, float)) and 5 <= v <= 120:
                p[k] = float(v)
            elif k == "max_tips_per_corner" and isinstance(v, int) and 1 <= v <= 3:
                p[k] = v
        self.cat.put_setting("coach_prefs", p)
        self._prefs = p
        return dict(p)

    # ------------------------------------------------------------------ tips
    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["instruction"] = json.loads(d.pop("instruction_json"))
        return d

    def new_tip(self, *, session_id, track, vehicle, synthetic, corner, type_, lap, confidence, impact_s, mag, instruction) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO coach_tips(created_at,session_id,track,vehicle,synthetic,corner,type,key,lap_issued,confidence,impact_before_s,mag_before,"
                "instruction_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'nuovo')",
                (self.clock(), session_id, track or "", vehicle or "", int(synthetic), corner, type_, f"{corner}.{type_}", lap, confidence, impact_s, mag,
                 json.dumps(instruction, ensure_ascii=False)))
        return cur.lastrowid

    def update_instruction(self, tip_id: int, instruction: dict) -> None:
        with self.db:
            self.db.execute("UPDATE coach_tips SET instruction_json=? WHERE id=?", (json.dumps(instruction, ensure_ascii=False), tip_id))

    def tip(self, tip_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM coach_tips WHERE id=?", (tip_id,)).fetchone()
        return self._row(r) if r else None

    def open_tips(self, track, vehicle, synthetic) -> list[dict]:
        rows = self.db.execute("SELECT * FROM coach_tips WHERE track=? AND vehicle=? AND synthetic=? AND status IN ('nuovo','mostrato') ORDER BY id",
                               (track or "", vehicle or "", int(synthetic))).fetchall()
        return [self._row(r) for r in rows]

    def last_tip(self, track, vehicle, synthetic, key) -> dict | None:
        r = self.db.execute("SELECT * FROM coach_tips WHERE track=? AND vehicle=? AND synthetic=? AND key=? ORDER BY id DESC LIMIT 1",
                            (track or "", vehicle or "", int(synthetic), key)).fetchone()
        return self._row(r) if r else None

    def recent_tips(self, track, vehicle, synthetic, limit=30) -> list[dict]:
        rows = self.db.execute("SELECT * FROM coach_tips WHERE track=? AND vehicle=? AND synthetic=? ORDER BY id DESC LIMIT ?",
                               (track or "", vehicle or "", int(synthetic), limit)).fetchall()
        return [self._row(r) for r in rows]

    def mark_shown(self, tip_id: int, lap: int | None) -> None:
        with self.db:
            self.db.execute("UPDATE coach_tips SET status='mostrato', shown_at=COALESCE(shown_at,?), shown_lap=COALESCE(shown_lap,?) "
                            "WHERE id=? AND status IN ('nuovo','mostrato')", (self.clock(), lap, tip_id))

    def evaluate(self, tip_id: int, *, status: str, outcome: str | None, lap: int, impact_after: float | None, count: bool = True,
                 skipped: bool = False, new_impact_before: float | None = None, new_mag: float | None = None) -> None:
        closing = status in CLOSED
        with self.db:
            self.db.execute(
                "UPDATE coach_tips SET status=?, outcome=?, evaluated_lap=?, impact_after_s=?, evaluations=evaluations+?, skipped=skipped+?, "
                "closed_at=CASE WHEN ? THEN ? ELSE closed_at END, impact_before_s=COALESCE(?,impact_before_s), mag_before=COALESCE(?,mag_before) WHERE id=?",
                (status, outcome, lap, impact_after, 1 if count else 0, 1 if skipped else 0, int(closing), self.clock(), new_impact_before, new_mag, tip_id))

    # ------------------------------------------------------------------ habits
    def seen(self, track, vehicle, synthetic, session_id, corner, type_, impact_s) -> None:
        key = (track or "", vehicle or "", int(synthetic), corner, type_)
        r = self.db.execute("SELECT last_session_id FROM coach_habits WHERE track=? AND vehicle=? AND synthetic=? AND corner=? AND type=?", key).fetchone()
        now = self.clock()
        with self.db:
            if r is None:
                self.db.execute("INSERT INTO coach_habits VALUES (?,?,?,?,?,1,?,?,?,?,1,NULL)", (*key, float(impact_s or 0.0), now, now, session_id))
            else:
                self.db.execute("UPDATE coach_habits SET laps_seen=laps_seen+1, total_impact_s=total_impact_s+?, last_seen=?, last_session_id=?, "
                                "sessions=sessions+?, fixed_at=NULL WHERE track=? AND vehicle=? AND synthetic=? AND corner=? AND type=?",
                                (float(impact_s or 0.0), now, session_id, 0 if r["last_session_id"] == session_id else 1, *key))

    def mark_fixed(self, track, vehicle, synthetic, corner, type_) -> None:
        with self.db:
            self.db.execute("UPDATE coach_habits SET fixed_at=? WHERE track=? AND vehicle=? AND synthetic=? AND corner=? AND type=?",
                            (self.clock(), track or "", vehicle or "", int(synthetic), corner, type_))

    def laps_analysed(self, track, vehicle, synthetic) -> int:
        return self.db.execute("SELECT COUNT(*) FROM coach_laps WHERE track=? AND vehicle=? AND synthetic=?", (track or "", vehicle or "", int(synthetic))).fetchone()[0]

    def habit(self, track, vehicle, synthetic, corner, type_) -> dict:
        r = self.db.execute("SELECT * FROM coach_habits WHERE track=? AND vehicle=? AND synthetic=? AND corner=? AND type=?",
                            (track or "", vehicle or "", int(synthetic), corner, type_)).fetchone()
        n = max(1, self.laps_analysed(track, vehicle, synthetic))
        if r is None:
            return {"classification": "nuovo", "laps_seen": 0, "laps_analysed": n}
        seen, ratio = r["laps_seen"], r["laps_seen"] / n
        cls = "corretto" if r["fixed_at"] else "abitudine" if seen >= HABIT_MIN_LAPS and ratio >= HABIT_MIN_RATIO else "occasionale"
        return {"classification": cls, "laps_seen": seen, "laps_analysed": n, "sessions": r["sessions"], "avg_impact_s": round(r["total_impact_s"] / max(1, seen), 3)}

    def habits(self, track, vehicle, synthetic) -> list[dict]:
        rows = self.db.execute("SELECT corner,type FROM coach_habits WHERE track=? AND vehicle=? AND synthetic=?", (track or "", vehicle or "", int(synthetic))).fetchall()
        out = [{"corner": r["corner"], "type": r["type"], **self.habit(track, vehicle, synthetic, r["corner"], r["type"])} for r in rows]
        out.sort(key=lambda h: (-(h["classification"] == "abitudine"), -h["laps_seen"]))
        return out

    # ------------------------------------------------------------------ laps / progress
    def save_lap(self, session_id, lap, track, vehicle, synthetic, time_s, delta_best_s, findings, review: dict) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO coach_laps VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (session_id, lap, track or "", vehicle or "", int(synthetic), self.clock(), time_s, delta_best_s, findings,
                             json.dumps(review, ensure_ascii=False)))

    def progress(self, track, vehicle, synthetic, limit=200) -> list[dict]:
        rows = self.db.execute("SELECT session_id,lap,created_at,time_s,delta_best_s,findings FROM coach_laps WHERE track=? AND vehicle=? AND synthetic=? "
                               "ORDER BY created_at DESC LIMIT ?", (track or "", vehicle or "", int(synthetic), limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def review(self, session_id, lap) -> dict | None:
        r = self.db.execute("SELECT review_json FROM coach_laps WHERE session_id=? AND lap=?", (session_id, lap)).fetchone()
        return json.loads(r[0]) if r else None

    # ------------------------------------------------------------------ overview for the dashboard / report
    def summary(self, track, vehicle, synthetic) -> dict:
        tips = self.recent_tips(track, vehicle, synthetic, 200)
        by_status: dict[str, int] = {}
        for t in tips:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        hb = self.habits(track, vehicle, synthetic)
        prog = self.progress(track, vehicle, synthetic, 50)
        best = [p["time_s"] for p in prog if p["time_s"]]
        return {"track": track, "vehicle": vehicle, "synthetic": bool(synthetic), "tips_by_status": by_status,
                "recurring": [h for h in hb if h["classification"] == "abitudine"][:8], "occasional": [h for h in hb if h["classification"] == "occasionale"][:8],
                "corrected": [h for h in hb if h["classification"] == "corretto"][:8],
                "laps_analysed": self.laps_analysed(track, vehicle, synthetic), "best_lap_s": min(best) if best else None,
                "recent_tips": [{k: t[k] for k in ("id", "key", "status", "outcome", "lap_issued", "evaluated_lap", "impact_before_s", "impact_after_s", "evaluations")}
                                | {"headline": t["instruction"].get("headline"), "corner_label": t["instruction"].get("corner_label")} for t in tips[:15]],
                "prefs": self.prefs()}
