"""Build the ZATCA VAT Mistakes Rulebook as a self-contained, themed HTML page.
Reads docs/VAT-Mistakes-Rulebook.md, produces docs/rulebook-page.html (Artifact-ready:
no <html>/<head>/<body> wrappers; <title>+<style> at top, content, <script> at end).
"""
import re
import html as _html
import markdown

ROOT = r"C:\projects\E-AUDIT"
SRC = ROOT + r"\docs\VAT-Mistakes-Rulebook.md"
OUT = ROOT + r"\docs\rulebook-page.html"

md_text = open(SRC, encoding="utf-8").read()

# --- purpose sentence (the lede) ---------------------------------------------
m = re.search(r"\*\*Purpose\.\*\*\s*(.+?)(?:\n\n|\Z)", md_text, re.S)
purpose = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
purpose = re.sub(r"`([^`]+)`", r"\1", purpose)  # drop code ticks for the lede
purpose = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", purpose)  # drop **bold** / *italic* markers

# --- parse the summary table -------------------------------------------------
lines = md_text.splitlines()
rules = []
in_tbl = False
for ln in lines:
    if ln.strip().startswith("## Summary table"):
        in_tbl = True
        continue
    if in_tbl:
        if ln.strip().startswith("## ") or ln.strip() == "---":
            if rules:  # table ended
                break
            continue
        if ln.strip().startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) < 5:
                continue
            code = cells[0]
            if code.lower() == "code" or set(code) <= set("-: "):
                continue  # header / separator
            if not re.match(r"^[A-Z]{2,4}-\d", code):
                continue
            rules.append({
                "code": code,
                "title": cells[1],
                "family": cells[2],
                "gap": cells[3],
                "sev": cells[4],
            })

def sev_band(s):
    t = re.split(r"[ (/\u2013\u2014-]", s.strip(), 1)[0].lower()
    return t if t in ("high", "medium", "low") else "medium"

def gap_band(g):
    gl = g.strip().lower()
    if gl.startswith("yes"):
        return "yes"
    if gl.startswith("partial"):
        return "partial"
    return "no"

families = []
for r in rules:
    if r["family"] not in families:
        families.append(r["family"])

gap_count = sum(1 for r in rules if gap_band(r["gap"]) in ("yes", "partial"))

# --- build cards -------------------------------------------------------------
def gap_label(g):
    gl = g.strip()
    if gap_band(g) == "no":
        reason = re.sub(r"^No\s*", "", gl).strip("() ")
        return "no", ("No direct gap" + (" · " + reason if reason else ""))
    # Yes / Partial → keep the arrow target
    return gap_band(g), gl.replace("->", "\u2192")

cards = []
for r in rules:
    sb = sev_band(r["sev"])
    gb, glabel = gap_label(r["gap"])
    text = " ".join([r["code"], r["title"], r["family"], r["gap"], r["sev"]]).lower()
    cards.append(
        f'<a class="card sev-{sb} gap-{gb}" href="#rule-{r["code"]}" '
        f'data-family="{_html.escape(r["family"])}" data-sev="{sb}" data-gap="{gb}" '
        f'data-text="{_html.escape(text, quote=True)}">'
        f'<div class="card-top"><span class="code">{_html.escape(r["code"])}</span>'
        f'<span class="fam">{_html.escape(r["family"])}</span></div>'
        f'<h3 class="card-title">{_html.escape(r["title"])}</h3>'
        f'<div class="card-badges">'
        f'<span class="badge gap-{gb}">{_html.escape(glabel)}</span>'
        f'<span class="pill sev-{sb}">{_html.escape(r["sev"])}</span>'
        f'</div></a>'
    )
cards_html = "\n".join(cards)

# --- family + severity chips -------------------------------------------------
fam_chips = "".join(
    f'<button class="chip" data-facet="family" data-val="{_html.escape(f)}">{_html.escape(f)}</button>'
    for f in families
)
sev_chips = "".join(
    f'<button class="chip sevchip sev-{s}" data-facet="sev" data-val="{s}">{lab}</button>'
    for s, lab in (("high", "High"), ("medium", "Medium"), ("low", "Low"))
)
gap_chips = "".join(
    f'<button class="chip" data-facet="gap" data-val="{v}">{lab}</button>'
    for v, lab in (("yes", "Explains a gap"), ("partial", "Partial"), ("no", "No direct gap"))
)

