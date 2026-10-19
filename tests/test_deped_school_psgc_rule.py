"""The proposed #91 DepEd school-to-PSGC rule on made-up units (analysis/cross_source/cross_source_deped_school_psgc_rule.py)."""

import json
from dataclasses import dataclass

import pytest

from analysis.cross_source.cross_source_deped_school_psgc_rule import Rule


@dataclass(frozen=True)
class Unit:
    id: str
    name: str
    level: str


MANILA = Unit("1380600000", "City of Manila", "City")
SAMPALOC = Unit("1380608000", "Sampaloc", "SubMun")
BAY = Unit("0403402000", "Bay", "Mun")
LOS_BANOS = Unit("0403411000", "Los Baños", "Mun")
SGA_MUN = Unit("1999901000", "Pahamuddin", "Mun")
SGA_MUN_2 = Unit("1999904000", "Nabalawag", "Mun")
PIKIT = Unit("1204714000", "Pikit", "Mun")
SULU_MUN = Unit("0906601000", "Jolo", "Mun")
TAGUIG = Unit("1381500000", "City of Taguig", "City")
UNITS = [MANILA, SAMPALOC, BAY, LOS_BANOS, SGA_MUN, SGA_MUN_2, PIKIT, SULU_MUN, TAGUIG]

BGY_SAMPALOC = Unit("1380608001", "Barangay 395", "Bgy")
BGY_BAY = Unit("0403402001", "Bitin", "Bgy")
BGY_BAY_2 = Unit("0403402002", "Calo", "Bgy")
BGY_LOS_BANOS = Unit("0403411001", "Anos", "Bgy")
BGY_SGA = Unit("1999901001", "Buliok", "Bgy")
BGY_SGA_2 = Unit("1999904001", "Damatulan", "Bgy")
BGY_PIKIT = Unit("1204714001", "Ginatilan", "Bgy")
BGY_JOLO = Unit("0906601001", "Asturias", "Bgy")
BGY_NORTH_SIGNAL = Unit("1381500001", "North Signal Village", "Bgy")
BGY_CENTRAL_SIGNAL = Unit("1381500002", "Central Signal Village", "Bgy")
BARANGAYS = [BGY_SAMPALOC, BGY_BAY, BGY_BAY_2, BGY_LOS_BANOS, BGY_SGA, BGY_SGA_2, BGY_PIKIT, BGY_JOLO,
             BGY_NORTH_SIGNAL, BGY_CENTRAL_SIGNAL]

SGA_SCHOOL = "100001"


def city_of(unit):
    return MANILA if unit.level == "SubMun" else unit


def barangay_candidates(city):
    prefix = city.id[:5] if city.id.startswith("13806") else city.id[:7]
    return [b for b in BARANGAYS if b.id.startswith(prefix)]


def same_barangay_name(deped_barangay, unit):
    return unit is not None and deped_barangay.casefold() == unit.name.casefold()


@pytest.fixture
def rules(repo_root):
    return json.loads((repo_root / "config/mappings/integration/deped_school_psgc.json").read_text(encoding="utf-8"))


@pytest.fixture
def rule(rules):
    return Rule(rules, {SGA_SCHOOL}, city_of, barangay_candidates, same_barangay_name)


def school(barangay, school_id="200001", province="LAGUNA", municipality="BAY"):
    return (school_id, "REGION IV-A", province, municipality, barangay)


def decide(rule, s, c_loc, n_loc, c_bgy, n_bgy, c_tier="code", n_tier="exact"):
    city = rule.decide_city(s, c_loc, c_tier, n_loc, n_tier, c_bgy)
    return city, rule.decide_barangay(s, city, c_bgy, c_tier, n_bgy, n_tier)


def test_code_and_name_agree_is_code(rule):
    city, bgy = decide(rule, school("Bitin"), BAY, BAY, BGY_BAY, BGY_BAY)
    assert city[:3] == ("matched", BAY, "code")
    assert bgy[:3] == ("matched", BGY_BAY, "code")


def test_code_wins_a_disagreement_only_when_the_deped_barangay_supports_it(rule):
    supported, _ = decide(rule, school("Anos"), LOS_BANOS, BAY, BGY_LOS_BANOS, None)
    assert supported[:3] == ("matched", LOS_BANOS, "code_name_differs")
    unsupported, bgy = decide(rule, school("Bitin"), LOS_BANOS, BAY, BGY_LOS_BANOS, BGY_BAY)
    assert unsupported == ("ambiguous", None, None, "code and name differ")
    assert bgy == ("ambiguous", None, None, "city or municipality ambiguous")


def test_code_only_is_code_name_differs_and_name_only_uses_the_tier(rule):
    city, bgy = decide(rule, school("Calo"), BAY, None, BGY_BAY_2, None)
    assert city[2] == "code_name_differs" and bgy[:3] == ("matched", BGY_BAY_2, "code")
    city, bgy = decide(rule, school("Kalo"), None, BAY, None, BGY_BAY_2, n_tier="folded")
    assert city[:3] == ("matched", BAY, "name_normalized") and bgy[2] == "name_normalized"


def test_unmatched_when_neither_is_found(rule):
    city, bgy = decide(rule, school("Nowhere"), None, None, None, None)
    assert city == ("unmatched", None, None, "no code, no name match")
    assert bgy == ("unmatched", None, None, "city or municipality unmatched")


