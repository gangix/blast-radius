# Blast Radius — Demo Video Script (<3 min)

## Prep (before recording)
- DataHub up (`localhost:9002`) + cloudflared tunnel running.
- ❌ / ⚠️ / ✅ PR comments already posted (don't film the ~2-min run wait).
- Tabs open, in order:
  1. PR #1 **diff** (removed `discount_amount` line)
  2. PR #1 **comment** (❌)
  3. DataHub `order_details` **Lineage** tab (downstream expanded — click "Show More")
  4. DataHub `order_details` **Schema** tab (the `blast-radius-breaking` tag on `discount_amount`)
  5. the write-back **knowledge doc**
  6. PR #2 (⚠️)
  7. PR #3 (✅)
- Browser zoom ~110–125%. Record 1080p. **Don't show secrets / the tunnel URL.**

---

## 0:00–0:10 — COLD OPEN ("the innocent one-liner")
**Screen:** PR #1 diff, frozen on the red `- discount_amount,` line. Slow push-in or static.
**Overlay text**, one line at a time:
> One line.
> Two broken finance dashboards.
> Nobody in this PR knows yet.

**VO (calm, let it breathe):**
> "This one-line change is about to break the revenue report. It passes every test. And nothing in this pull request can see it coming."

Hard cut → **Title card: BLAST RADIUS — the pre-merge guardian for data teams.**

## 0:10–0:45 — THE BOT ANSWERS
**Screen:** PR #1 comment (❌), scroll slowly.
**VO:**
> "Blast Radius is a GitHub bot that answers that at review time. Breaking change. Dropping `discount_amount` hits two production finance queries — run eleven times a day by two people — and it feeds three dashboards and twelve charts. None of it is guessed. Every fact comes from DataHub."

## 0:45–1:05 — PROVE IT'S REAL
**Screen:** DataHub **Lineage** tab — pan the downstream fan-out; then back to the comment → expand a `SQL —` block.
**VO:**
> "And it's real — here's the actual downstream lineage in DataHub, the dashboards and charts hanging off this table. These are real production queries too — you can see it reads `discount_amount` right here in the SQL."

## 1:05–1:35 — WRITE-BACK (strongest beat)
**Screen:** DataHub `discount_amount` column with the `blast-radius-breaking` tag → then the knowledge doc.
**VO:**
> "And it doesn't just comment and forget — it writes the finding back into DataHub. Here's the `blast-radius-breaking` tag it put on the column, and a knowledge doc linked to the pull request. So the next person who opens this table in the catalog inherits the warning. The agent contributes back to the graph."

## 1:35–2:10 — NOT A NAYSAYER
**Screen:** PR #2 (⚠️) briefly, then PR #3 (✅).
**VO:**
> "It's not a naysayer. Rename a column one query still reads — a warning, review before merge. And the important case: dropping `gift_wrap`. Same table, feeds all those dashboards — but no query has read `gift_wrap` in thirty days, so it says: safe to merge. Severity is weighted by real usage, not raw node counts."

## 2:10–2:35 — HOW IT WORKS + CLOSE
**Screen:** README architecture diagram, then the demo repo.
**VO:**
> "Deterministic core, DataHub as the source of truth, the Agent Context Kit to read lineage and write back, shipped as a GitHub Action. Impossible without a context platform. Blast Radius — know what breaks, before you merge."

**End card:** `github.com/gangix/blast-radius`

---

## If over 3:00
Trim the "how it works" VO first — never the ❌ comment (0:10–0:45) or the write-back beat (1:05–1:35). Those two are the must-keeps.

## Overlay text checklist (cold open)
- "One line." / "Two broken finance dashboards." / "Nobody in this PR knows yet."
- Title: BLAST RADIUS — the pre-merge guardian for data teams
- End card: github.com/gangix/blast-radius
