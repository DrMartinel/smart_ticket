"""Builds 08-traceability.md from the feature specs.

Usage: python3 docs/requirements/phase-2/tools/build_traceability.py docs/requirements/phase-2
"""
import re, sys, os
D = sys.argv[1]
FEATS = [("PRE-1","06-PRE-prerequisites.md","PRE1"),("PRE-2","06-PRE-prerequisites.md","PRE2"),
 ("F1","06-F1-sla.md","F1"),("F2","06-F2-teams-assignment.md","F2"),("F3","06-F3-requester-chat.md","F3"),
 ("F4","06-F4-notifications.md","F4"),("F5","06-F5-pii-reveal.md","F5"),("F6","06-F6-kb-governance.md","F6"),
 ("F7","06-F7-mass-incident.md","F7"),("F8","06-F8-security-inbox.md","F8"),("F9","06-F9-rollout-control.md","F9"),
 ("F10","06-F10-reporting.md","F10"),("F11","06-F11-graph-retrieval.md","F11"),("F12","06-F12-itsm-iam-integration.md","F12"),
 ("F13","06-F13-identity.md","F13")]
GOALS = {"PRE-1":"G5, G7","PRE-2":"G1, G2, G4, G6","F1":"G1","F2":"G2","F3":"G3","F4":"G4","F5":"G5","F6":"G7","F7":"G7","F8":"G7","F9":"G7","F10":"G1, G2, G3, G7","F11":"G7","F12":"G7","F13":"G6"}
KPIS = {"F1":"K1, K2, K3","F2":"K4, K5","F3":"K6, K7","F4":"K8","F5":"K9","F13":"K10, K11","F8":"K12","F7":"K13","F9":"K14","PRE-1":"K9, K14"}
MOSCOW = {"PRE-1":"Must","PRE-2":"Must","F1":"Must","F2":"Must","F3":"Must","F4":"Must","F5":"Must","F13":"Must","F6":"Should","F7":"Should","F8":"Should","F9":"Should","F10":"Should","F11":"Could","F12":"Could"}
def ids(t, kind, tag):
    pat = rf'\b{kind}-{tag}-\d+\b'
    return sorted(set(re.findall(pat, t)), key=lambda x: int(x.rsplit("-", 1)[1]))
def rng(xs):
    if not xs: return "—"
    if len(xs) <= 3: return ", ".join(xs)
    return f"{xs[0]} … {xs[-1]} ({len(xs)})"
def expand(t):
    def rep(m):
        kind, tag, a, b = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        w = len(m.group(3))
        return ", ".join(f"{kind}-{tag}-{i:0{w}d}" for i in range(a, b + 1))
    t = re.sub(r'\b(BR|FR|UC|AC)-([A-Z0-9]+)-(\d+)\s*(?:…|\.\.\.|–)\s*(\d+)\b', rep, t)
    def rep_list(m):
        kind, tag, first, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        w = len(first)
        nums = [first] + re.findall(r'\d+', rest)
        return ", ".join(f"{kind}-{tag}-{int(n):0{w}d}" for n in nums)
    return re.sub(r'\b(BR|FR|UC|AC)-([A-Z0-9]+)-(\d+)((?:,\s*\d+\b(?![-\d]))+)', rep_list, t)
def section(t, tag):
    if tag == "PRE1": return t.split("# PRE-2")[0]
    if tag == "PRE2": return t.split("# PRE-2")[1]
    return t
