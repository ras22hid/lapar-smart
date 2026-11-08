"""The FAMA staff questionnaire (Section 3.2.1 / Appendix D of the report).

The questions and answer choices live here once so the public form, the
admin results page and the CSV export can never drift apart. Answers are
stored as the choice text itself, so a raw export reads like the report."""

QUESTIONS = [
    {
        "key": "q1",
        "text": "How often do you purchase food or beverages from Lazaria Cafe in a week?",
        "options": ["Less than once a week", "1 to 2 times", "3 to 4 times", "5 times or more"],
    },
    {
        "key": "q2",
        "text": "On average, how long do you wait in line to place your order at the counter?",
        "options": ["Less than 5 minutes", "5 to 10 minutes", "11 to 15 minutes", "More than 15 minutes"],
    },
    {
        "key": "q3",
        "text": "Have you ever experienced an incorrect order due to miscommunication at the counter?",
        "options": ["No, never", "Yes, once", "Yes, sometimes (2 to 3 times)", "Yes, often (4 times or more)"],
    },
    {
        "key": "q4",
        "text": "Would you find it useful to receive a notification when your order is ready for collection?",
        "options": ["Very useful", "Useful", "Neutral", "Not very useful", "Not useful at all"],
    },
    {
        "key": "q5",
        "text": "Would you be interested in reserving food and beverages in advance for meeting room events?",
        "options": ["Very interested", "Interested", "Neutral", "Not very interested", "Not interested at all"],
    },
]


def _pct(count, total):
    return round(count * 100 / total, 1) if total else 0.0


def tally(rows):
    """Counts and percentages per answer, in the order of Table 3.1."""
    total = len(rows)
    result = []
    for q in QUESTIONS:
        counts = {o: 0 for o in q["options"]}
        for r in rows:
            if r[q["key"]] in counts:
                counts[r[q["key"]]] += 1
        result.append(
            {
                "key": q["key"],
                "text": q["text"],
                "rows": [{"label": o, "count": c, "pct": _pct(c, total)} for o, c in counts.items()],
            }
        )
    return total, result


def summary_sentences(rows):
    """Plain-English findings for Section 2.1 and under Table 3.1, built only
    from the recorded answers. Empty until at least one response exists."""
    total = len(rows)
    if not total:
        return {"evidence": "", "findings": ""}

    def share(key, answers):
        return _pct(sum(1 for r in rows if r[key] in answers), total)

    def commonest(key):
        counts = {}
        for r in rows:
            counts[r[key]] = counts.get(r[key], 0) + 1
        label = max(QUESTIONS_BY_KEY[key]["options"], key=lambda o: counts.get(o, 0))
        return label, _pct(counts.get(label, 0), total)

    long_wait = share("q2", ("11 to 15 minutes", "More than 15 minutes"))
    wrong_any = share("q3", QUESTIONS_BY_KEY["q3"]["options"][1:])
    wrong_often = share("q3", ("Yes, sometimes (2 to 3 times)", "Yes, often (4 times or more)"))
    notify = share("q4", ("Very useful", "Useful"))
    preorder = share("q5", ("Very interested", "Interested"))
    wait_label, wait_pct = commonest("q2")

    evidence = (
        f"Of {total} respondents, {long_wait}% waited 11 minutes or longer in line at the counter "
        f"and {wrong_any}% had received a wrong order at least once."
    )
    findings = (
        f"The most common waiting time at the counter was {wait_label.lower()} ({wait_pct}% of {total} respondents), "
        f"and {long_wait}% waited 11 minutes or longer. {wrong_any}% had received an incorrect order at least once "
        f"and {wrong_often}% had experienced it two or more times. "
        f"{notify}% found a notification when the order is ready useful or very useful, and "
        f"{preorder}% were interested or very interested in reserving food for meeting room events."
    )
    return {"evidence": evidence, "findings": findings}


QUESTIONS_BY_KEY = {q["key"]: q for q in QUESTIONS}
