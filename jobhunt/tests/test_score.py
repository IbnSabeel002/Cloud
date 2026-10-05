import copy
import unittest
from datetime import date

from jobhunt.profile import DEFAULT_PROFILE, load_profile
from jobhunt.salary import parse_pay
from jobhunt.score import (
    dedupe_candidates, evaluate, format_pay, freshness_points, seniority_points,
    skill_points, tier_for, title_points, validate_candidate,
)

TODAY = date(2026, 10, 5)
RICH_JD = (
    "You will produce short-form video with Kling and Veo, build workflows in ComfyUI, "
    "prompt Midjourney, run Meta Ads campaigns, design in Canva and report in Google Analytics. "
    "Own the content calendar for Instagram and TikTok across our brands."
)


def cand(**kw):
    base = {
        "source": "indeed", "title": "Creative AI Specialist", "company": "Acme Studio",
        "location": "Dubai", "url": "https://example.com/job/1", "posted": "Posted on: October 02, 2026",
        "pay_text": "AED 12,000 - 15,000 a month", "pay_source": "listing", "level_label": None,
        "years_required": 4, "languages_required": ["English"], "job_type": "full-time",
        "apply_method": "portal", "apply_email": None, "scope_items": ["ai video"],
        "gender_restricted": False, "visa_info": "sponsored", "description": RICH_JD,
    }
    base.update(kw)
    return base


def ev(**kw):
    return evaluate(cand(**kw), DEFAULT_PROFILE, TODAY)


class TitlePointTests(unittest.TestCase):
    def pts(self, title, desc=""):
        return title_points(title, desc, DEFAULT_PROFILE)[0]

    def test_tiers_of_title_fit(self):
        self.assertEqual(self.pts("Creative AI Specialist"), 30)
        self.assertEqual(self.pts("Senior Social Media Manager"), 24)
        self.assertEqual(self.pts("Marketing Operations Manager"), 22)
        self.assertEqual(self.pts("Digital Transformation Lead"), 22)
        # Seen in live Dubai results: automation-flavoured AI titles must not score zero.
        self.assertEqual(self.pts("AI & Automation Specialist"), 22)
        self.assertEqual(self.pts("Senior Agentic AI Solutions Specialist"), 22)
        self.assertEqual(self.pts("Generative AI Software Engineer & Digital Marketing Specialist | AI Automation"), 30)
        self.assertEqual(self.pts("Creative Director"), 16)
        self.assertEqual(self.pts("Content Creator"), 10)
        self.assertEqual(self.pts("Off-Page SEO Specialist - Links, Placements & Media"), 0)

    def test_hyphen_and_case_insensitive(self):
        self.assertEqual(self.pts("AI-Content Lead"), 30)
        self.assertEqual(self.pts("GENERATIVE AI PRODUCER"), 30)

    def test_ai_must_be_a_word(self):
        # "ai" inside another word must not count as an AI role.
        self.assertEqual(self.pts("Retail Social Media Specialist"), 16)
        self.assertEqual(self.pts("Chair Manager"), 0)

    def test_ai_in_jd_lifts_a_social_role(self):
        plain = self.pts("Social Media Manager", "Manage our Instagram.")
        lifted = self.pts("Social Media Manager", "Use AI tools. Our AI workflow is core to the role.")
        self.assertEqual(plain, 24)
        self.assertEqual(lifted, 28)

    def test_lift_is_capped_at_30(self):
        self.assertEqual(self.pts("Creative AI Specialist", "AI AI AI generative"), 30)


class SkillPointTests(unittest.TestCase):
    def test_short_jd_is_neutral_and_flagged(self):
        pts, hits, missing = skill_points("Creative AI Specialist", "Great role.", DEFAULT_PROFILE)
        self.assertEqual((pts, hits, missing), (8, [], True))

    def test_five_hits_max_out(self):
        pts, hits, missing = skill_points("x", RICH_JD, DEFAULT_PROFILE)
        self.assertFalse(missing)
        self.assertEqual(pts, 25)
        self.assertGreaterEqual(len(hits), 5)

    def test_long_jd_with_no_overlap_scores_zero(self):
        jd = "We need someone to answer the phone and file paperwork carefully every day. " * 4
        self.assertEqual(skill_points("Receptionist", jd, DEFAULT_PROFILE)[0], 0)


