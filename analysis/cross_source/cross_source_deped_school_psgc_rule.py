# The proposed #91 match rule as plain functions, so tests can run it on made-up units
# (tests/test_deped_school_psgc_rule.py). cross_source_deped_enrollment_psgc.py applies it to the
# real data. The logic lives here, and later in etl/04_integration/01_map_deped_school_psgc.sql;
# the rule_order in config/mappings/integration/deped_school_psgc.json describes it, and both must
# change together.
#
# A unit is anything with `id`, `name` and `level` (PSGC 2Q 2026). Every decision is
# (match_status, unit, match_method, match_detail), with unit and method None when not matched (D-029).

import collections

SULU_TIER = "code, Sulu region"


class Rule:
    def __init__(self, rules, sga, city_of, barangay_candidates, same_barangay_name):
        """rules: the JSON file; sga: school IDs of D-031; city_of: rolls a Manila sub-municipality
        up to the City of Manila; barangay_candidates: the barangays inside a city or municipality;
        same_barangay_name: True when a DepEd barangay name matches a PSGC barangay by the name tiers."""
        self.tier_method = rules["match_method_from_name_tier"]
        unreviewed = [o["deped_barangay"] for o in rules["overrides"] if not o.get("reviewer")]
        if unreviewed:
            raise ValueError(f"override without a reviewer in deped_school_psgc.json: {unreviewed}")
        self.overrides = {(o["level"], o["deped_province"], o["deped_municipality"], o["deped_barangay"]): o
                          for o in rules["overrides"]}
        self.sga = sga
        self.city_of = city_of
        self.barangay_candidates = barangay_candidates
        self.same_barangay_name = same_barangay_name
        self.override_hits = collections.Counter()

    def name_method(self, tier):
        if tier not in self.tier_method:
            raise ValueError(f"name tier {tier!r} has no match_method in deped_school_psgc.json; add it there first")
        return self.tier_method[tier]

    @staticmethod
    def code_method(tier, names_agree):
        if tier == SULU_TIER:
            return "code_region_moved"
        return "code" if names_agree else "code_name_differs"

    def override_method(self, o, c_unit, n_unit, c_tier, n_tier):
        """An override picks the unit, not the method: the method follows the side it uses, so `code`
        still means the names agree (D-029) and the rest are `code_name_differs`."""
        if o["use"] == "code":
            return self.code_method(c_tier, n_unit is not None and c_unit.id == n_unit.id)
        return self.name_method(n_tier)

    def decide_city(self, school, c_loc, c_tier, n_loc, n_tier, c_bgy):
        """The city or municipality. c_loc and n_loc are the localities the code and the name match
        found, before Manila's sub-municipalities roll up; c_bgy is the barangay the code gives."""
        school_id, _, province, municipality, barangay = school
        c_unit = self.city_of(c_loc) if c_loc else None
        n_unit = self.city_of(n_loc) if n_loc else None

        def by_code(names_agree, detail):
            if c_loc.level == "SubMun":
                return "matched", c_unit, "rollup", f"{detail}; Manila sub-municipality rolled up"
            return "matched", c_unit, self.code_method(c_tier, names_agree), detail

        def by_name(detail):
            if n_loc.level == "SubMun":
                return "matched", n_unit, "rollup", f"{detail}; Manila sub-municipality rolled up"
            return "matched", n_unit, self.name_method(n_tier), detail

        o = self.overrides.get(("city_mun", province, municipality, barangay))
        if o:
            self.override_hits["city_mun"] += 1
            unit = c_unit if o["use"] == "code" else n_unit
            if unit is None:
                return "unmatched", None, None, "reviewed override: no unit"
            return "matched", unit, self.override_method(o, c_unit, n_unit, c_tier, n_tier), "reviewed override"
        agree = c_unit is not None and n_unit is not None and c_unit.id == n_unit.id
        # The code's barangay supports the code's city only when it lies inside that city (profile O-7).
        bgy_supports_code = (c_unit is not None and c_bgy is not None
                             and c_bgy.id in {u.id for u in self.barangay_candidates(c_unit)}
                             and self.same_barangay_name(barangay, c_bgy))
        if school_id in self.sga:
            # D-031 excludes these schools until their barangays are matched to the Special Geographic
            # Area municipalities; the EMISD code does that when DepEd's barangay name agrees with it.
            if bgy_supports_code:
                return by_code(agree, "Special Geographic Area; DepEd barangay name matches the code's barangay")
            return "excluded", None, None, "Special Geographic Area (D-031)"
        if agree:
            return by_code(True, "code and name agree")
        if c_unit and n_unit:
            if bgy_supports_code:
                return by_code(False, "code; DepEd barangay name matches the code's barangay")
            return "ambiguous", None, None, "code and name differ"
        if c_unit:
            return by_code(False, "code only")
        if n_unit:
            return by_name(f"name only ({n_tier})")
        return "unmatched", None, None, "no code, no name match"

    def decide_barangay(self, school, city, c_unit, c_tier, n_unit, n_tier):
        """The barangay, given the city decision. c_unit and n_unit are the barangays the code and the
        name match found."""
        _, _, province, municipality, barangay = school
        city_status, city_unit = city[0], city[1]
        if city_status != "matched":
            return city_status, None, None, f"city or municipality {city_status}"
        o = self.overrides.get(("bgy", province, municipality, barangay))
        if o:
            self.override_hits["bgy"] += 1
            unit = c_unit if o["use"] == "code" else n_unit
            if unit is None:
                return "unmatched", None, None, "reviewed override: no unit"
            method, detail = self.override_method(o, c_unit, n_unit, c_tier, n_tier), "reviewed override"
        elif c_unit and n_unit and c_unit.id == n_unit.id:
            unit, method, detail = c_unit, self.code_method(c_tier, True), "code and name agree"
        elif c_unit and self.same_barangay_name(barangay, c_unit):
            unit, method, detail = c_unit, self.code_method(c_tier, True), "code; DepEd barangay name matches"
        elif c_unit and n_unit:
            return "ambiguous", None, None, "code and name differ"
        elif c_unit:
            unit, method, detail = c_unit, self.code_method(c_tier, False), "code only"
        elif n_unit:
            unit, method, detail = n_unit, self.name_method(n_tier), f"name only ({n_tier})"
        else:
            return "unmatched", None, None, "no code, no name match"
        if unit.id not in {u.id for u in self.barangay_candidates(city_unit)}:
            return "ambiguous", None, None, "barangay outside the accepted city or municipality"
        return "matched", unit, method, detail
