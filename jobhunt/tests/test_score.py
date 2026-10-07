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

    def test_expired_posts_are_rejected_whether_the_model_flags_them_or_the_text_says_so(self):
        self.assertIn("expired", self.reasons(extra_flags=["expired_on_indeed"]))
        self.assertIn("expired", self.reasons(extra_flags=["expired"]))
        self.assertIn("expired", self.reasons(extra_flags=["Expired_On_Indeed"]))  # flags are lower-cased first
        for text in ("This job has expired on Indeed.", "This job is no longer available.", "The position has been filled.",
                     "This role is closed.", "We are no longer accepting applications.", "The vacancy was filled last week."):
            self.assertIn("expired", self.reasons(description=RICH_JD + " " + text), text)
        self.assertIn("expired", self.reasons(title="Content Creator - this position has been filled"))

    def test_ordinary_words_do_not_make_a_post_expired(self):
        for text in ("Applications close on 30 October.", "You will help us close more deals and expire no ideas.",
                     "The role is open to applicants worldwide.", "We closed a funding round this year.",
                     "Our offer expires after 7 days.", "Experience with expired-domain SEO is a plus."):
            self.assertNotIn("expired", self.reasons(description=RICH_JD + " " + text), text)
        self.assertNotIn("expired", self.reasons(extra_flags=["employer_mismatch", "heavy_overtime"]))

    def test_a_sentence_that_only_mentions_a_filled_or_closed_post_does_not_reject_a_live_job(self):
        # Critics showed the first version of the rule rejected real jobs whose text talked about these cases.
        for text in ("In the event this position has been filled, we will keep your CV on file.",
                     "If this role is closed to you because of your visa, tell us.",
                     "We will let you know once the position has been filled.",
                     "This position is closed-loop: you own the funnel from lead to renewal.",
                     "Note that the job is no longer available to candidates who need sponsorship, so apply early.",
                     "Reply within 7 days, after which we are no longer accepting applications from agencies and recruiters."):
            self.assertNotIn("expired", self.reasons(description=RICH_JD + " " + text), text)

    def test_the_notice_counts_on_its_own_line_inside_a_longer_description(self):
        for page in (RICH_JD + "\n\n## This job has expired on Indeed\n\nSee similar jobs",
                     "⚠️ The position has been filled.\n" + RICH_JD,
                     RICH_JD + "\nThis job is no longer available"):
            self.assertIn("expired", self.reasons(description=page), page[:40])

    def test_says_expired_directly(self):
        from jobhunt.score import says_expired
        self.assertTrue(says_expired("Role (this job has expired)", ""))
        self.assertTrue(says_expired("Role", "We're no longer accepting applications"))
        self.assertFalse(says_expired("Role", ""))
        self.assertFalse(says_expired("", None))

    def test_an_expired_post_is_never_shortlisted_however_well_it_scores(self):
        e = ev(extra_flags=["expired_on_indeed"])
        self.assertEqual(e.status, "rejected")
        self.assertFalse(e.strong)
        self.assertEqual(e.reject_reasons[0], "expired")

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

    def test_a_candidate_with_their_own_visa_is_never_rejected_or_warned_about_visas(self):
        own = load_profile(overrides={"needs_visa_sponsorship": False})
        for visa in ("sponsored", "not_sponsored", "not_stated", None):
            e = evaluate(cand(visa_info=visa), own, TODAY)
            self.assertEqual(e.reject_reasons, [], visa)
            self.assertNotIn("visa_not_stated", e.flags, visa)
            self.assertNotIn("no_visa_sponsorship", e.reject_reasons, visa)
        # Only an explicit False silences the warning; "unknown" (None) keeps it.
        unknown = load_profile(overrides={"needs_visa_sponsorship": None})
        self.assertIn("visa_not_stated", evaluate(cand(visa_info="not_stated"), unknown, TODAY).flags)

    def test_the_visa_setting_does_not_change_the_score(self):
        base = evaluate(cand(visa_info="not_stated"), DEFAULT_PROFILE, TODAY).score
        own = evaluate(cand(visa_info="not_stated"), load_profile(overrides={"needs_visa_sponsorship": False}), TODAY).score
        self.assertEqual(base, own)

    def test_arabic_required_rejects_for_someone_who_does_not_work_in_arabic(self):
        # The private settings list Arabic as unsupported: languages_flag_only is emptied.
        profile = load_profile(overrides={"languages_flag_only": []})
        self.assertIn("language:arabic", evaluate(cand(languages_required=["English", "Arabic"]), profile, TODAY).reject_reasons)
        # "A plus" is not "required": the model leaves it out of languages_required, so nothing is rejected.
        self.assertEqual(evaluate(cand(languages_required=["English"]), profile, TODAY).reject_reasons, [])

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

    def test_the_thin_bar_may_not_exceed_the_normal_bar(self):
        with self.assertRaises(ValueError):
            load_profile(overrides={"thin_shortlist_threshold": 61})
        self.assertEqual(load_profile(overrides={"thin_shortlist_threshold": 60})["thin_shortlist_threshold"], 60)