# --- full reference (detail) -------------------------------------------------
# start at Legend; drop the leading title/purpose (shown in the hero)
li = md_text.find("## Legend")
detail_md = md_text[li:] if li != -1 else md_text
# remove the summary-table section (cards replace it)
st = detail_md.find("## Summary table")
if st != -1:
    nxt = detail_md.find("\n## ", st + 3)
    detail_md = detail_md[:st] + (detail_md[nxt:] if nxt != -1 else "")

detail_html = markdown.markdown(
    detail_md, extensions=["tables", "fenced_code", "sane_lists", "attr_list", "md_in_html"]
)

# inject anchors: prefer a structural occurrence (heading / bold / table cell)
for r in rules:
    code = r["code"]
    anchor = f'<span id="rule-{code}" class="anchor"></span>'
    pat = re.compile(r"(<(?:h[1-6]|strong|td)[^>]*>\s*)(" + re.escape(code) + r")")
    if pat.search(detail_html):
        detail_html = pat.sub(lambda mo: mo.group(1) + anchor + mo.group(2), detail_html, count=1)
    else:
        detail_html = detail_html.replace(code, anchor + code, 1)

# --- assemble ----------------------------------------------------------------
CSS = r"""
:root{
  --brand:#0E6B57; --brand-deep:#0A4C40; --brand-tint:#E6F0EB;
  --gold:#A9803F;
  --bg:#EDF2EF; --surface:#FFFFFF; --surface-2:#F5F9F7; --raise:#FFFFFF;
  --ink:#14201C; --muted:#5B6A63; --faint:#8A968F; --line:#DCE6E0;
  --high:#B23A36; --high-bg:#F7E7E6; --med:#A9761E; --med-bg:#F6EDDD; --low:#2C7A58; --low-bg:#E2F0E9;
  --shadow:0 1px 2px rgba(16,40,32,.05), 0 8px 24px -14px rgba(16,40,32,.18);
  --radius:14px;
  --sans:ui-sans-serif,system-ui,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --brand:#3FB79A; --brand-deep:#2C8C76; --brand-tint:#132A23;
  --gold:#C9A15C;
  --bg:#0C1310; --surface:#131C18; --surface-2:#0F1713; --raise:#16211B;
  --ink:#E9F1EC; --muted:#9BADA4; --faint:#6E7E76; --line:#243029;
  --high:#E4736E; --high-bg:#2A1917; --med:#D6A44E; --med-bg:#28211320; --med-bg:#241D12; --low:#5FC496; --low-bg:#122A20;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 10px 30px -16px rgba(0,0,0,.6);
}}
:root[data-theme="dark"]{
  --brand:#3FB79A; --brand-deep:#2C8C76; --brand-tint:#132A23;
  --gold:#C9A15C;
  --bg:#0C1310; --surface:#131C18; --surface-2:#0F1713; --raise:#16211B;
  --ink:#E9F1EC; --muted:#9BADA4; --faint:#6E7E76; --line:#243029;
  --high:#E4736E; --high-bg:#2A1917; --med:#D6A44E; --med-bg:#241D12; --low:#5FC496; --low-bg:#122A20;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 10px 30px -16px rgba(0,0,0,.6);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--brand);text-underline-offset:2px}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}

/* topbar */
.topbar{position:sticky;top:0;z-index:40;background:color-mix(in srgb,var(--surface) 88%, transparent);
  backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--line)}
.topbar .wrap{display:flex;align-items:center;gap:14px;height:60px}
.brand{display:flex;align-items:center;gap:11px;font-weight:700;letter-spacing:.2px}
.mark{width:30px;height:30px;border-radius:8px;background:linear-gradient(145deg,var(--brand),var(--brand-deep));
  display:grid;place-items:center;color:#fff;font-weight:800;font-size:13px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.12)}
.brand small{display:block;font-weight:500;color:var(--muted);letter-spacing:.3px;font-size:11.5px;margin-top:1px}
.brand b{font-size:15px}
.grow{flex:1}
.tbtn{border:1px solid var(--line);background:var(--surface-2);color:var(--muted);border-radius:9px;
  height:34px;padding:0 12px;font:inherit;font-size:13px;cursor:pointer;display:inline-flex;align-items:center;gap:7px}
.tbtn:hover{color:var(--ink);border-color:var(--brand)}
.topbar::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;
  background:linear-gradient(90deg,var(--brand),var(--gold) 70%,transparent)}

/* hero */
.hero{padding:46px 0 30px}
.eyebrow{font-size:12px;font-weight:600;letter-spacing:1.6px;text-transform:uppercase;color:var(--brand);margin:0 0 12px}
.hero h1{font-size:clamp(28px,4vw,42px);line-height:1.08;margin:0 0 14px;letter-spacing:-.02em;text-wrap:balance;font-weight:750}
.lede{max-width:74ch;color:var(--muted);font-size:16.5px;line-height:1.6;margin:0}
.stats{display:flex;flex-wrap:wrap;gap:14px;margin-top:26px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:130px;box-shadow:var(--shadow)}
.stat .n{font-size:26px;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.stat .l{font-size:12px;color:var(--muted);margin-top:2px}
.stat.accent .n{color:var(--brand)}

/* controls */
.controls{position:sticky;top:60px;z-index:30;background:color-mix(in srgb,var(--bg) 92%,transparent);
  backdrop-filter:blur(6px);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:14px 0}
.controls .wrap{display:flex;flex-wrap:wrap;align-items:center;gap:12px}
.search{position:relative;flex:1;min-width:220px}
.search input{width:100%;height:40px;border:1px solid var(--line);background:var(--surface);color:var(--ink);
  border-radius:10px;padding:0 14px 0 38px;font:inherit;font-size:14px}
.search input:focus{outline:2px solid var(--brand);outline-offset:1px;border-color:transparent}
.search svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--faint)}
.chips{display:flex;flex-wrap:wrap;gap:7px}
.chip{border:1px solid var(--line);background:var(--surface);color:var(--muted);border-radius:999px;
  padding:7px 13px;font:inherit;font-size:12.5px;cursor:pointer;transition:.12s;white-space:nowrap}
.chip:hover{color:var(--ink);border-color:var(--brand)}
.chip[aria-pressed="true"]{background:var(--brand);border-color:var(--brand);color:#fff}
.chip.sevchip[aria-pressed="true"]{color:#fff}
.chip.sev-high[aria-pressed="true"]{background:var(--high);border-color:var(--high)}
.chip.sev-medium[aria-pressed="true"]{background:var(--med);border-color:var(--med)}
.chip.sev-low[aria-pressed="true"]{background:var(--low);border-color:var(--low)}
.facet-label{font-size:11px;letter-spacing:.5px;text-transform:uppercase;color:var(--faint);margin-right:2px;align-self:center}
.rescount{margin-left:auto;font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
.rescount b{color:var(--ink)}
.clearbtn{border:none;background:none;color:var(--brand);font:inherit;font-size:13px;cursor:pointer;text-decoration:underline}

/* cards */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px;padding:26px 0 8px}
.card{display:flex;flex-direction:column;gap:10px;background:var(--surface);border:1px solid var(--line);
  border-left:4px solid var(--line);border-radius:var(--radius);padding:15px 16px;text-decoration:none;color:inherit;
  box-shadow:var(--shadow);transition:transform .12s, border-color .12s}
.card:hover{transform:translateY(-2px);border-color:var(--brand);border-left-color:var(--brand)}
.card.sev-high{border-left-color:var(--high)} .card.sev-medium{border-left-color:var(--med)} .card.sev-low{border-left-color:var(--low)}
.card-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.code{font-family:var(--mono);font-size:12.5px;font-weight:600;color:var(--brand);letter-spacing:.3px}
.fam{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}
.card-title{font-size:15.5px;line-height:1.32;margin:0;font-weight:650;letter-spacing:-.01em}
.card-badges{display:flex;flex-wrap:wrap;gap:7px;margin-top:auto}
.badge{font-size:11.5px;padding:4px 9px;border-radius:7px;font-weight:600;line-height:1.3}
.badge.gap-yes,.badge.gap-partial{background:var(--brand-tint);color:var(--brand-deep)}
:root[data-theme="dark"] .badge.gap-yes,:root[data-theme="dark"] .badge.gap-partial{color:var(--brand)}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]) .badge.gap-yes,:root:not([data-theme="light"]) .badge.gap-partial{color:var(--brand)}}
.badge.gap-partial{outline:1px dashed color-mix(in srgb,var(--brand) 45%, transparent);outline-offset:-1px;background:transparent}
.badge.gap-no{background:var(--surface-2);color:var(--faint)}
.pill{font-size:11.5px;padding:4px 10px;border-radius:999px;font-weight:650}
.pill.sev-high{background:var(--high-bg);color:var(--high)} .pill.sev-medium{background:var(--med-bg);color:var(--med)} .pill.sev-low{background:var(--low-bg);color:var(--low)}
.empty{grid-column:1/-1;text-align:center;color:var(--muted);padding:50px 0}

/* reference */
.reference{padding:34px 0 10px;border-top:1px solid var(--line);margin-top:26px}
.ref-head{display:flex;align-items:baseline;gap:12px;margin-bottom:6px}
.ref-head h2{font-size:22px;margin:0;letter-spacing:-.01em}
.ref-head span{color:var(--muted);font-size:13.5px}
.doc{max-width:100%}
.doc h2{font-size:20px;margin:34px 0 10px;padding-top:14px;border-top:1px solid var(--line);letter-spacing:-.01em}
.doc h2:first-child{border-top:none;padding-top:0;margin-top:8px}
.doc h3{font-size:16.5px;margin:22px 0 6px}
.doc h4{font-size:15px;margin:18px 0 6px;color:var(--brand-deep)}
:root[data-theme="dark"] .doc h4{color:var(--brand)}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]) .doc h4{color:var(--brand)}}
.doc p{max-width:78ch;color:var(--ink)}
.doc strong{font-weight:680}
.doc code{font-family:var(--mono);font-size:12.5px;background:var(--surface-2);border:1px solid var(--line);
  border-radius:5px;padding:1px 5px}
.doc a{font-weight:500}
.doc ul,.doc ol{max-width:78ch}
.doc li{margin:4px 0}
.doc hr{border:none;border-top:1px solid var(--line);margin:26px 0}
.tablescroll,.doc :is(table){display:block;overflow-x:auto}
.doc table{width:100%;border-collapse:collapse;margin:14px 0;font-size:13.5px;min-width:520px}
.doc th,.doc td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
.doc th{background:var(--surface-2);font-weight:650;position:sticky;top:0;white-space:nowrap}
.doc tr:hover td{background:var(--surface-2)}
.anchor{position:relative;top:-84px;visibility:hidden}
:target{scroll-margin-top:90px}
.doc span[id^="rule-"]+*, .doc :is(h3,h4,strong):has(+ .anchor){}

footer{border-top:1px solid var(--line);margin-top:40px;padding:26px 0 48px;color:var(--muted);font-size:13px}
footer .wrap{display:flex;flex-wrap:wrap;gap:10px 22px;align-items:center}
footer .note{max-width:70ch}
.kbd{font-family:var(--mono);font-size:11px;background:var(--surface-2);border:1px solid var(--line);border-radius:5px;padding:1px 6px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
@media (max-width:640px){.hero{padding:34px 0 22px}.controls{top:60px}.doc table{min-width:440px}}
"""

