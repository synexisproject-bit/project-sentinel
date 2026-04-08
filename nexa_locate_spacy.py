#!/usr/bin/env python3
import argparse, re, sys, json
import pandas as pd
import spacy

# --- light dictionaries for normalization ---
COUNTRIES = {
 "united states":"US","u.s.":"US","usa":"US","america":"US","canada":"CA","mexico":"MX","united kingdom":"GB","england":"GB",
 "ireland":"IE","france":"FR","germany":"DE","spain":"ES","portugal":"PT","italy":"IT","switzerland":"CH","austria":"AT",
 "netherlands":"NL","belgium":"BE","norway":"NO","sweden":"SE","finland":"FI","denmark":"DK","iceland":"IS","poland":"PL",
 "czech republic":"CZ","czechia":"CZ","slovakia":"SK","hungary":"HU","romania":"RO","bulgaria":"BG","greece":"GR","turkey":"TR",
 "russia":"RU","ukraine":"UA","estonia":"EE","latvia":"LV","lithuania":"LT","china":"CN","japan":"JP","south korea":"KR","india":"IN",
 "malaysia":"MY","singapore":"SG","indonesia":"ID","philippines":"PH","thailand":"TH","vietnam":"VN","australia":"AU","new zealand":"NZ",
 "brazil":"BR","argentina":"AR","chile":"CL","peru":"PE","colombia":"CO","egypt":"EG","morocco":"MA","kenya":"KE","south africa":"ZA",
 "israel":"IL","jordan":"JO","lebanon":"LB","united arab emirates":"AE","uae":"AE","qatar":"QA","oman":"OM","saudi arabia":"SA"
}
US_STATES = {
 "alabama":"AL","alaska":"AK","arizona":"AZ","arkansas":"AR","california":"CA","colorado":"CO","connecticut":"CT","delaware":"DE",
 "florida":"FL","georgia":"GA","hawaii":"HI","idaho":"ID","illinois":"IL","indiana":"IN","iowa":"IA","kansas":"KS","kentucky":"KY",
 "louisiana":"LA","maine":"ME","maryland":"MD","massachusetts":"MA","michigan":"MI","minnesota":"MN","mississippi":"MS","missouri":"MO",
 "montana":"MT","nebraska":"NE","nevada":"NV","new hampshire":"NH","new jersey":"NJ","new mexico":"NM","new york":"NY",
 "north carolina":"NC","north dakota":"ND","ohio":"OH","oklahoma":"OK","oregon":"OR","pennsylvania":"PA","rhode island":"RI",
 "south carolina":"SC","south dakota":"SD","tennessee":"TN","texas":"TX","utah":"UT","vermont":"VT","virginia":"VA","washington":"WA",
 "west virginia":"WV","wisconsin":"WI","wyoming":"WY",
 # common abbreviations (lowercased)
 "al":"AL","ak":"AK","az":"AZ","ar":"AR","ca":"CA","co":"CO","ct":"CT","de":"DE","fl":"FL","ga":"GA","hi":"HI","id":"ID","il":"IL","in":"IN",
 "ia":"IA","ks":"KS","ky":"KY","la":"LA","me":"ME","md":"MD","ma":"MA","mi":"MI","mn":"MN","ms":"MS","mo":"MO","mt":"MT","ne":"NE","nv":"NV",
 "nh":"NH","nj":"NJ","nm":"NM","ny":"NY","nc":"NC","nd":"ND","oh":"OH","ok":"OK","or":"OR","pa":"PA","ri":"RI","sc":"SC","sd":"SD","tn":"TN",
 "tx":"TX","ut":"UT","vt":"VT","va":"VA","wa":"WA","wv":"WV","wi":"WI","wy":"WY"
}
STOP_SINGLE = set("""
ok okay well however then here there somewhere nowhere anywhere today yesterday tomorrow
morning evening night noon church school home hospital store cafe café river lake ocean
mountain valley beach street road avenue sights smells ufo ufos january february march
april may june july august september october november december
""".split())

def clean_text(s:str)->str:
    return re.sub(r"\s+"," ", (s or "").strip())

def is_trivial(tok:str)->bool:
    t = re.sub(r"[^a-z]+","", tok.lower())
    return (t in STOP_SINGLE) or (len(t) <= 2)