def test_manila_sub_municipality_is_rollup(rule):
    s = school("Barangay 395", province="NCR, CITY OF MANILA, FIRST DISTRICT", municipality="SAMPALOC")
    city, bgy = decide(rule, s, SAMPALOC, SAMPALOC, BGY_SAMPALOC, BGY_SAMPALOC)
    assert city[:3] == ("matched", MANILA, "rollup")
    assert bgy[:3] == ("matched", BGY_SAMPALOC, "code")
    by_name, _ = decide(rule, s, None, SAMPALOC, None, BGY_SAMPALOC)
    assert by_name[:3] == ("matched", MANILA, "rollup")


def test_sulu_region_code_is_code_region_moved(rule):
    city, bgy = decide(rule, school("Asturias", province="SULU", municipality="JOLO"), SULU_MUN, SULU_MUN, BGY_JOLO,
                       BGY_JOLO, c_tier="code, Sulu region")
    assert city[2] == "code_region_moved" and bgy[2] == "code_region_moved"


def test_special_geographic_area_matched_by_code_when_the_barangay_agrees(rule):
    s = school("Buliok", school_id=SGA_SCHOOL, province="NORTH COTABATO", municipality="PIKIT")
    city, bgy = decide(rule, s, SGA_MUN, PIKIT, BGY_SGA, BGY_PIKIT)
    assert city[:3] == ("matched", SGA_MUN, "code_name_differs")
    assert bgy[:3] == ("matched", BGY_SGA, "code")


def test_special_geographic_area_otherwise_excluded_with_no_code(rule):
    s = school("Ginatilan", school_id=SGA_SCHOOL, province="NORTH COTABATO", municipality="PIKIT")
    city, bgy = decide(rule, s, SGA_MUN, PIKIT, BGY_SGA, BGY_PIKIT)
    assert city == ("excluded", None, None, "Special Geographic Area (D-031)")
    assert bgy == ("excluded", None, None, "city or municipality excluded")


def test_code_barangay_in_another_municipality_does_not_support_the_code(rule):
    # School 207519: the city code is one SGA municipality, the barangay code is in another.
    s = school("Damatulan", school_id=SGA_SCHOOL, province="NORTH COTABATO", municipality="PIKIT")
    city, bgy = decide(rule, s, SGA_MUN, PIKIT, BGY_SGA_2, None)
    assert city == ("excluded", None, None, "Special Geographic Area (D-031)")
    assert bgy == ("excluded", None, None, "city or municipality excluded")
    city, _ = decide(rule, school("Calo"), LOS_BANOS, BAY, BGY_BAY_2, None)
    assert city == ("ambiguous", None, None, "code and name differ")


def test_barangay_outside_the_accepted_city_is_ambiguous(rule):
    _, bgy = decide(rule, school("Anos"), BAY, BAY, BGY_LOS_BANOS, None)
    assert bgy == ("ambiguous", None, None, "barangay outside the accepted city or municipality")


def test_signal_village_override_uses_the_code(rule):
    s = school("SIGNAL VILLAGE", province="NCR FOURTH DISTRICT", municipality="TAGUIG CITY")
    city, bgy = decide(rule, s, TAGUIG, TAGUIG, BGY_NORTH_SIGNAL, BGY_CENTRAL_SIGNAL, n_tier="old name")
    assert bgy == ("matched", BGY_NORTH_SIGNAL, "code_name_differs", "reviewed override")
    assert rule.override_hits == {"bgy": 1}


def test_signal_village_override_is_code_when_the_name_match_agrees(rule):
    s = school("SIGNAL VILLAGE", province="NCR FOURTH DISTRICT", municipality="TAGUIG CITY")
    _, bgy = decide(rule, s, TAGUIG, TAGUIG, BGY_CENTRAL_SIGNAL, BGY_CENTRAL_SIGNAL, n_tier="old name")
    assert bgy == ("matched", BGY_CENTRAL_SIGNAL, "code", "reviewed override")


def test_override_still_needs_a_barangay_inside_the_city(rule):
    s = school("SIGNAL VILLAGE", province="NCR FOURTH DISTRICT", municipality="TAGUIG CITY")
    _, bgy = decide(rule, s, TAGUIG, TAGUIG, BGY_BAY, BGY_CENTRAL_SIGNAL, n_tier="old name")
    assert bgy == ("ambiguous", None, None, "barangay outside the accepted city or municipality")


def test_override_without_a_reviewer_fails(rules):
    rules["overrides"][0]["reviewer"] = None
    with pytest.raises(ValueError, match="without a reviewer"):
        Rule(rules, {SGA_SCHOOL}, city_of, barangay_candidates, same_barangay_name)


def test_unknown_name_tier_fails(rule):
    with pytest.raises(ValueError, match="new tier"):
        decide(rule, school("Calo"), None, BAY, None, BGY_BAY_2, n_tier="new tier")


def test_every_rule_method_is_a_d029_value(rules, repo_root):
    decisions = (repo_root / "docs/governance/decisions.md").read_text(encoding="utf-8")
    d029 = decisions[decisions.index("## D-029"):decisions.index("## D-030")]
    methods = set(rules["match_method_from_name_tier"].values())
    methods |= {"code", "code_name_differs", "code_region_moved", "rollup"}
    missing = sorted(m for m in methods if f"| `{m}` |" not in d029)
    assert not missing, f"match_method values not in D-029: {missing}"