class SeniorityTests(unittest.TestCase):
    def pts(self, years, title="Social Media Manager"):
        return seniority_points(years, title, DEFAULT_PROFILE)

    def test_years_bands(self):
        self.assertEqual(self.pts(None)[0], 10)
        self.assertEqual(self.pts(1)[0], 6)
        self.assertEqual(self.pts(3)[0], 15)
        self.assertEqual(self.pts(6)[0], 15)
        self.assertEqual(self.pts(8)[0], 9)
        self.assertEqual(self.pts(12)[0], 3)

    def test_years_gap_against_the_candidates_own_experience(self):
        five = load_profile(overrides={"years_experience": 5})
        pts = lambda y: seniority_points(y, "Social Media Manager", five)[0]
        self.assertEqual([pts(y) for y in (2, 5, 6, 7, 8, 9, 12)], [15, 15, 12, 9, 6, 3, 3])
        self.assertEqual(pts(None), 10)
        self.assertEqual(pts(1), 6)  # asking for a year or less is still junior work

    def test_without_candidate_years_the_fixed_bands_apply(self):
        self.assertEqual(seniority_points(8, "Social Media Manager", DEFAULT_PROFILE)[0], 9)

    def test_executive_title_is_treated_as_junior(self):
        pts, flags = self.pts(4, "Social Media Marketing Executive")
        self.assertLessEqual(pts, 6)
        self.assertIn("junior_title", flags)


class FreshnessTests(unittest.TestCase):
    def test_bands(self):
        self.assertEqual([freshness_points(a) for a in (0, 3, 4, 7, 8, 14, 15, None)], [5, 5, 3, 3, 1, 1, 0, 0])


class TierTests(unittest.TestCase):
    def tier(self, text):
        return tier_for(parse_pay(text), DEFAULT_PROFILE)

    def test_tiers(self):
        self.assertEqual(self.tier("AED 10,000"), "A")
        self.assertEqual(self.tier("AED 5K - AED 11K/mo"), "A")  # midpoint 8,000
        self.assertEqual(self.tier("AED 5,000 - 7,000"), "B")
        self.assertEqual(self.tier("AED 4,000 - 5,000"), "C")
        self.assertEqual(self.tier(None), "U")

    def test_top_of_range_under_floor_is_x(self):
        self.assertEqual(self.tier("AED3,500 - AED4,000 a month"), "C")  # ceiling == floor is not under it
        self.assertEqual(self.tier("AED 3,000 - 3,900"), "X")

    def test_open_ended_below_floor_is_unknown_not_rejected(self):
        self.assertEqual(self.tier("from AED 3,000"), "U")

    def test_range_straddling_floor_is_c(self):
        self.assertEqual(self.tier("AED 3,000 - 4,500"), "C")

    def test_format_pay(self):
        self.assertEqual(format_pay(None), "not listed")
        self.assertEqual(format_pay(parse_pay("AED 10,000")), "AED 10,000/mo")
        self.assertEqual(format_pay(parse_pay("AED 4,000 - 5,000")), "AED 4,000–5,000/mo")
        self.assertEqual(format_pay(parse_pay("AED 8,000+")), "AED 8,000+/mo")
        self.assertEqual(format_pay(parse_pay("up to 4000")), "AED up to 4,000/mo")
        self.assertTrue(format_pay(parse_pay("USD 4,000 per month")).startswith("≈ AED 14,690"))