class LocationTests(unittest.TestCase):
    def status(self, location, **kw):
        return evaluate(cand(location=location, **kw), DEFAULT_PROFILE, TODAY)

    def test_other_countries_are_rejected(self):
        for place, token in (("Riyadh", "riyadh"), ("Riyadh, Saudi Arabia", "riyadh"), ("Doha, Qatar", "doha"),
                             ("Kuwait City", "kuwait"), ("Bengaluru, India", "india"), ("Hong Kong", "hong_kong")):
            e = self.status(place)
            self.assertEqual(e.reject_reasons, ["location:" + token], place)
            self.assertEqual(e.status, "rejected")

    def test_dubai_in_any_form_is_fine(self):
        for place in ("Dubai", "Dubai, United Arab Emirates", "Business Bay, Dubai", "Dubai Silicon Oasis, Dubai",
                      "United Arab Emirates", "UAE", "Al Quoz"):
            e = self.status(place)
            self.assertEqual(e.reject_reasons, [], place)
            self.assertFalse([f for f in e.flags if f.startswith("outside_dubai")], place)

    def test_an_empty_location_means_the_search_was_for_dubai(self):
        e = evaluate(cand(location=None), DEFAULT_PROFILE, TODAY)
        self.assertEqual(e.reject_reasons, [])
        self.assertEqual(e.location, "Dubai")

    def test_other_emirates_are_flagged_not_rejected(self):
        for place, token in (("Sharjah Emirate, United Arab Emirates", "sharjah"), ("Abu Dhabi", "abu_dhabi"),
                             ("Ras Al Khaimah", "ras_al_khaimah")):
            e = self.status(place)
            self.assertEqual(e.reject_reasons, [], place)
            self.assertIn("outside_dubai:" + token, e.flags, place)

    def test_a_post_that_names_dubai_and_another_emirate_is_not_flagged(self):
        e = self.status("Dubai / Sharjah")
        self.assertFalse([f for f in e.flags if f.startswith("outside_dubai")])

    def test_a_place_name_inside_a_longer_word_does_not_match(self):
        # "oman" sits inside "Romania"; "india" inside "Indianapolis".
        self.assertEqual(self.status("Bucharest, Romania").reject_reasons, [])
        self.assertEqual(self.status("Indianapolis").reject_reasons, [])

    def test_the_lists_can_be_changed_in_the_profile(self):
        allow_abu_dhabi = load_profile(overrides={"flag_locations": [], "reject_locations": ["riyadh"]})
        e = evaluate(cand(location="Abu Dhabi"), allow_abu_dhabi, TODAY)
        self.assertFalse([f for f in e.flags if f.startswith("outside_dubai")])
        self.assertEqual(evaluate(cand(location="Doha"), allow_abu_dhabi, TODAY).reject_reasons, [])


class ThinListingTests(unittest.TestCase):
    """A listing with no job description is judged at the thin bar; one with a description is not."""

    def thin(self, **kw):
        base = dict(description="", pay_text=None, pay_source=None, posted=None, years_required=None,
                    scope_items=[], visa_info="not_stated")
        base.update(kw)
        return evaluate(cand(**base), DEFAULT_PROFILE, TODAY)

    def test_a_clear_title_with_nothing_else_clears_the_thin_bar(self):
        e = self.thin(title="Social Media Manager")
        self.assertIn("no_jd", e.flags)
        self.assertEqual((e.score, e.status, e.strong), (50, "shortlisted", False))

    def test_a_score_between_the_two_bars_shortlists_only_without_a_description(self):
        # With a description this role scores 52: above the thin bar (50) but below the normal bar (60).
        description = ("Look after our Instagram and use Canva to design the posts. We need someone organised "
                       "who can plan the month ahead for the team.")
        with_jd = self.thin(title="Social Media Manager", description=description)
        self.assertNotIn("no_jd", with_jd.flags)
        self.assertTrue(50 <= with_jd.score < 60, with_jd.score)
        self.assertEqual(with_jd.status, "below_threshold")
        # The same role with no description scores 50, and that clears the thin bar.
        without_jd = self.thin(title="Social Media Manager")
        self.assertEqual((without_jd.score, without_jd.status), (50, "shortlisted"))

    def test_a_weak_title_stays_below_even_with_no_description(self):
        e = self.thin(title="Marketing Manager")
        self.assertEqual(e.status, "below_threshold")

    def test_a_thin_listing_can_never_be_strong(self):
        e = self.thin(title="Creative AI Specialist", posted="Posted on: October 05, 2026")
        self.assertEqual(e.status, "shortlisted")
        self.assertFalse(e.strong)
        self.assertLess(e.score, 75)

    def test_the_thin_bar_is_a_setting(self):
        strict = load_profile(overrides={"thin_shortlist_threshold": 60})
        e = evaluate(cand(title="Social Media Manager", description="", pay_text=None, posted=None, years_required=None,
                          scope_items=[], visa_info="not_stated"), strict, TODAY)
        self.assertEqual(e.status, "below_threshold")

    def test_a_reject_reason_still_wins_over_the_thin_bar(self):
        e = self.thin(title="Social Media Manager", level_label="Fresher")
        self.assertEqual(e.status, "rejected")


