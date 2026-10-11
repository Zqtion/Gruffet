"""The agent decision layer: compact 'disagreement cards' for borderline leads.

The coding agent (Claude Code, Codex, ...) is the LLM, so no API key is involved. It reads
only these short cards, never raw pages, and answers with `gruffet resolve`.
"""
from __future__ import annotations

from .store import Store
from .util import est_tokens


def _vals(store: Store, lid: str, field: str, n: int = 3) -> str:
    out = []
    for v in store.values(lid, field)[:n]:
        fam = "+".join(sorted(store.families_for(lid, field, v)))
        out.append(f"{v} [{fam}]")
    return ", ".join(out) or "-"


def card(store: Store, row) -> str:
    lid = row["id"]
    g = store.gates(lid)
    open_gates = "; ".join(f"{k}={v['status']} ({v['detail']})" for k, v in g.items()
                           if v["status"] != "pass" and k not in ("phone_corroborated", "email_verified"))
    title = (store.values(lid, "meta.title") or [""])[0][:80]
    return (f"[{lid}] {row['name']} | {row['category'] or '?'} | score {row['score']}\n"
            f"  open: {open_gates or 'none'}\n"
            f"  site: {', '.join(store.values(lid, 'website')[:1]) or '-'} | title: {title or '-'}\n"
            f"  phone: {_vals(store, lid, 'phone')} | email: {_vals(store, lid, 'email')}\n")


def cards(store: Store, limit: int = 20, budget: int = 1500) -> str:
    rows = store.leads("review")
    if not rows:
        return "No leads awaiting review."
    out, used = [], 0
    for i, row in enumerate(rows[:limit]):
        c = card(store, row)
        t = est_tokens(c)
        if used + t > budget and out:
            out.append(f"... {len(rows) - i} more review leads (raise --budget or --limit)")
            break
        out.append(c)
        used += t
    else:
        if len(rows) > limit:
            out.append(f"... {len(rows) - limit} more review leads (raise --limit)")
    out.append("Decide each with: gruffet resolve <id> accept|reject --reason \"...\"")
    return "\n".join(out)


def evidence(store: Store, lid: str, budget: int = 1200) -> str:
    row = store.lead(lid)
    if not row:
        return f"No lead {lid}"
    lines = [f"[{lid}] {row['name']} | tier {row['tier']} | score {row['score']} | {row['tier_reason']}"]
    for k, v in store.gates(lid).items():
        lines.append(f"  gate {k}: {v['status']} - {v['detail']}")
    for c in store.claims(lid):
        if c["field"] == "meta.text_sample":
            continue
        lines.append(f"  {c['field']}: {c['value'][:120]}  <{c['source'][:70]}> {c['label']}")
    text, used = [], 0
    for ln in lines:
        used += est_tokens(ln)
        if used > budget:
            text.append("  ... truncated (raise --budget)")
            break
        text.append(ln)
    return "\n".join(text)


def missing_cards(store: Store, limit: int = 25, budget: int = 1200) -> str:
    """Leads with no website: the agent can web-search for it, then `gruffet add`."""
    rows = [r for r in store.leads(("incomplete", "review")) if not store.values(r["id"], "website")]
    if not rows:
        return "No leads are missing a website."
    out, used = [], 0
    for r in rows[:limit]:
        addr = (store.values(r["id"], "address") or [""])[0]
        line = f"[{r['id']}] {r['name']} | {r['category'] or '?'} | {addr[:70] or 'no address'} | {r['lat']:.4f},{r['lon']:.4f}"
        used += est_tokens(line)
        if used > budget and out:
            out.append(f"... {len(rows) - len(out)} more (raise --budget/--limit)")
            break
        out.append(line)
    out.append('For each: web-search the official site, then `gruffet add <id> website <url> --note "web search"`; '
               "afterwards run `gruffet enrich` and `gruffet verify`. The gates still check it is really this business.")
    return "\n".join(out)


def add_fact(store: Store, lid: str, field: str, value: str, source_url: str | None = None, note: str = "") -> str:
    """Agent-supplied evidence. Website needs no source; contact facts must cite the page they came from,
    so they count as an independent source family ('ext') during cross-checking."""
    from .util import norm_phone, normalize_url
    from .extract import _email_ok
    lead = store.lead(lid)
    if not lead:
        raise KeyError(lid)
    if field == "website":
        v = normalize_url(value)
        if not v:
            raise ValueError(f"not a valid URL: {value!r}")
        store.add_claim(lid, "website", v, f"agent:{note or 'manual'}", "INFERRED")
    elif field in ("phone", "email", "address"):
        src = normalize_url(source_url)
        if not src:
            raise ValueError(f"adding a {field} requires --source-url (the page where you saw it)")
        if field == "phone":
            v = norm_phone(value, lead["region"] or store.get_meta("region"))
            if not v:
                raise ValueError(f"not a valid phone number: {value!r}")
        elif field == "email":
            v = value.strip().lower()
            if not _email_ok(v):
                raise ValueError(f"not a valid email: {value!r}")
        else:
            v = value.strip()
        store.add_claim(lid, field, v, f"ext:{src}", "INFERRED")
    else:
        raise ValueError("field must be website, phone, email or address")
    store.commit()
    return v


def resolve(store: Store, lid: str, decision: str, reason: str, rename: str | None = None) -> str:
    """Record the agent's verdict. `rename` fixes a stale name (the business is the same but trades
    under a new name); the old name is kept as a `former_name` claim so re-discovery doesn't duplicate it."""
    from .util import norm_name
    assert decision in ("accept", "reject")
    row = store.lead(lid)
    if not row:
        raise KeyError(lid)
    if rename and decision == "accept" and rename.strip() != row["name"]:
        store.add_claim(lid, "former_name", row["name"], "agent:resolve", "EXTRACTED")
        store.add_claim(lid, "name", rename.strip(), "agent:resolve", "INFERRED")
        store.db.execute("UPDATE leads SET name=?, name_norm=? WHERE id=?", (rename.strip(), norm_name(rename), lid))
        store.commit()
    if decision == "accept" and row["tier"] not in ("review", "agent-approved"):
        raise ValueError(f"{lid} is '{row['tier']}' ({row['tier_reason']}); only review leads can be accepted. "
                         f"Add evidence with `gruffet add`, then re-run enrich and verify.")
    store.set_verdict(lid, decision, reason)
    tier = "agent-approved" if decision == "accept" else "reject"
    store.set_tier(lid, row["score"], tier, f"agent {decision}ed: {reason}")
    return tier