class HardRejectTests(unittest.TestCase):
    def reasons(self, **kw):
        return ev(**kw).reject_reasons

    def test_clean_candidate_has_no_rejects(self):
        self.assertEqual(self.reasons(), [])

    def test_stale(self):
        self.assertIn("stale", self.reasons(posted="30+ days ago"))
        self.assertIn("stale", self.reasons(posted="Posted on: July 21, 2026"))
        self.assertNotIn("stale", self.reasons(posted="21 days ago"))
        self.assertIn("stale", self.reasons(posted="22 days ago"))

    def test_unknown_date_is_flagged_not_rejected(self):
        e = ev(posted=None)
        self.assertNotIn("stale", e.reject_reasons)
        self.assertIn("no_date", e.flags)

    def test_junior_by_label_or_title(self):
        self.assertIn("junior_level", self.reasons(level_label="Fresher"))
        self.assertIn("junior_level", self.reasons(level_label="Entry level"))
        self.assertIn("junior_level", self.reasons(title="Junior Video Editor"))
        self.assertIn("junior_level", self.reasons(title="Marketing Intern"))
        self.assertNotIn("junior_level", self.reasons(title="Head of International Marketing"))

    def test_pay_below_floor(self):
        self.assertIn("pay_below_floor", self.reasons(pay_text="AED 3,000 - 3,900"))
        # The top of the range equals the floor: not below it.
        self.assertNotIn("pay_below_floor", self.reasons(pay_text="AED3,500 - AED4,000 a month"))
        # Open-ended and straddling ranges are judged later, not rejected here.
        self.assertNotIn("pay_below_floor", self.reasons(pay_text="from AED 3,000"))
        self.assertNotIn("pay_below_floor", self.reasons(pay_text="AED 3,000 - 4,500"))

    def test_languages(self):
        self.assertIn("language:french", self.reasons(languages_required=["French"]))
        self.assertIn("language:chinese", self.reasons(languages_required=["Mandarin"]))
        self.assertEqual(self.reasons(languages_required=["English"]), [])

    def test_arabic_is_flag_only_by_default(self):
        e = ev(languages_required=["English", "Arabic"])
        self.assertEqual(e.reject_reasons, [])
        self.assertIn("language:arabic", e.flags)

    def test_arabic_rejects_once_user_lists_it_as_unsupported(self):
        profile = load_profile(overrides={"languages_flag_only": []})
        e = evaluate(cand(languages_required=["Arabic"]), profile, TODAY)
        self.assertIn("language:arabic", e.reject_reasons)

    def test_job_types(self):
        self.assertIn("job_type:part-time", self.reasons(job_type="part-time"))
        self.assertIn("job_type:freelance", self.reasons(job_type="Freelance"))
        e = ev(job_type="contract")
        self.assertEqual(e.reject_reasons, [])
        self.assertIn("contract", e.flags)

    def test_commission_only(self):
        self.assertIn("commission_only", self.reasons(description=RICH_JD + " This is a commission-only position."))
        self.assertIn("commission_only", self.reasons(description=RICH_JD + " 100% commission, no basic salary."))
        self.assertNotIn("commission_only", self.reasons(description=RICH_JD + " Basic salary plus commission."))

    def test_upfront_fee(self):
        self.assertIn("upfront_fee", self.reasons(description=RICH_JD + " A refundable security deposit is required."))
        self.assertIn("upfront_fee", self.reasons(description=RICH_JD + " Candidates must pay a small amount."))

    def test_company_paid_visa_is_not_a_scam_signal(self):
        self.assertNotIn("upfront_fee", self.reasons(description=RICH_JD + " The company covers visa fees and medical."))

    def test_whatsapp_only_apply(self):
        self.assertIn("whatsapp_only_apply", self.reasons(apply_method="whatsapp"))

    def test_visa(self):
        needs = load_profile(overrides={"needs_visa_sponsorship": True})
        e = evaluate(cand(visa_info="not_sponsored"), needs, TODAY)
        self.assertIn("no_visa_sponsorship", e.reject_reasons)
        e = evaluate(cand(visa_info="not_sponsored"), DEFAULT_PROFILE, TODAY)
        self.assertEqual(e.reject_reasons, [])
        self.assertIn("visa_not_stated", ev(visa_info="not_stated").flags)

    def test_multiple_reasons_are_all_reported_once(self):
        e = ev(posted="2026-01-01", level_label="Fresher", pay_text="AED 3,000", job_type="part-time")
        self.assertEqual(
            sorted(e.reject_reasons),
            sorted(["stale", "junior_level", "pay_below_floor", "job_type:part-time"]),
        )
        self.assertEqual(e.status, "rejected")


