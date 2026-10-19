# Execution Evidence Guide (Deliverable 06)

**What the rules require.** For a non-on-chain topic (Topic B is one), execution evidence is **simulated-account / sandbox operation logs** *and* the **demo video**. Real on-chain transaction hashes are only required for the on-chain topic (F), so you do **not** need them — but if you show Sepolia anchoring, use a real anchor and open it on Etherscan (README → "Checking on-chain anchors").

**Deadline:** 2026-10-20 23:59 Beijing (UTC+8) = 15:59 UTC = 16:59 London (BST). Later versions overwrite earlier ones, so submit early and re-submit if you improve it.

---

## What you already have

`evidence/` (committed to the repo — the `.agents/` folder is git-ignored, so nothing there would ship):

| File | What it is |
| :--- | :--- |
| `live_e2e_results.json` | 57 operations against the **live** Render + Vercel deployment: method, endpoint, status, latency, sanitised request/response, timestamp. 57/57 passed. Tokens are already redacted. |
| `LIVE_VERIFICATION_REPORT.md` | Human-readable summary of that run, by route group |
| `test_live_e2e.py` | The script that produced it — so a judge can reproduce it |
| `adversarial_stress_results.json` | Adversarial / boundary probes against the live deployment |
| `unit_test_run.log` | Local unit-test output (see the note on the 4 failures in the summary) |

This is your **sandbox operation log**. The remaining piece is the **demo video** and a few screenshots tying the log to what a judge can see.

---

## Step 1 — Re-run the live suite so the log is fresh

Do this once the deployment is final (after any last push), so the log timestamps match the version being judged.

```powershell
cd "C:\Users\HP VICTUS\Documents\wealth_agent"
pip install httpx websockets
python evidence\test_live_e2e.py
```

It registers a throwaway user, so it never touches real data. It rewrites `live_e2e_results.json` and `LIVE_VERIFICATION_REPORT.md` next to the script. **Render's free tier sleeps** — the first request can take ~30–60 s; open <https://finfuture.onrender.com/health> in a browser first to wake it.

Then confirm the headline numbers before you quote them:

```powershell
python -c "import json;d=json.load(open('evidence/live_e2e_results.json'));print(d['passed_tests'],'/',d['total_tests'],'passed;',d['failed_tests'],'failed')"
```

Commit and push: `git add evidence && git commit -m "Refresh execution evidence" && git push`.

---

## Step 2 — Capture the demo video (≤ 5 min, optional but strongly recommended)

Record the **live** site, not localhost, so the judge sees the deployed product. Windows: `Win + G` (Game Bar) or OBS. 1080p, microphone on, English narration (English is the official language of the track).

**Before recording**
1. Wake the backend: open `https://finfuture.onrender.com/health` until it returns `ok`.
2. Use a **fresh account with a real inbox you can open on screen** (e.g. a Gmail alias such as `you+demo1@gmail.com`), so onboarding is part of the story and the step-up code arrives. Red-tier orders cannot be approved on the live site until an email provider (`BREVO_API_KEY` + `EMAIL_FROM`) is set on Render.
3. Close other tabs, hide bookmarks and personal data. Don't show `.env`, API keys, or the Render dashboard environment page.

**Suggested script (~4:30)**

| Time | Show | Say |
| :--- | :--- | :--- |
| 0:00–0:20 | Landing page | One-line pitch: non-discretionary AI wealth advisor; the model writes words, code supplies numbers, a human approves every trade. |
| 0:20–1:10 | Register → onboarding chat | Risk profiling by conversation; stated vs revealed tolerance; the more conservative wins. |
| 1:10–2:00 | Advisor: ask for an allocation / compare funds | Black-Litterman + CVaR numbers come from code; show the comparison table and rationale. |
| 2:00–2:45 | Propose a trade over \$1,000 → Continue to verification → open the email → enter the code | Tier 3 proposal, 15-min expiry. Tier 4 needs explicit approval, and above \$1,000 a single-use code emailed to the client. Optionally type a wrong code first to show "attempts left". |
| 2:45–3:30 | **Trigger a block**: an oversized or non-whitelisted order, or paste a prompt-injection line | Compliance firewall blocks it deterministically; show the rule ID and reason. |
| 3:30–4:00 | Audit page | Hash-chained entries, chain verification, Merkle proof. If a Sepolia wallet is configured: anchor, open the Etherscan link, show Input Data = Merkle root. |
| 4:00–4:30 | Refresh the page and reopen chat | History persisted in PostgreSQL across sessions. Close with the 57/57 live test result. |