def attach_country_admin(token_lower:str):
    # country names
    if token_lower in COUNTRIES: 
        return "", COUNTRIES[token_lower]  # (admin1, country)
    # US states
    if token_lower in US_STATES:
        return US_STATES[token_lower], "US"
    return "", ""

def extract_locations_spacy(nlp, text:str):
    """
    Returns list of (name, label, score, admin1, country)
    """
    if not text or not text.strip(): return []
    doc = nlp(text)
    out = []

    # spaCy NER: prefer GPE > LOC > FAC
    base_scores = {"GPE":0.95, "LOC":0.90, "FAC":0.85}
    for ent in doc.ents:
        if ent.label_ not in base_scores: 
            continue
        name = clean_text(ent.text)
        lower = name.lower()
        if is_trivial(lower):
            continue
        admin1, country = attach_country_admin(lower)
        out.append((name, ent.label_, base_scores[ent.label_], admin1, country))

    # Light regex for "in/at/near/from <Title Case ...>"
    for m in re.finditer(r"\b(?:in|at|near|from)\s+([A-Z][A-Za-z]+(?:[ -][A-Z][A-Za-z]+){0,3})\b", text):
        name = clean_text(m.group(1))
        lower = name.lower()
        if is_trivial(lower):
            continue
        admin1, country = attach_country_admin(lower)
        out.append((name, "RGX", 0.80, admin1, country))

    # dedupe: keep highest score per normalized name
    best = {}
    for name, lbl, sc, adm, ctry in out:
        k = name.lower()
        if (k not in best) or (sc > best[k][1]):
            best[k] = (name, sc, lbl, adm, ctry)

    # sort by score
    final = sorted([(v[0], v[2], v[1], v[3], v[4]) for v in best.values()], key=lambda x: x[2], reverse=True)
    return final

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True)   # xlsx (paired-down precognition file)
    ap.add_argument("--sheet", default=0)
    ap.add_argument("--id-col", default="Respondent ID")
    ap.add_argument("--text-col", default="Please describe your ONE specific and remarkable noetic experience.")
    ap.add_argument("--out", required=True)                 # CSV output
    ap.add_argument("--hi-out", default="")
    ap.add_argument("--min-conf", type=float, default=0.90)
    args = ap.parse_args()

    nlp = spacy.load("en_core_web_sm", disable=["tagger","lemmatizer","textcat","parser"])  # NER only

    df = pd.read_excel(args.infile, sheet_name=args.sheet)
    for c in [args.id_col, args.text-col if False else args.text_col]:
        if c not in df.columns:
            print(f"ERROR: missing column: {c}", file=sys.stderr)
            sys.exit(2)

    rows = []
    for _, r in df.iterrows():
        rid = r[args.id_col]
        text = clean_text(r.get(args.text_col, ""))
        hits = extract_locations_spacy(nlp, text)

        # best guess
        best_city = ""
        best_admin = ""
        best_country = ""
        best_conf = 0.0

        for name, lbl, score, adm, ctry in hits:
            # take first decent GPE/LOC/FAC as "city-ish"
            if not best_city and lbl in ("GPE","LOC","FAC"):
                best_city = name
                best_admin = adm
                best_country = ctry
                best_conf = score
            # fill missing country/admin from dictionaries if later hits provide them
            if not best_country and ctry:
                best_country = ctry
            if not best_admin and adm:
                best_admin = adm

        rows.append({
            "respondent_id": rid,
            "loc_candidates": "; ".join([f"{n}({lbl},{sc:.2f})" for n,lbl,sc,_,_ in hits]),
            "loc_top_name": best_city,
            "loc_top_admin1": best_admin,
            "loc_top_country": best_country,
            "loc_confidence": round(best_conf,3),
        })

    out = pd.DataFrame(rows)
    out.to_csv(args.out, index=False)

    if args.hi_out:
        hi = out[(out["loc_top_name"].str.len() > 0) & (out["loc_confidence"] >= args.min_conf)].copy()
        hi.to_csv(args.hi_out, index=False)

    # quick summary to stdout
    total = len(out)
    hi_n = int(((out["loc_top_name"].str.len() > 0) & (out["loc_confidence"] >= args.min_conf)).sum())
    print(json.dumps({
        "rows": total,
        "with_any_location": int((out["loc_top_name"].str.len() > 0).sum()),
        "high_conf_threshold": args.min_conf,
        "high_conf_count": hi_n
    }, indent=2))
if __name__ == "__main__":
    main()