out = []
out.append("# 8. Traceability\n")
out.append("Generated from the feature files by `tools/build_traceability.py`, so it can't drift\nfrom them silently. Re-run it after any spec change. IDs are defined in each\nfeature's §d–§j.\n")
out.append("## 8.1 Goal → feature → requirements → tests\n")
out.append("| Goal | KPI | Feature | MoSCoW | Use cases | FRs | BRs | ADRs | Acceptance | Regression tests |")
out.append("|---|---|---|---|---|---|---|---|---|---|")
uc_rows = []; coverage = []; test_rows = []
for name, f, tag in FEATS:
    t = section(expand(open(os.path.join(D, f)).read()), tag)
    ucs, frs, brs, acs = ids(t,"UC",tag), ids(t,"FR",tag), ids(t,"BR",tag), ids(t,"AC",tag)
    adrs = set(re.findall(r'ADR-(\d{4})', t))
    for line in re.findall(r'\*\*ADRs?:?\*\*:?(.*)', t):
        adrs |= set(re.findall(r'\b(00\d\d)\b', line))
    adrs = sorted(adrs)
    tests = sorted(set(re.findall(r'`(test_[a-z0-9_]+)`', t)))
    test_rows.append((name, acs, tests))
    out.append(f"| {GOALS.get(name,'—')} | {KPIS.get(name,'—')} | [{name}]({f}) | {MOSCOW[name]} | {rng(ucs)} | {rng(frs)} | {rng(brs)} | {', '.join(adrs) or '—'} | {rng(acs)} | {len(tests)} |")
    # UC level
    for block in re.split(r'\n(?=\| Field \| UC-)', t):
        m = re.match(r'\| Field \| (UC-[A-Z0-9]+-\d+) · (.+?) \|', block)
        if not m: continue
        rules = re.search(r'^\| Rules \| (.+?) \|$', block, re.M)
        screens = re.search(r'^\| Screens \| (.+?) \|$', block, re.M)
        uc_rows.append((name, m.group(1), m.group(2), rules.group(1) if rules else "—", screens.group(1) if screens else "—"))
    # summary-table UCs (Could features)
    for m in re.finditer(r'^\| (UC-[A-Z0-9]+-\d+) \| ([^|]+?) \| ([^|]+?) \| ([^|]+?) \|$', t, re.M):
        uc_rows.append((name, m.group(1), m.group(3), m.group(4), "see §d"))
    # coverage: BRs never referenced outside their own definition row
    for br in brs:
        n = len(re.findall(re.escape(br)+r'\b', t))
        others = sum(len(re.findall(re.escape(br)+r'\b', expand(open(os.path.join(D,g)).read()))) for g in os.listdir(D) if g.endswith('.md') and g not in (f, '08-traceability.md'))
        if n + others <= 1: coverage.append(br)
out.append("\nGoals and KPIs are defined in [§1](01-executive-summary.md). ADR numbers ≥ 0030 are proposed ([§9.4](09-risks-open-questions.md#94-proposed-adrs)).\n")
out.append("## 8.2 Use case → rules → screens\n")
out.append("Screens link to their Figma frames (stage 5, [mockups.md](mockups.md)).\n")
out.append("| Feature | Use case | Name | Rules | Screens |")
out.append("|---|---|---|---|---|")
for r in uc_rows: out.append("| " + " | ".join(r) + " |")
out.append("\n## 8.3 Feature → tests\n")
out.append("Acceptance scenarios (Gherkin, §j) and the regression tests named in §i.\n")
out.append("| Feature | Acceptance scenarios | Regression tests |")
out.append("|---|---|---|")
for name, acs, tests in test_rows:
    out.append(f"| {name} | {rng(acs)} | " + (", ".join(f"`{x}`" for x in tests) or "—") + " |")
out.append("\n## 8.4 Coverage check\n")
out.append(f"- Features traced: {len(FEATS)}. Use cases: {len(uc_rows)}.")
out.append("- Business rules referenced only where they are defined (no use case, FR or test cites them): " + (", ".join(coverage) if coverage else "none") + ".")
if coverage: out.append("  These still bind (they are in §e); stage 6 decides whether each needs its own acceptance scenario.")
out.append("- Business rules link to tests at feature level (8.1). Tagging each acceptance scenario with the rule ids it proves is a stage 6 task.")
open(os.path.join(D, "08-traceability.md"), "w").write("\n".join(out) + "\n")
print(len(uc_rows), coverage)