class ListingPageLinkTests(unittest.TestCase):
    """A results page is not a job. A live run stored the Indeed search address as a job's link."""

    SERP = "https://ae.indeed.com/jobs?q=Generative+AI+Specialist&l=Dubai&fromage=3&sort=date"

    def test_a_search_page_is_never_kept_as_the_jobs_link(self):
        e = evaluate(cand(url=self.SERP), DEFAULT_PROFILE, TODAY)
        self.assertEqual(e.url, "")
        self.assertEqual(e.all_urls, [])
        self.assertIn("no_job_link", e.flags)

    def test_the_other_listing_pages_are_caught_too(self):
        for url in ("https://ae.indeed.com/q-social-media-manager-l-dubai-jobs.html",
                    "https://ae.indeed.com/l-dubai-jobs.html",
                    "https://www.bayt.com/en/uae/jobs/social-media-manager-jobs-in-dubai/",
                    "https://www.linkedin.com/jobs/search/?keywords=social%20media",
                    "https://www.linkedin.com/comm/jobs/search-results/?x=1"):
            self.assertEqual(evaluate(cand(url=url), DEFAULT_PROFILE, TODAY).url, "", url)

    def test_real_job_links_are_untouched(self):
        for url in ("https://ae.indeed.com/viewjob?jk=a99402720521a673", "https://to.indeed.com/aactk227gs7w",
                    "https://www.bayt.com/en/uae/jobs/senior-social-media-manager-4567890/",
                    "https://www.linkedin.com/jobs/view/4473137196/", "https://example.com/jobs/azya-smmm"):
            e = evaluate(cand(url=url), DEFAULT_PROFILE, TODAY)
            self.assertEqual(e.url, url, url)
            self.assertNotIn("no_job_link", e.flags, url)

    def test_a_missing_url_is_not_flagged_as_a_wrong_one(self):
        self.assertNotIn("no_job_link", evaluate(cand(url=None), DEFAULT_PROFILE, TODAY).flags)

    def test_the_good_link_survives_when_the_job_was_seen_on_two_pages(self):
        e = evaluate(cand(url=self.SERP, all_urls=[self.SERP, "https://to.indeed.com/aabbcc"]), DEFAULT_PROFILE, TODAY)
        self.assertEqual(e.all_urls, ["https://to.indeed.com/aabbcc"])


class SnippetOnlyTests(unittest.TestCase):
    """The few bullets a results page shows are not a job description."""

    SNIPPET = ("Experience with ChatGPT, Gemini, Claude & AI tools. Basic AI automation and prompt engineering. "
               "Use AI tools for daily business tasks.")  # 133 characters: over the 120 that counts as a description

    def test_without_the_marker_a_snippet_is_scored_like_a_full_description(self):
        e = evaluate(cand(title="AI Specialist", description=self.SNIPPET, pay_text=None, years_required=None), DEFAULT_PROFILE, TODAY)
        self.assertNotIn("no_jd", e.flags)  # this is the false precision the marker removes
        self.assertGreater(e.components["skills"], 8)

    def test_with_the_marker_it_is_judged_on_the_title_and_the_rest(self):
        e = evaluate(cand(title="AI Specialist", description=self.SNIPPET, description_partial=True, pay_text=None,
                          years_required=None), DEFAULT_PROFILE, TODAY)
        self.assertIn("no_jd", e.flags)
        self.assertEqual(e.components["skills"], 8)
        self.assertFalse(e.strong)

    def test_the_marker_does_not_hide_a_full_description(self):
        full = evaluate(cand(description_partial=False), DEFAULT_PROFILE, TODAY)
        self.assertNotIn("no_jd", full.flags)

    def test_the_snippet_text_is_still_kept_for_the_report(self):
        e = evaluate(cand(description=self.SNIPPET, description_partial=True), DEFAULT_PROFILE, TODAY)
        self.assertEqual(e.description, self.SNIPPET)


class AmpersandTests(unittest.TestCase):
    def test_an_ampersand_reads_as_and(self):
        self.assertEqual(title_points("Social Media & Digital Marketing Manager", "", DEFAULT_PROFILE)[0], 24)
        self.assertEqual(title_points("Social Media and Digital Marketing Manager", "", DEFAULT_PROFILE)[0], 24)
        self.assertEqual(title_points("AI&Automation Lead", "", DEFAULT_PROFILE)[0], 22)  # no spaces around it either

    def test_the_existing_titles_keep_their_points(self):
        self.assertEqual(title_points("AI & Automation Specialist", "", DEFAULT_PROFILE)[0], 22)
        self.assertEqual(title_points("Social Media & AI Manager", "", DEFAULT_PROFILE)[0], 24)


if __name__ == "__main__":
    unittest.main()