class ScoringTests(unittest.TestCase):
    def test_ideal_candidate_is_strong(self):
        e = ev(posted="Today")
        self.assertEqual(e.components, {"title": 30, "skills": 25, "seniority": 15, "pay": 20, "freshness": 5, "adjustment": 0})
        self.assertEqual(e.score, 95)
        self.assertEqual((e.status, e.strong, e.tier), ("shortlisted", True, "A"))

    def test_shortlist_and_strong_thresholds(self):
        # Good title and skills but no pay, no seniority signal, 10 days old: shortlisted, not strong.
        e = ev(pay_text=None, posted="10 days ago", years_required=None, description=RICH_JD[:130])
        self.assertEqual(e.score, sum(e.components.values()))
        self.assertEqual(e.status, "shortlisted")
        self.assertFalse(e.strong)
        self.assertGreaterEqual(e.score, 60)
        self.assertLess(e.score, 75)
        weak = ev(title="Content Creator", pay_text=None, posted="14 days ago", description="short")
        self.assertEqual(weak.status, "below_threshold")
        self.assertFalse(weak.strong)

    def test_off_target_title_is_capped_at_40(self):
        e = ev(title="Off-Page SEO Specialist", pay_text="AED 12,000", posted="Today")
        self.assertLessEqual(e.score, 40)
        self.assertIn("off_target_title", e.flags)
        self.assertEqual(e.status, "below_threshold")

    def test_scope_bloat_penalty_depends_on_pay_tier(self):
        bloat = ["social media", "website", "paid ads", "video editing"]
        cheap = ev(pay_text="AED 4,000 - 5,000", scope_items=bloat)
        rich = ev(pay_text="AED 12,000", scope_items=bloat)
        self.assertEqual(cheap.components["adjustment"], -10)
        self.assertEqual(rich.components["adjustment"], -4)
        self.assertIn("scope_bloat", cheap.flags)

    def test_free_email_apply_is_penalised(self):
        e = ev(apply_email="hr.recruit@gmail.com")
        self.assertEqual(e.components["adjustment"], -8)
        self.assertIn("free_email_apply", e.flags)
        self.assertEqual(ev(apply_email="jobs@acmestudio.example").components["adjustment"], 0)

    def test_watchlist_bonus_uses_normalised_company(self):
        profile = load_profile(overrides={"watchlist_companies": ["Acme Studio L.L.C"]})
        e = evaluate(cand(), profile, TODAY)
        self.assertEqual(e.components["adjustment"], 5)
        self.assertIn("watchlist_company", e.flags)

    def test_adjustment_is_clamped(self):
        # free email (-8) + scope bloat at tier C (-10) + hidden employer (-5) = -23, clamped to -20.
        e = ev(apply_email="a@gmail.com", company="Confidential", pay_text="AED 4,500",
               scope_items=["a", "b", "c", "d"])
        self.assertEqual(e.components["adjustment"], -20)

    def test_score_is_within_0_100(self):
        for kw in ({}, {"title": "x"}, {"pay_text": None, "posted": None}):
            self.assertTrue(0 <= ev(**kw).score <= 100)

    def test_missing_description_is_flagged(self):
        self.assertIn("no_jd", ev(description="").flags)

    def test_unlisted_pay_is_flagged_and_tier_u(self):
        e = ev(pay_text=None)
        self.assertEqual(e.tier, "U")
        self.assertEqual(e.pay_display, "not listed")
        self.assertIn("pay_unlisted", e.flags)

    def test_only_risky_pay_assumptions_are_flagged(self):
        self.assertFalse([f for f in ev(pay_text="AED 10,000").flags if f.startswith("pay_assumed")])
        self.assertFalse([f for f in ev(pay_text="25,000").flags if f.startswith("pay_assumed")])
        self.assertIn("pay_assumed:period_assumed_yearly", ev(pay_text="AED 120,000").flags)
        self.assertIn("pay_assumed:multiple_numbers_used_first", ev(pay_text="Basic 9000 + housing 2000 + transport 500").flags)

    def test_engineering_titles_are_marked_down_even_with_ai_in_the_title(self):
        # Seen live: a software-engineering post that scored above a better-fitting AI role.
        eng = ev(title="Generative AI Software Engineer & Digital Marketing Specialist | AI Automation")
        plain = ev(title="Generative AI Producer")
        self.assertIn("engineering_role", eng.flags)
        self.assertEqual(eng.components["adjustment"], -8)
        self.assertNotIn("engineering_role", plain.flags)

    def test_prompt_engineer_is_not_treated_as_an_engineering_role(self):
        self.assertNotIn("engineering_role", ev(title="Prompt Engineer").flags)
        self.assertIn("engineering_role", ev(title="Prompt Engineer and Backend Developer").flags)

    def test_business_development_is_not_a_developer(self):
        self.assertNotIn("engineering_role", ev(title="Business Development Manager").flags)

    def test_advertised_minimum_under_the_floor_is_flagged_not_rejected(self):
        # Seen live: "From AED1,111.00 per month" on a real Dubai AI role.
        e = ev(pay_text="From AED1,111.00 per month")
        self.assertIn("pay_min_below_floor", e.flags)
        self.assertEqual((e.tier, e.reject_reasons), ("U", []))
        self.assertNotIn("pay_min_below_floor", ev(pay_text="From AED 5,000").flags)
        self.assertNotIn("pay_min_below_floor", ev(pay_text="From AED18,000.00 per month").flags)

    def test_a_freelance_title_on_a_permanent_post_is_flagged(self):
        # Seen live: "Freelance Graphic Designer ..." posted as Permanent.
        e = ev(title="Freelance Graphic Designer & Creative Content Specialist", job_type="full-time")
        self.assertIn("title_says:freelance", e.flags)
        self.assertNotIn("job_type:freelance", e.reject_reasons)
        self.assertEqual([f for f in ev(job_type="freelance").flags if f.startswith("title_says")], [])

    def test_extra_flags_are_validated_and_capped(self):
        base = set(ev().flags)
        e = ev(extra_flags=["employer_mismatch", "Prompt_Injection_Attempt", "bad flag!", "<script>", "x" * 50,
                            "a", "b", "c", "d"])
        added = set(e.flags) - base
        # Junk is dropped without using up slots; of the 6 valid labels only the first 5 are kept.
        self.assertEqual(added, {"employer_mismatch", "prompt_injection_attempt", "a", "b", "c"})
        self.assertNotIn("d", e.flags)

    def test_pay_estimate_flag(self):
        self.assertIn("pay_estimate", ev(pay_source="estimate").flags)

    def test_gender_restricted_is_flag_only(self):
        e = ev(gender_restricted=True)
        self.assertIn("gender_restricted", e.flags)
        self.assertEqual(e.reject_reasons, [])

    def test_why_mentions_title_and_skills(self):
        why = ev().why
        self.assertIn("creative ai", why)
        self.assertIn("skills in JD", why)

    def test_evaluate_does_not_mutate_input(self):
        c = cand()
        before = copy.deepcopy(c)
        evaluate(c, DEFAULT_PROFILE, TODAY)
        self.assertEqual(c, before)

    def test_same_input_same_output(self):
        self.assertEqual(ev().to_dict(), ev().to_dict())