TITLE = "ZATCA VAT Mistakes Rulebook"

page = []
page.append(f"<title>{TITLE}</title>")
page.append("<style>" + CSS + "</style>")

page.append('<header class="topbar"><div class="wrap">'
            '<div class="brand"><span class="mark">ZC</span>'
            '<span><b>ZATCA VAT Audit Agent</b><small>Rule Library</small></span></div>'
            '<span class="grow"></span>'
            '<button class="tbtn" id="themeBtn" aria-label="Toggle theme">'
            '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
            '<span id="themeLbl">Theme</span></button>'
            '</div></header>')

page.append('<main>')
page.append('<section class="hero"><div class="wrap">'
            '<p class="eyebrow">VAT Audit Agent \u00b7 Detection rules</p>'
            '<h1>VAT Mistakes Rulebook</h1>'
            f'<p class="lede">{_html.escape(purpose)}</p>'
            '<div class="stats">'
            f'<div class="stat"><div class="n">{len(rules)}</div><div class="l">Detection rules</div></div>'
            f'<div class="stat"><div class="n">{len(families)}</div><div class="l">Mistake families</div></div>'
            f'<div class="stat accent"><div class="n">{gap_count}</div><div class="l">Explain an e-invoice &#8596; filing gap</div></div>'
            '</div></div></section>')