**After recording:** trim dead air, export MP4, keep under the size limit on the submission form, and upload to a link that works without login (YouTube *unlisted*, or Google Drive "anyone with the link"). **Open the link in a private window to verify it.**

---

## Step 3 — Screenshots (5–8 images)

Save to `evidence/screenshots/` with descriptive names so the package is self-explanatory:

1. `01_live_health.png` — `https://finfuture.onrender.com/health` returning `{"status":"ok","paper_trading":true,…}`
2. `02_onboarding_profile.png` — completed risk profile
3. `03_allocation.png` — allocation with weights / CVaR
4. `04_trade_proposal.png` — proposal with expiry and compliance rule results
4b. `04b_step_up_code.png` — the step-up dialog next to the received email (blank out the full address)
5. `05_blocked_trade.png` — a trade rejected with the rule ID visible
6. `06_audit_chain_verified.png` — audit page / `GET /audit/{client_id}/verify` showing `valid: true`
7. `07_live_test_summary.png` — terminal output of `python evidence\test_live_e2e.py` ending with 57/57
8. `08_compliance_tiers.png` — `/app/compliance` permission-tier console

---

## Step 4 — A broker-side trace (only if you have it)

If your Alpaca **paper** account is connected, one screenshot of its order history showing the paper fill that matches a trade ID in your log is strong corroboration. Blank out the account number. If the deployment ran in `DRY_RUN`, the fills are simulated — say "simulated fill" in the caption rather than implying a broker order.

---

## Step 5 — Package and submit

```
evidence/
  live_e2e_results.json
  LIVE_VERIFICATION_REPORT.md
  test_live_e2e.py
  adversarial_stress_results.json
  unit_test_run.log
  screenshots/…
```

Submit alongside the other deliverables:

| # | Deliverable | Where |
| :--- | :--- | :--- |
| 01 | Technical documentation | `docs/TECHNICAL_DOCUMENTATION.md` (export to PDF if the form wants one) |
| 02 | Presentation deck (≤ 10 min) | separate |
| 03 | Demo video (≤ 5 min, optional) | link from Step 2 |
| 04 | Source code | GitHub repo + `README.md` + tests |
| 05 | Security self-assessment | `SECURITY_SELF_ASSESSMENT.md` |
| 06 | Execution evidence | `evidence/` + video |

Export Markdown to PDF with: `npx md-to-pdf docs/TECHNICAL_DOCUMENTATION.md` (mermaid diagrams won't render there — take screenshots from the GitHub preview, or use <https://mermaid.live>).

## Final pre-submission checklist

- [ ] Live site loads and `/health` is `ok`
- [ ] `evidence/` regenerated *after* the last code push, 57/57 (or whatever the true number is)
- [ ] Video link opens in a private window
- [ ] No secrets in repo: `git ls-files | Select-String "\.env$"` returns nothing but `.env.example`
- [ ] Production `SECRET_KEY` and `AUDIT_SECRET_KEY` are set on Render (not the dev defaults — `RISK-08`)
- [ ] An email provider is set on Render (`BREVO_API_KEY` + verified `EMAIL_FROM`) and a Red-tier trade's code arrives
- [ ] `OTP_DEV_ECHO` is **not** set on Render (production refuses to start with it)
- [ ] Any anchoring claim in the deck/video matches reality (`RISK-09`)