class DedupeTests(unittest.TestCase):
    def test_same_job_on_two_boards_collapses_and_keeps_richest(self):
        indeed = cand(source="indeed", pay_text=None, description="short", url="https://indeed.example/1")
        bayt = cand(source="bayt", pay_text="AED 12,000", description=RICH_JD, url="https://bayt.example/9",
                    company="Acme Studio L.L.C", title="Creative AI Specialist (Dubai)")
        unique, dups = dedupe_candidates([indeed, bayt])
        self.assertEqual(dups, 1)
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["pay_text"], "AED 12,000")
        self.assertEqual(sorted(unique[0]["all_urls"]), ["https://bayt.example/9", "https://indeed.example/1"])

    def test_pay_from_poorer_record_is_not_lost(self):
        a = cand(pay_text="AED 9,000", description="", url="https://a.example")
        b = cand(pay_text=None, description=RICH_JD, url="https://b.example")
        unique, _ = dedupe_candidates([a, b])
        self.assertEqual(unique[0]["pay_text"], "AED 9,000")
        self.assertEqual(unique[0]["description"], RICH_JD)

    def test_different_jobs_stay_separate(self):
        unique, dups = dedupe_candidates([cand(), cand(title="Social Media Manager")])
        self.assertEqual((len(unique), dups), (2, 0))

    def test_input_not_mutated(self):
        a = cand()
        before = copy.deepcopy(a)
        dedupe_candidates([a, cand()])
        self.assertEqual(a, before)


class ValidateTests(unittest.TestCase):
    def test_validate(self):
        self.assertEqual(validate_candidate(cand()), [])
        self.assertEqual(validate_candidate(cand(title="")), ["missing title"])
        self.assertEqual(validate_candidate({"title": "x"}), ["missing company"])
        self.assertEqual(validate_candidate("nope"), ["candidate is not an object"])


class ProfileTests(unittest.TestCase):
    def test_overrides_win_and_defaults_remain(self):
        p = load_profile(overrides={"floor": 6000, "tier_b": 7000})
        self.assertEqual((p["floor"], p["tier_a"]), (6000, 8000))

    def test_invalid_salary_policy_raises(self):
        with self.assertRaises(ValueError):
            load_profile(overrides={"floor": 9000})
        with self.assertRaises(ValueError):
            load_profile(overrides={"shortlist_threshold": 90, "strong_threshold": 80})

    def test_defaults_are_not_shared_between_loads(self):
        p = load_profile()
        p["lexicon"].append("zzz")
        self.assertNotIn("zzz", load_profile()["lexicon"])


if __name__ == "__main__":
    unittest.main()