page.append('<section class="controls"><div class="wrap">'
            '<div class="search">'
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>'
            '<input id="q" type="search" placeholder="Search rules \u2014 e.g. reverse charge, late filing, credit note, Box 9\u2026" autocomplete="off"></div>'
            '<div class="chips"><span class="facet-label">Family</span>' + fam_chips + '</div>'
            '<div class="chips"><span class="facet-label">Severity</span>' + sev_chips + '</div>'
            '<div class="chips"><span class="facet-label">Gap</span>' + gap_chips + '</div>'
            '<span class="rescount"><b id="shown">' + str(len(rules)) + '</b> / ' + str(len(rules)) + ' rules '
            '<button class="clearbtn" id="clear" hidden>clear</button></span>'
            '</div></section>')

page.append('<div class="wrap">')
page.append('<section class="cards" id="cards">' + cards_html +
            '<div class="empty" id="empty" hidden>No rules match \u2014 <button class="clearbtn" id="clear2">clear filters</button></div>'
            '</section>')

page.append('<section class="reference"><div class="ref-head"><h2>Full reference</h2>'
            '<span>every rule in detail \u2014 detection logic, evidence, and the gap it explains</span></div>'
            '<div class="doc">' + detail_html + '</div></section>')
page.append('</div>')  # /wrap
page.append('</main>')

page.append('<footer><div class="wrap"><span class="note">'
            'Detection is deterministic \u2014 the engine reconstructs the expected return from cleared e-invoices and names every difference; '
            'AI only reads and narrates free text; a human auditor approves every finding. These rules are the content behind '
            '<code>config.rule_library</code> and each maps to a <code>ROOT_CAUSE_CODE</code>.'
            '</span></div></footer>')

JS = r"""
(function(){
  var root=document.documentElement;
  // theme toggle: cycle system -> light -> dark
  var btn=document.getElementById('themeBtn'), lbl=document.getElementById('themeLbl');
  function label(){var t=root.getAttribute('data-theme');lbl.textContent=t?(t[0].toUpperCase()+t.slice(1)):'Theme';}
  btn.addEventListener('click',function(){
    var t=root.getAttribute('data-theme');
    root.setAttribute('data-theme', t==='dark'?'light':(t==='light'?'':'dark'));
    if(!root.getAttribute('data-theme'))root.removeAttribute('data-theme');
    label();
  });
  label();

  var q=document.getElementById('q'), cards=[].slice.call(document.querySelectorAll('.card'));
  var facets={family:new Set(),sev:new Set(),gap:new Set()};
  var shown=document.getElementById('shown'), empty=document.getElementById('empty');
  var clearBtns=[document.getElementById('clear'),document.getElementById('clear2')];

  function apply(){
    var term=(q.value||'').trim().toLowerCase();
    var n=0;
    cards.forEach(function(c){
      var ok=true;
      if(term && c.getAttribute('data-text').indexOf(term)<0) ok=false;
      if(ok && facets.family.size && !facets.family.has(c.getAttribute('data-family'))) ok=false;
      if(ok && facets.sev.size && !facets.sev.has(c.getAttribute('data-sev'))) ok=false;
      if(ok && facets.gap.size && !facets.gap.has(c.getAttribute('data-gap'))) ok=false;
      c.style.display=ok?'':'none'; if(ok)n++;
    });
    shown.textContent=n;
    empty.hidden=n>0;
    var active=term||facets.family.size||facets.sev.size||facets.gap.size;
    clearBtns.forEach(function(b){if(b)b.hidden=!active;});
  }
  q.addEventListener('input',apply);
  document.querySelectorAll('.chip').forEach(function(ch){
    ch.addEventListener('click',function(){
      var f=ch.getAttribute('data-facet'), v=ch.getAttribute('data-val');
      var on=ch.getAttribute('aria-pressed')==='true';
      ch.setAttribute('aria-pressed', on?'false':'true');
      if(on)facets[f].delete(v); else facets[f].add(v);
      apply();
    });
  });
  function clearAll(){
    q.value='';
    facets={family:new Set(),sev:new Set(),gap:new Set()};
    document.querySelectorAll('.chip').forEach(function(c){c.setAttribute('aria-pressed','false');});
    apply();
  }
  clearBtns.forEach(function(b){if(b)b.addEventListener('click',clearAll);});
})();
"""
page.append("<script>" + JS + "</script>")

open(OUT, "w", encoding="utf-8").write("\n".join(page))
print("wrote", OUT)
print("rules parsed:", len(rules), "| families:", families, "| explains-gap:", gap_count)
