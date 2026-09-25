from urllib.parse import urlencode
from io import BytesIO
from urllib.request import Request, urlopen
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import json
import urllib.parse
import urllib.request
import urllib.error
import re
import html
import base64
import mimetypes
from urllib.parse import urlencode, urlparse, parse_qs, quote

# ---------- MANUAL MOT APPRAISAL ----------
MOT_COST_RULES=[(("tyre","tire"),90,180,"Tyre"),(("brake pad","brake pads","brake disc","brake discs"),180,450,"Brakes"),(("suspension","spring","coil spring","shock absorber"),180,500,"Suspension"),(("exhaust","emissions"),150,500,"Exhaust / emissions"),(("windscreen","windshield"),120,350,"Windscreen"),(("lamp","light","bulb"),20,120,"Lighting"),(("wiper","washer"),20,100,"Wipers / washers"),(("corrosion","corroded","rust"),250,1000,"Corrosion"),(("oil leak","fluid leak"),100,500,"Leak"),(("bearing","wheel bearing"),150,350,"Wheel bearing"),(("ball joint","bush","bushing"),120,350,"Steering / suspension joint")]
def analyse_mot_notes(notes):
    text=(notes or "").lower(); hits=[]; low=high=0; seen=set()
    for words,lo,hi,label in MOT_COST_RULES:
        if any(w in text for w in words) and label not in seen:
            hits.append(label); low+=lo; high+=hi; seen.add(label)
    return {"items":hits,"low":low,"high":high,"planning":round((low+high)/2) if hits else 0}
def mot_time_adjustment(months_remaining):
    m=int(months_remaining)
    if m>=9:return 0
    if m>=6:return -50
    if m>=3:return -150
    if m>=1:return -250
    return -350



def scaled_appraisal_adjustments(year, market_value, condition_grade, service_history, keys, mot_months):
    """DG appraisal assumptions scaled by vehicle age and current market value.
    These are heuristics, not claimed observed market discounts.
    """
    try: year=int(year)
    except (TypeError,ValueError): year=2020
    try: value=max(0.0,float(market_value or 0))
    except (TypeError,ValueError): value=0.0
    age=max(0,2026-year)

    # Age/value severity: newer and higher-value stock carries more retail sensitivity.
    if age<=3: age_factor=1.55
    elif age<=6: age_factor=1.30
    elif age<=10: age_factor=1.00
    elif age<=15: age_factor=0.72
    else: age_factor=0.55

    if value>=30000: value_factor=1.60
    elif value>=20000: value_factor=1.40
    elif value>=12000: value_factor=1.20
    elif value>=7000: value_factor=1.00
    elif value>=4000: value_factor=0.80
    else: value_factor=0.65

    context=age_factor*value_factor

    grade_base={1:0,2:0,3:-175,4:-450,5:-900}.get(int(condition_grade or 2),0)
    history_base={"Full":0,"Part":-225,"None":-500,"Unknown":-300}.get(str(service_history),-300)
    keys_base={"2+ keys":0,"1 key":-125,"Unknown":-100}.get(str(keys),-100)

    grade=int(round(grade_base*context/25.0)*25)
    service=int(round(history_base*context/25.0)*25)
    # Keys scale less aggressively than condition/history because replacement cost is not proportional to vehicle value.
    key_context=max(0.75,min(1.60,(age_factor*0.45)+(value_factor*0.55)))
    key_adj=int(round(keys_base*key_context/25.0)*25)

    # MOT term matters more as a car ages; under 3 years old, don't penalise solely for MOT term.
    try: m=int(mot_months)
    except (TypeError,ValueError): m=12
    if age<3:
        mot=0
    else:
        base=0 if m>=9 else (-50 if m>=6 else (-150 if m>=3 else (-250 if m>=1 else -350)))
        mot_age_factor=0.70 if age<=5 else (0.90 if age<=9 else (1.00 if age<=14 else 1.10))
        mot=int(round(base*mot_age_factor/25.0)*25)

    def why(adj_type, amount):
        if amount==0: return "No default deduction for this selection."
        age_text="young" if age<=5 else ("mid-age" if age<=10 else "older")
        value_text="high-value" if value>=20000 else ("mid-value" if value>=7000 else "lower-value")
        if adj_type=="keys": return f"Scaled moderately for a {age_text}, {value_text} car; key cost is not assumed to rise directly with vehicle value."
        if adj_type=="mot": return f"Scaled mainly by vehicle age ({age} years), because short MOT generally matters more to older stock."
        return f"Scaled for vehicle age ({age} years) and current market value (~£{value:,.0f})."
    return {
        "age":age,"value":value,"context":context,
        "condition":grade,"service":service,"keys":key_adj,"mot":mot,
        "condition_reason":why("condition",grade),
        "service_reason":why("service",service),
        "keys_reason":why("keys",key_adj),
        "mot_reason":why("mot",mot)
    }


def safe_market_snapshot(market, fallback_retail=0):
    """Return a safe market dict while preserving live-market metadata."""
    try:
        fallback=float(fallback_retail or 0)
    except (TypeError,ValueError):
        fallback=0.0
    if not isinstance(market,dict):
        return {"count":0,"low":fallback,"high":fallback,"retail":fallback,"average":fallback,"rows":[]}
    snap=dict(market)
    def num(key,default):
        try:
            return float(snap.get(key,default) or default)
        except (TypeError,ValueError,AttributeError):
            return float(default)
    try:
        count=int(snap.get("count",0) or 0)
    except (TypeError,ValueError,AttributeError):
        count=0
    rows=snap.get("rows",[])
    if not isinstance(rows,list):
        rows=[]
    snap["count"]=max(0,count)
    snap["low"]=num("low",fallback)
    snap["high"]=num("high",fallback)
    snap["retail"]=num("retail",fallback)
    snap["average"]=num("average",snap["retail"])
    snap["rows"]=rows
    return snap

def weighted_mot_history_cost(mot_notes_cost, mot_months):
    """If more than 4 months MOT remains, retain only 15% of prior-MOT note cost weighting."""
    try: cost=max(0.0,float(mot_notes_cost or 0))
    except (TypeError,ValueError): cost=0.0
    try: months=int(mot_months or 0)
    except (TypeError,ValueError): months=0
    weight=0.15 if months>4 else 1.0
    return round(cost*weight,2), weight

def dg_buyer_overview(market_average,recommended_retail,asking,max_buy,category,category_adjustment,condition_grade,service_history,keys,mot_months,mot_analysis,mot_notes_cost,prep,other_costs,contingency,target_margin,comp_count,market_low,market_high):
    out=[]
    # Defensive normalization: Streamlit reruns/session state can carry older values.
    if not isinstance(mot_analysis, dict):
        mot_analysis={"items":[],"low":0,"high":0,"planning":0}
    mot_items=mot_analysis.get("items",[])
    if isinstance(mot_items,str): mot_items=[mot_items] if mot_items.strip() else []
    elif not isinstance(mot_items,(list,tuple,set)): mot_items=[]
    try: mot_months=int(mot_months or 0)
    except (TypeError,ValueError): mot_months=0
    gap=asking-max_buy
    out.append(("Buying position",f"Seller is £{abs(gap):,.0f} {'above' if gap>0 else 'inside'} DG's maximum buy. "+("At the current assumptions the asking price does not leave the target contribution." if gap>0 else "This leaves room before unrecorded defects.")))
    if category!="Clear / none known": out.append(("Insurance category",f"{category} already reduces retail by £{abs(category_adjustment):,.0f}. DG view: verify repair quality/provenance and expect a smaller buyer pool than an equivalent clear-history car."))
    out.append(("MOT",f"Entered notes flag {', '.join(str(x) for x in mot_items) or 'no automatically recognised repair category'}. Current advisory allowance £{mot_notes_cost:,.0f}. DG view: confirm actual repair prices before buying."))
    motview="plan on a fresh MOT before retail" if mot_months<3 else ("stock time may leave it needing a fresh MOT" if mot_months<6 else "no major short-MOT concern from term alone")
    out.append(("MOT remaining",f"About {mot_months} month(s): {motview}."))
    out.append(("Inputs",f"Condition {condition_grade}/5 · service history {service_history} · keys {keys} · prep £{prep:,.0f} · other costs £{other_costs:,.0f} · contingency £{contingency:,.0f}."))
    if comp_count<=1: out.append(("Market / stock risk",f"Only {comp_count} close comparable is available. There is not enough evidence for a reliable range or genuine days-to-sell estimate."))
    elif comp_count<5: out.append(("Market / stock risk",f"Only {comp_count} close comparables. DG view: valuation and exit-speed confidence are low; no genuine days-to-sell figure is available."))
    else:
        pct=((market_high-market_low)/market_average*100) if market_average else 0
        out.append(("Market / stock risk",f"{comp_count} close comparables with about {pct:.0f}% asking-price spread. This indicates pricing uncertainty, not measured days-to-sell."))
    out.append(("Retail",f"Live average £{market_average:,.0f} · DG retail £{recommended_retail:,.0f} · target contribution £{target_margin:,.0f}."))
    return out

def extract_source_advert(text):
    text=(text or "").strip()
    if not text:return {}
    out={"raw":text}
    u=re.search(r'https?://[^\s]+',text)
    if u:out["url"]=u.group(0).rstrip(").,]")
    q=re.search(r'£\s*([\d,]+)',text)
    if q:out["price"]=int(q.group(1).replace(",",""))
    m=re.search(r'(\d{1,3}(?:,\d{3})+|\d{4,6})\s*(?:miles|mile|mi)\b',text,re.I)
    if m:out["mileage"]=int(m.group(1).replace(",",""))
    return out



REPAIR_RULES=[
("Camshaft / valvetrain",["needs camshaft","camshaft needs","camshaft fault","camshaft worn","camshaft issue","camshaft problem","camshaft required","requires camshaft","camshaft noisy","camshaft noise","tappet noise","tappets noisy","top end tapping","top end rattle"],850,1800),
("Timing chain",["timing chain rattle","timing chain fault","needs timing chain","timing chain needs","chain rattle","rattle on startup","rattles on startup","rattle from cold","rattles from cold","rattle when cold"],700,1600),
("Timing belt",["needs timing belt","needs cambelt","timing belt due","cambelt due","cambelt overdue","timing belt overdue"],350,750),
("Head gasket / overheating",["head gasket","headgasket","mixing oil and coolant","mayo under cap","mayonnaise under cap","overheating","over heats","overheats","pressurising coolant","pressurizing coolant","bubbles in expansion tank"],900,2200),
("Turbo",["turbo fault","turbo failed","needs turbo","turbo needs","turbo gone","turbo blown","turbo whistle","turbo whining","no boost","losing boost","boost fault","underboost"],650,1600),
("Clutch",["clutch slipping","needs clutch","clutch needs","clutch fault","clutch gone","clutch is gone","high biting point","clutch bites high","clutch judder","clutch judders","hard to get into gear"],500,1100),
("Dual-mass flywheel / clutch",["dual mass","dmf","needs flywheel","flywheel rattle","flywheel noisy","rattle when clutch"],850,1600),
("Automatic gearbox",["gearbox fault","gearbox issue","transmission fault","gearbox slipping","broken gearbox","gearbox broken","gearbox gone","gearbox has gone","gearbox failed","gearbox failure","needs gearbox","new gearbox needed","gearbox noisy","gearbox noise","gearbox whining","gearbox whine","gearbox crunch","gearbox crunching","crunches gears","won't select gear","wont select gear","not selecting gear","stuck in gear","jumps out of gear","transmission slipping","transmission failed","transmission gone","limp mode gearbox"],1200,3200),
("Engine internal / knocking",["engine knocking","engine knock","knocking engine","bottom end knock","bottom end knocking","big end knock","big end gone","rod knock","engine rattling","engine rattle","engine seized","seized engine","engine gone","engine blown","blown engine","needs engine","replacement engine needed"],1200,3500),
("Misfire / running fault",["misfire","misfiring","misfires","running rough","runs rough","rough idle","lumpy idle","lumpy when cold","hesitates","hesitation","stuttering","stutters","down on power","loss of power","losing power"],120,800),
("Engine management / warning light",["engine management light","eml on","eml light","check engine light","engine light on","warning light on","management light on"],100,650),
("Oil leak / oil consumption",["oil leak","leaking oil","loses oil","losing oil","uses oil","using oil","burning oil","burns oil","heavy oil consumption","needs topping up with oil"],150,1000),
("Coolant leak / cooling",["coolant leak","leaking coolant","losing coolant","loses coolant","uses coolant","water leak","radiator leak","expansion tank leak","needs topping up coolant"],150,900),
("Smoke / exhaust",["blue smoke","white smoke","black smoke","smokes when cold","smokes on startup","smokes under acceleration","smoking engine","excessive smoke"],200,1200),
("DPF",["dpf fault","dpf blocked","blocked dpf","dpf issue","dpf light","dpf warning","dpf needs cleaning","regeneration fault","won't regenerate","wont regenerate"],250,900),
("EGR",["egr fault","egr issue","needs egr","egr valve","egr light"],250,650),
("AdBlue / emissions",["adblue fault","adblue issue","adblue warning","adblue countdown","emissions fault","emissions warning","scr fault","nox sensor"],250,1100),
("Alternator / charging",["needs alternator","alternator fault","alternator failed","battery light on","not charging","charging fault"],300,650),
("Starter motor",["needs starter","starter motor fault","starter failed","starter clicking","clicks but won't start","clicks but wont start"],250,550),
("Starting fault",["won't start","wont start","non starter","non-starter","doesn't start","doesnt start","hard to start","struggles to start","turns over but won't start","cranks but won't start"],150,1200),
("Air conditioning",["air con not working","aircon not working","a/c not working","ac not working","air con warm","aircon warm","needs regas","needs re-gas"],100,700),
("Front brakes",["front brakes needed","needs front brakes","front discs and pads","front pads and discs","front brakes need doing","front discs worn","front pads low"],250,500),
("Rear brakes",["rear brakes needed","needs rear brakes","rear discs and pads","rear pads and discs","rear brakes need doing","rear discs worn","rear pads low"],220,450),
("Brakes",["brakes needed","needs brakes","discs and pads","pads and discs","brakes need doing","brakes require attention","brake judder","brakes judder","brakes grinding","brake grinding","grinding brakes","squealing brakes","brakes squeal","brake warning light","brakes worn","pads low","discs worn"],350,700),
("ABS / stability control",["abs light","abs fault","traction control light","esp light","stability control fault"],150,700),
("Tyres - pair",["needs two tyres","2 tyres needed","two tyres needed","pair of tyres","two bald tyres","2 bald tyres"],180,360),
("Tyres - set",["needs four tyres","4 tyres needed","four tyres needed","needs tyres","tyres needed","tyres bald","bald tyres","tyres cracked","perished tyres","tyres perished","tyres low"],350,700),
("Wheel bearing",["wheel bearing","bearing noise","humming from wheel","wheel humming","drone from wheel","wheel bearing humming"],180,400),
("Suspension",["suspension knock","needs suspension","broken spring","coil spring","knocking suspension","suspension knocking","clunk over bumps","clunks over bumps","knock over bumps","knocks over bumps","spring snapped","snapped spring","shock leaking","leaking shock","bouncy suspension"],200,650),
("Steering",["steering knock","steering clunk","power steering fault","steering heavy","heavy steering","steering warning light","rack leaking","steering rack"],250,1200),
("Battery",["needs battery","battery weak","new battery needed","flat battery","battery keeps going flat","battery goes flat"],100,260),
("Electrical fault",["electrical fault","electrical issue","electrics playing up","intermittent electrical","windows not working","central locking not working","dashboard goes off"],100,900),
("Parking brake",["handbrake not working","handbrake weak","parking brake fault","electronic parking brake fault","epb fault"],150,650),
("Exhaust",["exhaust blowing","blowing exhaust","exhaust leak","exhaust broken","needs exhaust","exhaust rattling"],120,700),
("Catalytic converter",["catalytic converter fault","cat fault","needs catalytic converter","needs cat","catalyst efficiency","cat rattling"],300,1400),
("Rust / corrosion",["rusty underneath","rust underneath","bad rust","serious rust","corrosion underneath","welding needed","needs welding","sills rusty","rusty sills","subframe corrosion","subframe rusty"],300,1800),
("Water ingress",["water leak inside","water ingress","wet carpets","damp carpets","boot full of water","water in boot","leaking roof"],100,900),
("Convertible roof",["roof not working","convertible roof fault","soft top not working","hood not working","roof mechanism fault"],250,1600),
]
PREMIUM_BRANDS={"Porsche":1.75,"Ferrari":3.0,"Lamborghini":3.0,"Aston Martin":2.3,"Bentley":2.4,"Maserati":1.9,"Land Rover":1.45,"Jaguar":1.35,"Mercedes-Benz":1.35,"BMW":1.3,"Audi":1.3,"Lexus":1.2,"Volvo":1.15}
MODEL_MULTIPLIERS={("Porsche","911"):2.15,("Porsche","Cayenne"):1.75,("Porsche","Macan"):1.55,("BMW","M3"):1.65,("BMW","M4"):1.65,("Audi","RS3"):1.65,("Audi","RS4"):1.7,("Ford","Focus"):1.0,("Ford","Fiesta"):0.95,("Dacia","Sandero"):0.85}
def vehicle_repair_multiplier(make,model,spec=""):
    return max(.75,min(float(MODEL_MULTIPLIERS.get((str(make),str(model)),PREMIUM_BRANDS.get(str(make),1.0))),3.0))
def _repair_is_already_done(text,term):
    low=text.lower()
    # Don't penalise explicit negatives such as "no gearbox issues" or "no warning lights".
    pos=low.find(term)
    if pos>=0:
        prefix=low[max(0,pos-18):pos]
        if re.search(r"\b(no|without|never had|no sign of|no signs of)\s+$",prefix): return True
    for root in [x for x in term.split() if len(x)>=4]:
        if re.search(rf"(new|recent|recently|just)\s+[^.\n]{{0,45}}{re.escape(root)}[^.\n]{{0,45}}(fitted|replaced|done|changed|renewed|repaired|fixed)",low):return True
        if re.search(rf"{re.escape(root)}[^.\n]{{0,35}}(has been|was|recently|just)?\s*(fitted|replaced|renewed|changed|done|repaired|fixed)",low):return True
    return False
def analyse_description_repairs(text,make="",model="",spec=""):
    low=(text or "").lower().strip();mult=vehicle_repair_multiplier(make,model,spec)
    if not low:return {"items":[],"low":0,"high":0,"allowance":0,"multiplier":mult}
    found=[];families=set()
    for issue,terms,base_low,base_high in REPAIR_RULES:
        hit=next((t for t in terms if t in low),None)
        if not hit or _repair_is_already_done(low,hit):continue
        family="brakes" if "brake" in issue.lower() else ("tyres" if "tyre" in issue.lower() else issue.lower())
        if family in families and issue in ("Brakes","Tyres - set"):continue
        families.add(family);lo=int(round(base_low*mult/25)*25);hi=int(round(base_high*mult/25)*25);mid=int(round(((lo+hi)/2)/25)*25)
        found.append({"issue":issue,"low":lo,"high":hi,"allowance":mid,"evidence":hit})
    return {"items":found,"low":sum(x["low"] for x in found),"high":sum(x["high"] for x in found),"allowance":sum(x["allowance"] for x in found),"multiplier":mult}

def assess_seller_description(text, confirmed=None):
    """Risk-screen seller wording. Seller claims remain unverified."""
    text=(text or "").strip()
    confirmed=confirmed or {}
    if not text:
        return {"level":"Unknown","score":0,"flags":[],"positives":[],"questions":[],"conflicts":[]}
    low=text.lower(); flags=[]; positives=[]; questions=[]; conflicts=[]; score=0; seen=set()
    rules=[
        (3,["engine knock","knocking engine","head gasket","overheating","overheats","timing chain","timing belt snapped","gearbox fault","gearbox issue","clutch slipping","won't start","wont start","non runner","non-runner"],"Major mechanical wording","Get a firm diagnosis and repair cost before making an offer."),
        (2,["warning light","engine light","eml","management light","abs light","airbag light","limp mode","intermittent fault","sometimes cuts","occasionally cuts"],"Warning light / intermittent fault","Ask what warning is present, when it occurs and whether a diagnostic scan is available."),
        (2,["cat s","category s","cat n","category n","cat c","category c","cat d","category d","cat b","category b","cat a","category a","write off","write-off","insurance loss"],"Insurance-category wording","Verify the category, repair quality, invoices/photos and structural repair evidence where relevant."),
        (2,["no v5","lost v5","v5 missing","logbook missing","no logbook"],"V5C / ownership-document concern","Resolve keeper identity and V5C position before purchase."),
        (2,["selling for a friend","selling for friend","my mate's car","my mates car","for my brother","for my sister"],"Seller is not clearly the keeper","Establish who owns the car and why the keeper is not selling it directly."),
        (2,["spares or repair"],"Spares-or-repair wording","Treat the car as potentially requiring substantial work until inspected."),
        (1,["needs tlc","needs some tlc","project","sold as seen","quick sale","need gone","must go"],"Cautionary seller wording","Inspect carefully and price all unquantified work."),
        (1,["service due","needs service","overdue service","no service history","no history","part service history","partial service history"],"Service-history / maintenance concern","Check invoices, service record and overdue maintenance."),
        (1,["one key","1 key","single key","only key"],"Single-key wording","Confirm key count and replacement/programming cost."),
        (1,["tyres needed","needs tyres","tyre worn","brakes needed","needs brakes","discs and pads","suspension knock","wheel bearing"],"Likely consumable / MOT-related spend","Inspect the named items and replace generic allowances with real repair costs.")
    ]
    for pts,terms,label,q in rules:
        if any(term in low for term in terms) and label not in seen:
            seen.add(label); score+=pts; flags.append(label); questions.append(q)
    positives_rules=[
        (["full service history","full history","fsh"],"Seller claims full service history"),
        (["two keys","2 keys","both keys"],"Seller claims two keys"),
        (["recent service","just serviced","serviced recently"],"Seller claims recent servicing"),
        (["new mot","12 months mot","12 month mot","fresh mot"],"Seller claims a fresh/long MOT"),
        (["new tyres","recent tyres"],"Seller claims recent tyres"),
        (["new clutch","clutch replaced"],"Seller claims clutch replacement"),
        (["timing belt changed","cambelt changed","timing belt replaced","cambelt replaced"],"Seller claims timing-belt work")
    ]
    for terms,label in positives_rules:
        if any(term in low for term in terms): positives.append(label+" — verify evidence.")
    keys=str(confirmed.get("keys","")).lower()
    history=str(confirmed.get("service_history","")).lower()
    category=str(confirmed.get("category","")).lower()
    if any(x in low for x in ["one key","1 key","single key","only key"]) and ("2+" in keys or "2 key" in keys):
        conflicts.append("Advert appears to say one key, but appraisal says 2+ keys.")
    if ("full service history" in low or " fsh " in " "+low+" ") and any(x in history for x in ["none","part","unknown"]):
        conflicts.append("Advert claims full service history, but the appraisal selection does not.")
    if ("no service history" in low or "no history" in low) and "full" in history:
        conflicts.append("Advert suggests no service history, but appraisal says Full.")
    desc_cat=None
    for code in ["a","b","c","d","s","n"]:
        if f"cat {code}" in low or f"category {code}" in low:
            desc_cat=f"cat {code}"; break
    if desc_cat and desc_cat not in category:
        conflicts.append(f"Advert mentions {desc_cat.upper()}, but the appraisal category is different/unclear.")
    if conflicts: score+=2
    level="Low" if score<=1 else ("Medium" if score<=4 else "High")
    return {"level":level,"score":score,"flags":flags,"positives":positives,"questions":list(dict.fromkeys(questions)),"conflicts":conflicts}

st.set_page_config(page_title="DG Deal Finder", page_icon="🚘", layout="centered", initial_sidebar_state="collapsed")
DATA = Path(__file__).with_name("deals.csv")

st.markdown("""
<style>
:root{--navy:#0B1736;--blue:#1769E0;--ink:#172033;--muted:#697386;--bg:#F4F7FB;--card:#fff;--line:#E2E8F0;--green:#12805C;--greenbg:#EAF8F2;--amber:#A66400;--amberbg:#FFF6E6;--red:#B42318;--redbg:#FFF0EE}
.stApp{background:var(--bg)}.block-container{max-width:780px;padding:0 0 5rem!important}header[data-testid="stHeader"]{background:transparent}#MainMenu,footer{visibility:hidden}
html,body,[class*="css"]{font-family:Inter,system-ui,sans-serif;color:var(--ink)}
.dg-top{background:var(--navy);padding:20px 18px 18px;color:#fff}.dg-logo{font-size:1.08rem;font-weight:900;letter-spacing:-.025em}.dg-logo span{color:#70A9FF}.dg-tag{font-size:.72rem;color:#AAB8D4;margin-top:2px}
.dg-wrap{padding:0 14px}.dg-hero{padding:20px 0 12px}.eyebrow{font-size:.68rem;font-weight:800;letter-spacing:.13em;color:var(--blue);text-transform:uppercase}.hero{font-size:1.65rem;font-weight:900;letter-spacing:-.045em;color:var(--navy);line-height:1.05;margin:5px 0}.sub{font-size:.87rem;color:var(--muted);line-height:1.45}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:10px}.car{font-weight:900;font-size:1.12rem;color:var(--navy);letter-spacing:-.03em}.meta{color:var(--muted);font-size:.78rem;margin-top:2px}.label{font-size:.67rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:800}.section{font-size:1.08rem;font-weight:850;color:var(--navy);margin:18px 0 9px}
.chip{display:inline-block;border-radius:999px;padding:5px 9px;font-size:.72rem;font-weight:800;margin-top:8px}.good{background:var(--greenbg);color:var(--green)}.warn{background:var(--amberbg);color:var(--amber)}.bad{background:var(--redbg);color:var(--red)}
div[data-testid="stMetric"]{background:#fff;border:1px solid var(--line);border-radius:13px;padding:11px 12px}div[data-testid="stMetricLabel"]{font-size:.67rem;text-transform:uppercase;color:var(--muted)}div[data-testid="stMetricValue"]{font-size:1.2rem;font-weight:900;color:var(--navy)}
.stButton>button,.stFormSubmitButton>button,.stLinkButton>a,.stDownloadButton>button{border-radius:10px;min-height:46px;font-weight:800}.stFormSubmitButton>button{background:var(--blue)!important;color:#fff!important;border-color:var(--blue)!important}
div[data-testid="stTextInput"] input,div[data-testid="stNumberInput"] input,div[data-testid="stTextArea"] textarea,div[data-baseweb="select"]>div{background:#fff!important;border-color:var(--line)!important;border-radius:10px!important}
.stTabs [data-baseweb="tab-list"]{gap:2px;background:#fff;border-bottom:1px solid var(--line);padding:0 8px}.stTabs [data-baseweb="tab"]{height:48px;font-size:.76rem;font-weight:800;color:var(--muted);padding:0 9px}.stTabs [aria-selected="true"]{color:var(--blue)!important}
</style>
<div class="dg-top"><div class="dg-logo">DG <span>DEAL FINDER</span></div><div class="dg-tag">Vehicle sourcing intelligence</div></div>
""",unsafe_allow_html=True)

st.markdown(r"""
<style>
/* V4.1 mobile contrast + spacing repair */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background:#F6F8FC !important;
  color:#172033 !important;
}
.block-container{
  padding-top:0 !important;
  padding-left:0 !important;
  padding-right:0 !important;
}
.dg-wrap{padding-left:18px !important;padding-right:18px !important;}
.dg-top{display:block !important;background:#0B1736 !important;color:#fff !important;position:relative;z-index:2;}
.dg-top *{color:inherit !important}
.dg-logo span{color:#70A9FF !important}

/* Force Streamlit labels/help text to remain readable even when phone/browser is in dark mode */
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
.stTextInput label p,.stNumberInput label p,.stTextArea label p,
[data-testid="stSelectbox"] label p {
  color:#344054 !important;
  font-weight:700 !important;
  opacity:1 !important;
}
[data-testid="stCaptionContainer"] p {color:#697386 !important;}

/* Inputs */
input, textarea,
[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea {
  color:#172033 !important;
  -webkit-text-fill-color:#172033 !important;
  caret-color:#1769E0 !important;
  background:#FFFFFF !important;
}
input::placeholder, textarea::placeholder {
  color:#98A2B3 !important;
  -webkit-text-fill-color:#98A2B3 !important;
  opacity:1 !important;
}
[data-baseweb="input"], [data-baseweb="textarea"],
[data-baseweb="select"] > div {
  background:#FFFFFF !important;
  border-color:#D0D5DD !important;
  box-shadow:none !important;
}
[data-baseweb="input"]:focus-within,
[data-baseweb="textarea"]:focus-within {
  border-color:#1769E0 !important;
  box-shadow:0 0 0 2px rgba(23,105,224,.12) !important;
}
/* Number input +/- controls */
[data-testid="stNumberInput"] button {
  background:#F2F4F7 !important;
  color:#172033 !important;
  border-color:#D0D5DD !important;
}
[data-testid="stNumberInput"] button svg {fill:#172033 !important;color:#172033 !important;}

/* Tabs */
.stTabs [data-baseweb="tab-list"]{
  background:#FFFFFF !important;
  border-bottom:1px solid #E2E8F0 !important;
  padding:0 12px !important;
}
.stTabs [data-baseweb="tab"] p{color:#667085 !important;font-weight:800 !important;}
.stTabs [aria-selected="true"] p{color:#1769E0 !important;}

/* Reduce oversized mobile controls */
@media (max-width:640px){
  .dg-hero{padding-top:18px !important;}
  .hero{font-size:1.55rem !important;}
  div[data-baseweb="input"], div[data-baseweb="select"]>div{min-height:48px !important;}
  input{min-height:46px !important;font-size:16px !important;}
  [data-testid="stNumberInput"] button{width:46px !important;}
  .stTextInput,.stNumberInput,.stSelectbox,.stTextArea{margin-bottom:.2rem !important;}
}


/* V30 professional mobile buying-desk UI — large, thumb-friendly controls */
:root{
  --dg-navy:#071A2F; --dg-navy2:#102A43; --dg-blue:#1267D6; --dg-blue2:#0B57B7;
  --dg-bg:#F2F5F8; --dg-card:#FFFFFF; --dg-line:#D9E1E8; --dg-text:#122033; --dg-muted:#66788A;
}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:var(--dg-bg)!important}
.block-container{max-width:820px!important;padding-bottom:7rem!important}
.dg-top{background:linear-gradient(135deg,var(--dg-navy),var(--dg-navy2))!important;padding:18px 20px 20px!important;border-bottom:4px solid var(--dg-blue)!important;box-shadow:0 5px 18px rgba(7,26,47,.16)!important}
.dg-logo{font-size:1.18rem!important;letter-spacing:.01em!important}.dg-tag{font-size:.76rem!important;color:#C8D5E3!important}
.dg-wrap{padding-left:16px!important;padding-right:16px!important}.dg-hero{padding:18px 0 10px!important}.eyebrow{font-size:.69rem!important;letter-spacing:.12em!important}.hero{font-size:1.72rem!important;line-height:1.08!important}.sub{font-size:.9rem!important;max-width:620px}
.section{font-size:1.12rem!important;margin:24px 0 10px!important;letter-spacing:-.015em!important}
.card{border-radius:16px!important;border:1px solid var(--dg-line)!important;box-shadow:0 3px 12px rgba(20,40,65,.06)!important;padding:16px!important}
/* App-like segmented top navigation */
.stTabs [data-baseweb="tab-list"]{position:sticky!important;top:0!important;z-index:50!important;display:grid!important;grid-template-columns:repeat(4,1fr)!important;gap:6px!important;background:rgba(242,245,248,.97)!important;padding:10px 12px!important;border:0!important;backdrop-filter:blur(8px)!important}
.stTabs [data-baseweb="tab"]{height:52px!important;border-radius:12px!important;background:#E6ECF2!important;border:1px solid transparent!important;padding:0 5px!important}
.stTabs [data-baseweb="tab"] p{font-size:.72rem!important;color:#425466!important;font-weight:900!important;letter-spacing:.025em!important}
.stTabs [aria-selected="true"]{background:var(--dg-navy)!important;box-shadow:0 3px 8px rgba(7,26,47,.18)!important}.stTabs [aria-selected="true"] p{color:#fff!important}
/* Big BCA-style action buttons */
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button,.stLinkButton>a{
 min-height:56px!important;border-radius:13px!important;font-size:.92rem!important;font-weight:900!important;letter-spacing:.025em!important;border:1px solid #C9D4DF!important;box-shadow:0 2px 6px rgba(18,32,51,.08)!important;transition:.12s ease!important
}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:var(--dg-blue)!important;color:var(--dg-blue)!important;transform:translateY(-1px)}
.stFormSubmitButton>button{min-height:62px!important;background:linear-gradient(180deg,var(--dg-blue),var(--dg-blue2))!important;color:#fff!important;border:0!important;font-size:1rem!important;box-shadow:0 5px 14px rgba(18,103,214,.25)!important}
.stFormSubmitButton>button:active{transform:scale(.99)!important}
/* Form controls as large app tiles */
[data-testid="stWidgetLabel"] p{font-size:.79rem!important;color:#34495E!important;font-weight:850!important}
[data-baseweb="input"],[data-baseweb="textarea"],[data-baseweb="select"]>div{border:1px solid #C9D4DF!important;border-radius:12px!important;background:#fff!important;box-shadow:0 1px 3px rgba(18,32,51,.03)!important}
[data-baseweb="select"]>div{min-height:54px!important}input{min-height:52px!important}textarea{border-radius:12px!important;min-height:116px!important}
[data-testid="stNumberInput"] button{min-height:52px!important;min-width:48px!important}
/* Metrics/results become strong tiles */
div[data-testid="stMetric"]{border-radius:15px!important;border:1px solid var(--dg-line)!important;padding:14px 15px!important;box-shadow:0 3px 10px rgba(20,40,65,.055)!important}
div[data-testid="stMetricValue"]{font-size:1.34rem!important;letter-spacing:-.025em!important}
/* Expanders look like tappable menu rows */
[data-testid="stExpander"]{background:#fff!important;border:1px solid var(--dg-line)!important;border-radius:13px!important;overflow:hidden!important;margin:.4rem 0!important;box-shadow:0 2px 7px rgba(20,40,65,.04)!important}
[data-testid="stExpander"] summary{min-height:54px!important;font-weight:800!important;padding:0 14px!important}
/* Alerts */
[data-testid="stAlert"]{border-radius:13px!important;border-width:1px!important;padding:13px 14px!important}
/* Make radio/checkbox/toggle targets easier to hit */
[data-testid="stCheckbox"], [data-testid="stRadio"]{background:#fff;border-radius:12px;padding:6px 10px}
/* Desktop: keep clean single-column buying desk */
@media(min-width:700px){.dg-wrap{padding-left:22px!important;padding-right:22px!important}.stTabs [data-baseweb="tab-list"]{padding-left:18px!important;padding-right:18px!important}}
@media(max-width:640px){
 .block-container{padding-bottom:8rem!important}.dg-top{padding:15px 16px 17px!important}.hero{font-size:1.55rem!important}.sub{font-size:.84rem!important}
 .stTabs [data-baseweb="tab-list"]{gap:5px!important;padding:8px!important}.stTabs [data-baseweb="tab"]{height:50px!important}.stTabs [data-baseweb="tab"] p{font-size:.66rem!important}
 .stButton>button,.stDownloadButton>button,.stLinkButton>a{min-height:58px!important}.stFormSubmitButton>button{min-height:64px!important;font-size:1.02rem!important}
 [data-baseweb="select"]>div,input{min-height:54px!important;font-size:16px!important}
 div[data-testid="stMetric"]{padding:13px!important}
}

.market-note{border-radius:14px;padding:14px 16px;margin:10px 0 14px;border:1px solid #D5DEE8;background:#FFFFFF;color:#12233D;box-shadow:0 2px 7px rgba(20,40,65,.05)}
.market-note strong{display:block;font-size:.92rem;margin-bottom:3px;color:#0B1736}
.market-note.low{background:#FFF7E6;border-color:#E8B94F;color:#5B4210}
.market-note.low strong{color:#5B4210}
.market-note.good{background:#EAF7EF;border-color:#7CC596;color:#164B2A}
.market-note.good strong{color:#164B2A}
.market-note.bad{background:#FDECEC;border-color:#E39A9A;color:#742525}
.market-note.bad strong{color:#742525}


/* V30.8 — make the new-appraisal action unmistakable and readable */
[data-testid="stHorizontalBlock"]:has(button[kind="secondary"]) > [data-testid="column"]:last-child .stButton>button{
  background:#071A2F!important;
  color:#FFFFFF!important;
  border:2px solid #071A2F!important;
  box-shadow:0 5px 14px rgba(7,26,47,.20)!important;
}
[data-testid="stHorizontalBlock"]:has(button[kind="secondary"]) > [data-testid="column"]:last-child .stButton>button:hover{
  background:#102A43!important;
  color:#FFFFFF!important;
  border-color:#102A43!important;
}

/* V31 QoL: keep the main analyse action obvious on mobile */
@media (max-width:640px){
  [data-testid="stForm"] .stFormSubmitButton{
    position:sticky!important;
    bottom:10px!important;
    z-index:40!important;
    padding-top:8px!important;
  }
  [data-testid="stForm"] .stFormSubmitButton>button{
    box-shadow:0 8px 24px rgba(7,26,47,.28)!important;
  }
}
/* Faster-feeling UI: remove expensive decorative transitions on mobile */
@media (max-width:640px){
  .stButton>button,.stFormSubmitButton>button,.stDownloadButton>button,.stLinkButton>a{transition:none!important}
}

/* V33 — high-contrast save action */
.stButton>button[kind="primary"]{
  background:#176B45!important;
  color:#FFFFFF!important;
  border:2px solid #176B45!important;
  font-weight:800!important;
  box-shadow:0 5px 14px rgba(23,107,69,.22)!important;
}
.stButton>button[kind="primary"]:hover{
  background:#105638!important;
  color:#FFFFFF!important;
  border-color:#105638!important;
}

/* V36 readability fixes from mobile testing */
[data-testid="stAlert"][data-baseweb="notification"] p{color:#10233F!important;font-weight:650!important}
[data-testid="stAlert"][data-baseweb="notification"]{opacity:1!important}
.stButton>button[key="new_appraisal_btn"], .stButton>button:has(p:first-child){
  opacity:1;
}
/* Keep secondary action readable against dark navy */
[data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child .stButton>button{
  color:#FFFFFF!important;
}
[data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child .stButton>button p{
  color:#FFFFFF!important;
  opacity:1!important;
}

/* V39 mobile readability */
[data-testid="stAlert"] *, .stAlert * {color:#172033!important;opacity:1!important}
[data-testid="stAlert"] p, [data-testid="stAlert"] div {font-weight:650!important}
.st-key-new_appraisal_btn button,
.st-key-new_appraisal_btn button *,
button[kind="secondary"] p {opacity:1!important}
.st-key-new_appraisal_btn button {background:#111827!important;border-color:#111827!important;color:#FFFFFF!important}
.st-key-new_appraisal_btn button p {color:#FFFFFF!important}
</style>
""", unsafe_allow_html=True)

for k,v in {"min_profit":1000,"min_roi":25,"contingency_pct":20}.items():
    if k not in st.session_state: st.session_state[k]=v


def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

def at_configured():
    return bool(_secret("AUTOTRADER_API_BASE") and _secret("AUTOTRADER_ADVERTISER_ID") and _secret("AUTOTRADER_API_KEY"))

def at_request(path, params=None, method="GET", body=None):
    """Generic official Auto Trader Connect request wrapper.
    Endpoint paths/header names can be set in Streamlit Secrets to match the credentials issued to the account.
    """
    base=str(_secret("AUTOTRADER_API_BASE","")).rstrip("/")
    if not base:
        raise RuntimeError("Auto Trader API base URL is not configured.")
    url=base+"/"+path.lstrip("/")
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers={"Accept":"application/json","Content-Type":"application/json"}
    key=str(_secret("AUTOTRADER_API_KEY",""))
    header=str(_secret("AUTOTRADER_API_KEY_HEADER","Authorization"))
    prefix=str(_secret("AUTOTRADER_API_KEY_PREFIX","Bearer "))
    headers[header]=prefix+key
    extra=_secret("AUTOTRADER_EXTRA_HEADERS",{})
    if isinstance(extra,dict): headers.update({str(k):str(v) for k,v in extra.items()})
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=12) as r:
        return json.loads(r.read().decode())

def _find_num(obj, names):
    names={n.lower() for n in names}
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k.lower() in names and isinstance(v,(int,float)): return v
        for v in obj.values():
            x=_find_num(v,names)
            if x is not None: return x
    elif isinstance(obj,list):
        for v in obj:
            x=_find_num(v,names)
            if x is not None: return x
    return None

def fetch_at_vehicle(vrm,mileage):
    path=str(_secret("AUTOTRADER_VEHICLES_PATH","vehicles"))
    advertiser=str(_secret("AUTOTRADER_ADVERTISER_ID",""))
    params={"advertiserId":advertiser,"registration":vrm,"odometerReadingMiles":int(mileage),
            "valuations":"true","vehicleMetrics":"true"}
    return at_request(path,params=params)

def normalise_at(data):
    return {
      "retail":_find_num(data,["retail","retailValuation","retailValue"]),
      "trade":_find_num(data,["trade","tradeValuation","tradeValue"]),
      "private":_find_num(data,["private","privateValuation","privateValue"]),
      "part_exchange":_find_num(data,["partExchange","part_exchange","partExchangeValuation"]),
      "retail_rating":_find_num(data,["retailRating","retail_rating"]),
      "days_to_sell":_find_num(data,["daysToSell","days_to_sell"]),
      "supply":_find_num(data,["supply"]),
      "demand":_find_num(data,["demand"]),
      "market_condition":_find_num(data,["marketCondition","market_condition"]),
    }

def money(v):
    return "—" if v is None else f"£{v:,.0f}"

def metric_pct(v):
    if v is None: return "—"
    # API metrics are documented as decimals; tolerate already-percent values.
    return f"{(v*100 if abs(v)<=3 else v):.0f}%"






UK_MODEL_CATALOGUE={
"Abarth":["124 Spider","500","595","695"],
"Alfa Romeo":["Giulia","Giulietta","MiTo","Stelvio","Tonale"],
"Audi":["A1","A3","A4","A5","A6","A7","A8","Q2","Q3","Q5","Q7","Q8","TT"],
"BMW":["1 Series","2 Series","3 Series","4 Series","5 Series","6 Series","7 Series","8 Series","X1","X2","X3","X4","X5","X6","X7","Z4","i3","i4","iX"],
"Citroen":["Berlingo","C1","C2","C3","C3 Aircross","C4","C4 Cactus","C5","C5 Aircross","DS3"],
"Cupra":["Ateca","Born","Formentor","Leon","Tavascan"],
"Dacia":["Duster","Jogger","Logan","Sandero"],
"Fiat":["124 Spider","500","500L","500X","Bravo","Panda","Punto","Tipo"],
"Ford":["B-Max","C-Max","EcoSport","Edge","Fiesta","Focus","Galaxy","Grand C-Max","Ka","Ka+","Kuga","Mondeo","Mustang","Puma","Ranger","S-Max","Tourneo Connect","Transit Connect"],
"Honda":["Accord","Civic","CR-V","HR-V","Jazz"],
"Hyundai":["i10","i20","i30","i40","IONIQ","IONIQ 5","Kona","Santa Fe","Tucson"],
"Jaguar":["E-Pace","F-Pace","F-Type","I-Pace","XE","XF","XJ","XK"],
"Jeep":["Avenger","Cherokee","Compass","Grand Cherokee","Renegade","Wrangler"],
"Kia":["Ceed","Niro","Optima","Picanto","ProCeed","Rio","Sorento","Soul","Sportage","Stinger","Stonic","XCeed"],
"Land Rover":["Defender","Discovery","Discovery Sport","Freelander","Range Rover","Range Rover Evoque","Range Rover Sport","Range Rover Velar"],
"Lexus":["CT","ES","GS","IS","LC","LS","NX","RC","RX","UX"],
"Mazda":["2","3","6","CX-3","CX-30","CX-5","MX-5"],
"Mercedes-Benz":["A-Class","B-Class","C-Class","CLA","CLS","E-Class","GLA","GLB","GLC","GLE","GLS","S-Class","SL","SLK"],
"MG":["3","4","5","GS","HS","MG ZS","ZS EV"],
"MINI":["Clubman","Convertible","Countryman","Hatch"],
"Mitsubishi":["ASX","Eclipse Cross","L200","Mirage","Outlander","Shogun"],
"Nissan":["Juke","Leaf","Micra","Note","Pathfinder","Pulsar","Qashqai","X-Trail"],
"Peugeot":["107","108","2008","207","208","3008","308","5008","508","RCZ"],
"Porsche":["718 Boxster","718 Cayman","911","Cayenne","Macan","Panamera","Taycan"],
"Renault":["Captur","Clio","Kadjar","Koleos","Megane","Scenic","Twingo","Zoe"],
"SEAT":["Alhambra","Arona","Ateca","Ibiza","Leon","Mii","Tarraco"],
"Skoda":["Citigo","Fabia","Kamiq","Karoq","Kodiaq","Octavia","Rapid","Scala","Superb","Yeti"],
"Smart":["ForFour","ForTwo"],
"Subaru":["BRZ","Forester","Impreza","Legacy","Outback","XV"],
"Suzuki":["Alto","Baleno","Celerio","Ignis","Jimny","S-Cross","Swift","Vitara"],
"Tesla":["Model 3","Model S","Model X","Model Y"],
"Toyota":["Auris","Aygo","C-HR","Corolla","GT86","Prius","RAV4","Supra","Yaris","Yaris Cross"],
"Vauxhall":["Adam","Astra","Corsa","Crossland","Grandland","Insignia","Meriva","Mokka","Viva","Zafira"],
"Volkswagen":["Arteon","Beetle","Caddy","Golf","ID.3","ID.4","Passat","Polo","Scirocco","Sharan","T-Cross","T-Roc","Tiguan","Touareg","Touran","Up"],
"Volvo":["C30","C40","S40","S60","S80","S90","V40","V50","V60","V70","V90","XC40","XC60","XC70","XC90"]
}

def free_models_for_make_year(make, year):
    # Embedded catalogue makes the selector reliable on Streamlit and avoids
    # a network call every time a user changes the dropdown.
    return UK_MODEL_CATALOGUE.get(make, [])


# ---- Official UK bulk vehicle catalogue ------------------------------------
# DfT/DVLA df_VEH0270: first registrations by make, generic model, detailed
# model, fuel and engine-size band. This is a bulk government CSV, cached once;
# it is not queried per vehicle like an API.
DFT_UK_CATALOGUE_URL="https://assets.publishing.service.gov.uk/media/69ef3ecf9ca985145673b9ec/df_VEH0270.csv"

def _display_make(value):
    raw=str(value or "").strip()
    aliases={"BMW":"BMW","MG":"MG","MINI":"MINI","DS":"DS","SEAT":"SEAT","KIA":"Kia",
             "SKODA":"Skoda","MERCEDES-BENZ":"Mercedes-Benz","ALFA ROMEO":"Alfa Romeo",
             "LAND ROVER":"Land Rover","ASTON MARTIN":"Aston Martin","ROLLS-ROYCE":"Rolls-Royce"}
    return aliases.get(raw.upper(),raw.title())


# DG verified historical catalogue. Entries are deliberately year-bounded.
# Source basis for Porsche Cayman:
# 2007-08 Cayman 2.7; Cayman S 3.4. 2009-12 Cayman 2.9; Cayman S 3.4.
# 2013-16 981 Cayman 2.7; Cayman S/GTS 3.4; GT4 3.8 (2015-16).
# 718 four-cylinder 2.0/2.5 begins from 2016 model generation, never backfilled.
DG_YEAR_RULES=[
 {"make":"Porsche","model":"Cayman","start":2006,"end":2008,"fuel":"Petrol",
  "specs":{"Cayman":["2.7L Flat-6"],"Cayman S":["3.4L Flat-6"]}},
 {"make":"Porsche","model":"Cayman","start":2009,"end":2012,"fuel":"Petrol",
  "specs":{"Cayman":["2.9L Flat-6"],"Cayman S":["3.4L Flat-6"],"Cayman R":["3.4L Flat-6"]}},
 {"make":"Porsche","model":"Cayman","start":2013,"end":2014,"fuel":"Petrol",
  "specs":{"Cayman":["2.7L Flat-6"],"Cayman S":["3.4L Flat-6"]}},
 {"make":"Porsche","model":"Cayman","start":2015,"end":2016,"fuel":"Petrol",
  "specs":{"Cayman":["2.7L Flat-6"],"Cayman S":["3.4L Flat-6"],"Cayman GTS":["3.4L Flat-6"],"Cayman GT4":["3.8L Flat-6"]}},
 {"make":"Porsche","model":"Cayman","start":2017,"end":2018,"fuel":"Petrol",
  "specs":{"718 Cayman":["2.0L Turbo Flat-4"],"718 Cayman S":["2.5L Turbo Flat-4"],"718 Cayman GTS":["2.5L Turbo Flat-4"]}},
]

def dg_year_rule(make,model,year,fuel=""):
    mk=str(make or "").strip().lower(); md=str(model or "").strip().lower()
    y=int(year or 0)
    for r in DG_YEAR_RULES:
        if r["make"].lower()==mk and r["model"].lower()==md and r["start"]<=y<=r["end"]:
            if fuel and str(r.get("fuel","")).lower()!=str(fuel).lower(): continue
            return r
    return None

def dg_year_specs(make,model,year,fuel=""):
    r=dg_year_rule(make,model,year,fuel)
    return list(r["specs"].keys()) if r else []

def dg_year_engines(make,model,year,fuel="",spec=""):
    r=dg_year_rule(make,model,year,fuel)
    if not r:return []
    if spec and spec in r["specs"]: return list(r["specs"][spec])
    vals=[]
    for engines in r["specs"].values(): vals=_merge_unique(vals,engines)
    return vals


def reliable_year_choices(official_specs,official_engines,dg_specs,dg_engines,tax_specs,tax_engines,taxonomy_verified):
    """Universal safety gate for all manufacturers.
    Broad model-level fallback is intentionally excluded."""
    specs=_merge_unique(official_specs,dg_specs)
    engines=_merge_unique(official_engines,dg_engines)
    source=[]
    if official_specs or official_engines: source.append("DfT year evidence")
    if dg_specs or dg_engines: source.append("DG verified year rule")
    if taxonomy_verified:
        if not specs: specs=_merge_unique(tax_specs)
        if not engines: engines=_merge_unique(tax_engines)
        if tax_specs or tax_engines: source.append("exact taxonomy")
    return specs,engines,source

def catalogue_confidence(specs,engines):
    if specs and engines:return "verified"
    if specs or engines:return "partial"
    return "unverified"

MODEL_ALIASES={
 ("PORSCHE","CAYMAN"):["CAYMAN","718 CAYMAN"],("PORSCHE","718 CAYMAN"):["CAYMAN","718 CAYMAN"],
 ("PORSCHE","BOXSTER"):["BOXSTER","718 BOXSTER"],("PORSCHE","718 BOXSTER"):["BOXSTER","718 BOXSTER"],
}
def model_aliases(make,model):
    mk=str(make or "").strip().upper(); md=str(model or "").strip().upper()
    return {str(x).strip().upper() for x in MODEL_ALIASES.get((mk,md),[md]) if str(x).strip()}
def _official_model_mask(df,make,model):
    aliases=model_aliases(make,model)
    vals=df.apply(lambda r:_dft_model_name(r.get("Make",""),r.get("GenModel","")).upper(),axis=1)
    return vals.isin(aliases)
def friendly_model_name(make,value):
    x=str(value or "").strip()
    if str(make or "").strip().upper()=="PORSCHE" and x.upper()=="718 CAYMAN": return "Cayman"
    if str(make or "").strip().upper()=="PORSCHE" and x.upper()=="718 BOXSTER": return "Boxster"
    return x
def lookup_model_name(make,model):
    if str(make or "").strip().upper()=="PORSCHE" and str(model or "").strip().upper()=="CAYMAN": return "718 Cayman"
    if str(make or "").strip().upper()=="PORSCHE" and str(model or "").strip().upper()=="BOXSTER": return "718 Boxster"
    return model

def _dft_model_name(make,gen_model):
    x=str(gen_model or "").strip()
    mk=str(make or "").strip()
    if x.upper().startswith(mk.upper()+" "): x=x[len(mk):].strip()
    return x

def _dft_number(series):
    return pd.to_numeric(series.astype(str).str.replace("[c]","1",regex=False)
                         .str.replace("[x]","0",regex=False).str.replace("[z]","0",regex=False),
                         errors="coerce").fillna(0)

@st.cache_data(ttl=21600,show_spinner=False)
def _download_official_uk_catalogue():
    """Successful downloads are cached. Failures raise and therefore are NOT cached."""
    req=Request(DFT_UK_CATALOGUE_URL,headers={
        "User-Agent":"Mozilla/5.0 DG-Deal-Finder",
        "Accept":"text/csv,text/plain,*/*"
    })
    with urlopen(req,timeout=20) as response:
        raw=response.read()
    if len(raw)<1000:
        raise ValueError("Official catalogue download was unexpectedly small")
    df=pd.read_csv(BytesIO(raw),low_memory=False)
    required={"BodyType","Make","GenModel","Model","Fuel","EngineSizeSimple","EngineSizeDesc"}
    if not required.issubset(df.columns):
        raise ValueError("Official catalogue schema did not match expected DfT fields")
    year_cols=[c for c in df.columns if str(c).strip().isdigit() and 2000<=int(str(c).strip())<=2035]
    keep=list(required)+year_cols
    df=df[keep].copy()
    df=df[df["BodyType"].astype(str).str.strip().str.lower().eq("cars")]
    for c in ["Make","GenModel","Model","Fuel","EngineSizeDesc"]:
        df[c]=df[c].fillna("").astype(str).str.strip()
    df["EngineSizeSimple"]=pd.to_numeric(df["EngineSizeSimple"],errors="coerce")
    if df.empty:
        raise ValueError("Official catalogue contained no car rows")
    return df

def load_official_uk_catalogue():
    """Never cache a failed download. Retry on the next Streamlit rerun."""
    try:
        return _download_official_uk_catalogue(), ""
    except Exception as e:
        return pd.DataFrame(), f"{type(e).__name__}: {e}"

def official_uk_makes(df):
    if df is None or df.empty or "Make" not in df.columns:return []
    return sorted({_display_make(x) for x in df["Make"].dropna().unique() if str(x).strip()})

def _match_official_make(df,make):
    if df is None or df.empty:return df.iloc[0:0] if isinstance(df,pd.DataFrame) else pd.DataFrame()
    target=str(make or "").replace("-"," ").replace("  "," ").lower()
    return df[df["Make"].astype(str).str.replace("-"," ",regex=False).str.lower().eq(target)]

def official_uk_models(df,make,year=None):
    d=_match_official_make(df,make)
    if d.empty:return []
    # When annual first-registration counts exist for the selected year, prefer
    # models actually registered that year; otherwise keep the full make range.
    yc=str(int(year)) if year else ""
    if yc in d.columns:
        active=d[_dft_number(d[yc])>0]
        if not active.empty:d=active
    vals={friendly_model_name(make,_dft_model_name(x,y)) for x,y in zip(d["Make"],d["GenModel"])}
    return sorted(v for v in vals if v and v.lower() not in ("unknown","other"))

def _engine_label(simple,desc):
    try:
        cc=int(float(simple))
        if cc>0:return f"{cc/1000:.1f}L ({str(desc).strip()})" if str(desc).strip() else f"{cc/1000:.1f}L"
    except Exception:pass
    return str(desc or "").strip()

def official_uk_vehicle_choices(df,make,model,year=None):
    d=_match_official_make(df,make)
    if d.empty:return ([],[],[],[])
    d=d[_official_model_mask(d,make,model)]
    yc=str(int(year)) if year else ""
    if yc in d.columns:
        d=d[_dft_number(d[yc])>0]
    fuels=sorted({str(x).strip() for x in d.get("Fuel",pd.Series(dtype=str)) if str(x).strip()})
    engines=sorted({_engine_label(a,b) for a,b in zip(d.get("EngineSizeSimple",[]),d.get("EngineSizeDesc",[])) if _engine_label(a,b)})
    # DVLA's detailed Model field is the closest official bulk-data equivalent
    # to derivative/spec. Keep it verbatim rather than inventing a trim.
    specs=sorted({str(x).strip() for x in d.get("Model",pd.Series(dtype=str)) if str(x).strip()})
    return engines,fuels,[],specs


def _norm_fuel(value):
    x=str(value or "").strip().lower()
    if "electric" in x and "hybrid" not in x:return "electric"
    if "hybrid" in x:return "hybrid"
    if "diesel" in x:return "diesel"
    if "petrol" in x:return "petrol"
    return x

def _engine_cc_from_label(value):
    x=str(value or "").lower()
    m=re.search(r"(\d{3,4})\s*cc",x)
    if m:return int(m.group(1))
    m=re.search(r"(\d(?:\.\d)?)\s*l\b",x)
    if m:return int(round(float(m.group(1))*1000))
    return None



def official_year_spec_options(df,make,model,year,fuel=""):
    """Detailed DVLA model descriptions actually registered in selected year/fuel."""
    if df is None or df.empty:return []
    yc=str(int(year)) if year else ""
    if not yc or yc not in df.columns:return []
    d=_match_official_make(df,make)
    if d.empty:return []
    d=d[_official_model_mask(d,make,model)]
    if d.empty:return []
    d=d[_dft_number(d[yc])>0]
    if fuel:
        nf=_norm_fuel(fuel)
        d=d[d["Fuel"].map(_norm_fuel).eq(nf)]
    if d.empty:return []
    return sorted({str(x).strip() for x in d["Model"] if str(x).strip() and str(x).strip().lower() not in {"unknown","other"}})

def filter_specs_to_official_year(candidate_specs,official_specs):
    """When official year-specific detailed models exist, they become the allowed
    spec list. Do not merge generic trims from other years back in."""
    official=[str(x).strip() for x in (official_specs or []) if str(x).strip()]
    if official:return _merge_unique(official)
    return _merge_unique(candidate_specs or [])

def official_year_engine_options(df,make,model,year,fuel="",spec=""):
    """Return engine-size choices actually present in official UK first-registration
    rows for selected model/year/fuel/spec. Empty means we cannot safely constrain."""
    if df is None or df.empty:return []
    yc=str(int(year)) if year else ""
    if not yc or yc not in df.columns:return []
    d=_match_official_make(df,make)
    if d.empty:return []
    d=d[_official_model_mask(d,make,model)]
    if d.empty:return []
    d=d[_dft_number(d[yc])>0]
    if fuel:
        nf=_norm_fuel(fuel)
        d=d[d["Fuel"].map(_norm_fuel).eq(nf)]
    if spec and "Model" in d.columns:
        exact=d[d["Model"].astype(str).str.strip().str.lower().eq(str(spec).strip().lower())]
        if not exact.empty:d=exact
    if d.empty:return []
    return sorted({_engine_label(a,b) for a,b in zip(d["EngineSizeSimple"],d["EngineSizeDesc"]) if _engine_label(a,b)})

def _engine_band_cc(label):
    x=str(label or "").lower()
    m=re.search(r"(\d(?:\.\d)?)\s*l\b",x)
    if m:return int(round(float(m.group(1))*1000/100.0)*100)
    nums=[int(n) for n in re.findall(r"(\d{3,4})\s*cc",x)]
    if nums:return int(round(max(nums)/100.0)*100)
    return None

def filter_engines_to_official_year(candidate_engines,official_engines):
    """Map friendly DG/API engine labels onto official year-specific engine bands.
    If official evidence exists, only compatible engines survive."""
    official=list(official_engines or [])
    if not official:return list(candidate_engines or [])
    bands={_engine_band_cc(x) for x in official if _engine_band_cc(x)}
    kept=[]
    for e in candidate_engines or []:
        cc=_engine_band_cc(e)
        if cc and cc in bands: kept.append(e)
    # Include the official band labels too, so a thin friendly catalogue can never
    # hide an engine that the official year data proves exists.
    return _merge_unique(kept,official)

def official_combo_verification(df,make,model,year,fuel="",spec="",engine=""):
    """Verify that the chosen combination appears in official first-registration
    data for the selected calendar year. Returns verified/blocked/unavailable."""
    if df is None or df.empty:
        return {"status":"unavailable","reason":"Official UK catalogue unavailable."}
    yc=str(int(year)) if year else ""
    if not yc or yc not in df.columns:
        return {"status":"unavailable","reason":"Official year-level engine verification is not available for this year."}
    d=_match_official_make(df,make)
    if d.empty:return {"status":"blocked","reason":f"No official UK records found for {make} in {year}."}
    d=d[_official_model_mask(d,make,model)]
    if d.empty:return {"status":"blocked","reason":f"No official UK records found for {make} {model} in {year}."}
    d=d[_dft_number(d[yc])>0]
    if d.empty:return {"status":"blocked","reason":f"{make} {model} has no first-registration record in the official UK {year} data."}
    if fuel:
        nf=_norm_fuel(fuel)
        fd=d[d["Fuel"].map(_norm_fuel).eq(nf)]
        if fd.empty:return {"status":"blocked","reason":f"{fuel} is not shown for {make} {model} in the official UK {year} data."}
        d=fd
    # For a DG fallback trim, require the meaningful trim words to occur in the
    # official detailed model where possible. If not, leave spec unverified rather
    # than falsely blocking a legitimate naming variation.
    spec_verified=False
    if spec and "Model" in d.columns:
        words=[w.lower() for w in re.findall(r"[A-Za-z0-9]+",str(spec)) if len(w)>=2 and w.lower() not in {"the","edition"}]
        if words:
            sm=d["Model"].astype(str).str.lower().map(lambda x:all(w in x for w in words))
            if sm.any():
                d=d[sm];spec_verified=True
    if engine:
        wanted_cc=_engine_cc_from_label(engine)
        if wanted_cc:
            vals=pd.to_numeric(d["EngineSizeSimple"],errors="coerce")
            # DfT EngineSizeSimple is the upper edge of a 100cc band. Accept only
            # the matching nominal band (e.g. 2.0L -> 1901-2000cc), not a different engine.
            lo=max(1,wanted_cc-99); hi=wanted_cc+25
            ed=d[(vals>=lo)&(vals<=hi)]
            if ed.empty:
                available=sorted({_engine_label(a,b) for a,b in zip(d["EngineSizeSimple"],d["EngineSizeDesc"]) if _engine_label(a,b)})
                suffix=(" Available for this year: "+", ".join(available[:8])) if available else ""
                return {"status":"blocked","reason":f"{engine} is not verified for {make} {model} {year}.{suffix}"}
            d=ed
        else:
            # If we cannot safely map the engine label to an official engine-size band,
            # do not claim verification.
            return {"status":"unavailable","reason":"This engine label cannot be matched safely to the official engine-size data."}
    return {"status":"verified","reason":f"Engine/fuel combination appears in official UK first-registration data for {year}.","spec_verified":spec_verified}

UK_MAKES=["Abarth","Alfa Romeo","Audi","BMW","Citroen","Cupra","Dacia","DS","Fiat","Ford","Honda","Hyundai","Jaguar","Jeep","Kia","Land Rover","Lexus","Mazda","Mercedes-Benz","MG","MINI","Mitsubishi","Nissan","Peugeot","Porsche","Renault","SEAT","Skoda","Smart","Subaru","Suzuki","Tesla","Toyota","Vauxhall","Volkswagen","Volvo"]
COMMON_UK_SPECS={
("Ford","Fiesta"):["Style","Style+","Edge","Zetec","Zetec S","Titanium","Titanium X","ST-Line","ST-Line X","ST"],
("Ford","Focus"):["Style","Zetec","Titanium","Titanium X","ST-Line","ST-Line X","Active","ST"],
("Volkswagen","Golf"):["S","SE","Match","GT","GT Edition","R-Line","GTI","GTD","R"],
("Volkswagen","Polo"):["S","SE","Match","Beats","SEL","R-Line","GTI"],
("BMW","3 Series"):["SE","Sport","Luxury","M Sport"],
("Audi","A3"):["SE","Sport","S line","Black Edition"],
("Vauxhall","Corsa"):["Expression","S","SE","Design","Energy","SRi","Elite","GS Line","Ultimate"],
("Vauxhall","Astra"):["Design","Tech Line","SRi","Elite","GS Line","Ultimate"],
("Mercedes-Benz","A-Class"):["SE","Sport","AMG Line","AMG Line Premium","AMG Line Premium Plus"],
("Nissan","Qashqai"):["Visia","Acenta","Acenta Premium","N-Connecta","Tekna","Tekna+"],
("Peugeot","208"):["Access","Active","Allure","GT Line","GT"],
("Renault","Clio"):["Expression","Dynamique","Play","Iconic","S Edition","RS Line","Techno"],
("Toyota","Yaris"):["Active","Icon","Design","Excel","GR Sport"],
("Kia","Sportage"):["1","2","3","4","GT-Line","GT-Line S"],
("Hyundai","Tucson"):["S","SE","SE Nav","Premium","Premium SE","N Line"],
}




# ---------- FREE VEHICLE TAXONOMY ----------
FLEETBYTE_BASE="https://fleetcatalog.disturbingbyte.pt"

@st.cache_data(ttl=86400, show_spinner=False)
def fleetbyte_variants(make,model,year):
    """Exact-year taxonomy. Variant list is year-filtered; full variant records supply engine data."""
    def get(path,params=None):
        q=("?"+urlencode(params)) if params else ""
        req=Request(FLEETBYTE_BASE+path+q,headers={"Accept":"application/json","User-Agent":"DG-Deal-Finder/1.0"})
        with urlopen(req,timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    makes=get("/v1/makes",{"search":make,"pageSize":100}).get("items",[])
    m=next((x for x in makes if str(x.get("name","")).strip().lower()==make.strip().lower()),None)
    if not m: return []

    models=get(f"/v1/makes/{m['id']}/models",{"search":model,"pageSize":100}).get("items",[])
    mo=next((x for x in models if str(x.get("name","")).strip().lower()==model.strip().lower()),None)
    if not mo: return []

    # CRITICAL: ask the taxonomy for this exact selected year only.
    data=get(f"/v1/models/{mo['id']}/variants",{"year":int(year),"page":1,"pageSize":100})
    items=data.get("items",[]) if isinstance(data,dict) else []

    def engine_label(v):
        # Support common API field shapes from both list and full-spec responses.
        candidates=[
            v.get("engineSize"),v.get("engine_size"),v.get("displacement"),
            v.get("engineDisplacement"),v.get("engineCapacity"),v.get("capacity")
        ]
        eng=v.get("engine")
        if isinstance(eng,dict):
            candidates += [eng.get("size"),eng.get("displacement"),eng.get("capacity"),
                           eng.get("cc"),eng.get("litres"),eng.get("liters")]
        elif eng not in (None,""):
            candidates.append(eng)
        for val in candidates:
            if val in (None,""): continue
            mm=re.search(r'(\d+(?:\.\d+)?)',str(val))
            if not mm: continue
            n=float(mm.group(1))
            if n>20: n=n/1000.0
            if 0.5 <= n <= 10:
                return f"{n:.1f}L"
        return ""

    result=[]
    for summary in items:
        # SPEED: use the year-filtered variant summary directly.
        # Older builds fetched every variant detail one-by-one, which could add dozens
        # of sequential HTTP requests on a mobile appraisal. Missing engine metadata
        # safely falls back to live adverts/local choices/manual override.
        full=summary

        # Defensive year guard: even if an upstream API ever ignores ?year=,
        # reject records that explicitly say they don't cover the selected year.
        y=int(year)
        yf=full.get("yearFrom") or full.get("year_from") or full.get("startYear")
        yt=full.get("yearTo") or full.get("year_to") or full.get("endYear")
        vy=full.get("year") or full.get("modelYear")
        try:
            if vy not in (None,"") and int(vy)!=y: continue
            if yf not in (None,"") and y<int(yf): continue
            if yt not in (None,"") and y>int(yt): continue
        except Exception:
            pass

        name=str(full.get("name") or full.get("variant") or full.get("trim") or summary.get("name") or "").strip()
        fuel=str(full.get("fuelType") or full.get("fuel") or summary.get("fuelType") or summary.get("fuel") or "").strip()
        gearbox=str(full.get("gearboxType") or full.get("gearbox") or full.get("transmission") or summary.get("gearboxType") or "").strip()
        result.append({"spec":name,"engine":engine_label(full),"fuel":fuel,"gearbox":gearbox,"raw":full,"selected_year":y})
    return result

def taxonomy_options(variants,spec="",engine="",fuel=""):
    rows=list(variants or [])
    def norm(x): return str(x or "").strip().lower()
    if spec:
        rows=[x for x in rows if norm(spec) in norm(x.get("spec")) or norm(x.get("spec")) in norm(spec)]
    if engine:
        rows=[x for x in rows if norm(x.get("engine"))==norm(engine)]
    if fuel:
        rows=[x for x in rows if norm(x.get("fuel"))==norm(fuel)]
    def uniq(key):
        out=[]
        for x in rows:
            v=str(x.get(key) or "").strip()
            if v and v.lower() not in [a.lower() for a in out]: out.append(v)
        return out
    return rows,uniq("spec"),uniq("engine"),uniq("fuel"),uniq("gearbox")

# ---------- VEHICLE SPEC CASCADE ----------
# Reliable local fallback for common UK stock. Live sources augment this when available.
DG_POWERTRAIN_CATALOG = {
    ("Porsche","911"): {"engines":["3.0L Twin-Turbo Flat-6","3.8L Twin-Turbo Flat-6","4.0L Flat-6"],"fuels":["Petrol"],"gearboxes":["Automatic","Manual"],"specs":["Carrera","Carrera S","Carrera 4","Carrera 4S","Targa 4","Targa 4S","Carrera T","Carrera GTS","Carrera 4 GTS","Turbo","Turbo S","GT3","GT3 Touring","GT3 RS"]},
    ("Porsche","718 Cayman"): {"engines":["2.0L Turbo","2.5L Turbo","4.0L Flat-6"],"fuels":["Petrol"],"gearboxes":["Manual","Automatic"],"specs":["Cayman","Cayman T","Cayman S","Cayman GTS","GTS 4.0","GT4","GT4 RS"]},
    ("Porsche","718 Boxster"): {"engines":["2.0L Turbo","2.5L Turbo","4.0L Flat-6"],"fuels":["Petrol"],"gearboxes":["Manual","Automatic"],"specs":["Boxster","Boxster T","Boxster S","Boxster GTS","GTS 4.0","Spyder","Spyder RS"]},
    ("Porsche","Macan"): {"engines":["2.0L","3.0L","3.6L"],"fuels":["Petrol","Diesel"],"gearboxes":["Automatic"],"specs":["Macan","S","GTS","Turbo"]},
    ("Porsche","Cayenne"): {"engines":["3.0L","3.6L","4.0L","4.2L"],"fuels":["Petrol","Diesel","Hybrid"],"gearboxes":["Automatic"],"specs":["Cayenne","S","GTS","Turbo","Turbo S","E-Hybrid"]},

    ("Mazda","MX-5"): {
        "engines":["1.5 SKYACTIV-G","2.0 SKYACTIV-G"],
        "fuels":["Petrol"],
        "gearboxes":["Manual","Automatic"],
        "specs":["SE","SE-L","Sport","Sport Nav","Sport Tech","RF","GT Sport Tech","Prime-Line","Exclusive-Line","Homura"]
    },
    ("Skoda","Octavia"): {
        "engines":["1.0L","1.2L","1.4L","1.5L","1.6L","1.8L","2.0L"],
        "fuels":["Petrol","Diesel","Hybrid"],
        "gearboxes":["Manual","Automatic","DSG"],
        "specs":["S","SE","SE Plus","Elegance","Laurin & Klement","vRS","SportLine"]
    },
    ("Volkswagen","Golf"): {
        "engines":["1.0L","1.2L","1.4L","1.5L","1.6L","2.0L"],
        "fuels":["Petrol","Diesel","Hybrid","Electric"],
        "gearboxes":["Manual","Automatic","DSG"],
        "specs":["S","SE","Match","GT","GT Edition","GTI","GTD","R","R-Line"]
    },
    ("Ford","Fiesta"): {
        "engines":["1.0L","1.1L","1.25L","1.4L","1.5L","1.6L"],
        "fuels":["Petrol","Diesel","Hybrid"],
        "gearboxes":["Manual","Automatic"],
        "specs":["Style","Zetec","Titanium","Titanium X","ST-Line","ST-Line X","ST"]
    },
    ("Ford","Focus"): {
        "engines":["1.0L","1.5L","1.6L","2.0L","2.3L"],
        "fuels":["Petrol","Diesel","Hybrid"],
        "gearboxes":["Manual","Automatic"],
        "specs":["Style","Zetec","Titanium","Titanium X","ST-Line","ST-Line X","ST","RS"]
    },
    ("BMW","3 Series"): {
        "engines":["1.5L","1.6L","2.0L","3.0L"],
        "fuels":["Petrol","Diesel","Hybrid"],
        "gearboxes":["Manual","Automatic"],
        "specs":["SE","Sport","Luxury","M Sport","M340i","M340d"]
    },
    ("Audi","A3"): {
        "engines":["1.0L","1.2L","1.4L","1.5L","1.6L","1.8L","2.0L"],
        "fuels":["Petrol","Diesel","Hybrid"],
        "gearboxes":["Manual","Automatic","S tronic"],
        "specs":["SE","Sport","S line","Black Edition","S3","RS3"]
    },
    ("Vauxhall","Corsa"): {
        "engines":["1.0L","1.2L","1.3L","1.4L","1.5L","1.6L"],
        "fuels":["Petrol","Diesel","Electric"],
        "gearboxes":["Manual","Automatic"],
        "specs":["S","SE","Design","Energy","SRi","Elite","GS","Ultimate","VXR"]
    },
    ("Mercedes-Benz","A-Class"): {
        "engines":["1.3L","1.5L","1.6L","2.0L","2.1L"],
        "fuels":["Petrol","Diesel","Hybrid"],
        "gearboxes":["Manual","Automatic"],
        "specs":["SE","Sport","AMG Line","AMG Line Premium","AMG Line Premium Plus","A35 AMG","A45 AMG"]
    },
    ("Dacia","Sandero"): {
        "engines":["0.9L","1.0L","1.2L","1.5L"],
        "fuels":["Petrol","Diesel","LPG"],
        "gearboxes":["Manual","Automatic"],
        "specs":["Access","Essential","Comfort","Expression","Journey"]
    },
    ("Dacia","Sandero Stepway"): {
        "engines":["0.9L","1.0L","1.5L"],
        "fuels":["Petrol","Diesel","LPG"],
        "gearboxes":["Manual","Automatic"],
        "specs":["Essential","Comfort","Prestige","Expression","Extreme"]
    },
}

def _merge_unique(*groups):
    out=[]
    seen=set()
    for group in groups:
        for x in group or []:
            x=str(x).strip()
            if x and x.lower() not in seen:
                seen.add(x.lower()); out.append(x)
    return out

def local_vehicle_choices(make,model,year=None):
    model=lookup_model_name(make,model)
    d=DG_POWERTRAIN_CATALOG.get((make,model),{})
    specs=_merge_unique(d.get("specs",[]))
    try: y=int(year) if year is not None else None
    except (TypeError,ValueError): y=None
    # Current Dacia UK ranges are known; older names are retained only as suggestions
    # because the free market feed is not an authoritative historical taxonomy.
    if make=="Dacia" and model=="Sandero" and y and y>=2025:
        specs=["Essential","Expression","Journey"]
    elif make=="Dacia" and model=="Sandero Stepway" and y and y>=2025:
        specs=["Essential","Expression","Extreme"]
    return list(d.get("engines",[])),list(d.get("fuels",[])),list(d.get("gearboxes",[])),specs

@st.cache_data(ttl=3600, show_spinner=False)
def carsxe_choices(make,model,year):
    """Optional richer taxonomy. Only used when CARSXE_API_KEY exists in Streamlit Secrets."""
    key=str(_secret("CARSXE_API_KEY","")).strip()
    if not key: return [],[],[],[]
    params=urlencode({"key":key,"year":int(year),"make":make,"model":model,"allTrimOptions":1})
    req=Request("https://api.carsxe.com/v1/ymm?"+params,headers={"Accept":"application/json","User-Agent":"DG-Deal-Finder/1.0"})
    with urlopen(req,timeout=15) as r:
        data=json.loads(r.read().decode("utf-8"))
    trims=[]
    engines=[]; fuels=[]; gearboxes=[]
    for item in data.get("trimOptions",[]) or []:
        if isinstance(item,str): trims.append(item)
        elif isinstance(item,dict):
            name=item.get("name") or item.get("trim") or item.get("variant")
            if name: trims.append(name)
            txt=json.dumps(item)
            m=re.search(r'(\d\.\d)\s*L',txt,re.I)
            if m: engines.append(m.group(1)+"L")
            if re.search(r'diesel',txt,re.I): fuels.append("Diesel")
            if re.search(r'petrol|gasoline',txt,re.I): fuels.append("Petrol")
            if re.search(r'hybrid',txt,re.I): fuels.append("Hybrid")
            if re.search(r'electric',txt,re.I): fuels.append("Electric")
            if re.search(r'automatic|\\b\\d+A\\b',txt,re.I): gearboxes.append("Automatic")
            if re.search(r'manual|\\b\\d+M\\b',txt,re.I): gearboxes.append("Manual")
    return _merge_unique(engines),_merge_unique(fuels),_merge_unique(gearboxes),_merge_unique(trims)

@st.cache_data(ttl=900, show_spinner=False)
def marketcheck_choices(make,model,year):
    """Optional UK listing facets. Uses MARKETCHECK_API_KEY if the dealer later adds one."""
    key=str(_secret("MARKETCHECK_API_KEY","")).strip()
    if not key: return [],[],[],[]
    params={
        "api_key":key,"year":int(year),"make":make,"model":model,"rows":0,
        "facets":"engine_size|0|100,fuel_type|0|100,transmission|0|100,variant|0|200"
    }
    req=Request("https://api.marketcheck.com/v2/search/car/uk/active?"+urlencode(params),
                headers={"Accept":"application/json","User-Agent":"DG-Deal-Finder/1.0"})
    with urlopen(req,timeout=15) as r:
        data=json.loads(r.read().decode("utf-8"))
    facets=data.get("facets",{}) or {}
    def terms(name):
        v=facets.get(name,[])
        if isinstance(v,dict): v=v.get("terms",v.get("buckets",[]))
        out=[]
        for x in v or []:
            if isinstance(x,str): out.append(x)
            elif isinstance(x,dict):
                z=x.get("term",x.get("key",x.get("value")))
                if z is not None: out.append(str(z))
        return out
    engines=[]
    for x in terms("engine_size"):
        try:
            n=float(x)
            engines.append(f"{n:.1f}L")
        except: engines.append(x)
    return _merge_unique(engines),_merge_unique(terms("fuel_type")),_merge_unique(terms("transmission")),_merge_unique(terms("variant"))

def robust_vehicle_choices(make,model,year,rows):
    # Current adverts first, then optional structured APIs, then safe local fallback.
    a=build_vehicle_choices(rows)
    mc=([],[],[],[])
    cx=([],[],[],[])
    try: mc=marketcheck_choices(make,model,year)
    except Exception: pass
    try: cx=carsxe_choices(make,model,year)
    except Exception: pass
    local=local_vehicle_choices(make,model,year)
    merged=tuple(_merge_unique(a[i],mc[i],cx[i],local[i]) for i in range(4))
    sources=[]
    if any(a): sources.append("live adverts")
    if any(mc): sources.append("MarketCheck")
    if any(cx): sources.append("CarsXE")
    if any(local): sources.append("DG UK fallback")
    return (*merged, sources)

@st.cache_data(ttl=600, show_spinner=False)
def autoza_comparables(make, model, year, limit=50):
    """Fetch several result pages so DG does not mistake page one for the whole market."""
    wanted=max(1,min(int(limit or 50),150))
    rows=[]
    seen=set()
    per_page=50
    for page in range(1,4):
        params={"make":str(make).strip(),"model":str(model).strip(),
                "min_year":max(1990,int(year)-3),"max_year":int(year)+3,
                "page":page,"limit":per_page}
        url="https://autoza.co.uk/api/v1/vehicles?"+urlencode(params)
        req=Request(url,headers={"Accept":"application/json","User-Agent":"DG-Deal-Finder/1.0"})
        with urlopen(req,timeout=20) as response:
            payload=json.loads(response.read().decode("utf-8"))
        batch=[]
        if isinstance(payload,list):
            batch=payload
        elif isinstance(payload,dict):
            for key in ("vehicles","results","data","items"):
                value=payload.get(key)
                if isinstance(value,list):
                    batch=value; break
                if isinstance(value,dict):
                    for sub in ("vehicles","results","items"):
                        if isinstance(value.get(sub),list):
                            batch=value[sub]; break
                    if batch: break
        if not batch: break
        for car in batch:
            if not isinstance(car,dict): continue
            ident=str(_pick(car,"id","vehicle_id","stock_id","url","advert_url","link") or "")
            if not ident:
                ident="|".join(str(_pick(car,k) or "") for k in ("registration","title","price","mileage","year"))
            if ident in seen: continue
            seen.add(ident); rows.append(car)
            if len(rows)>=wanted: return rows
        if len(batch)<per_page: break
    return rows

def _num(d,*keys):
    if not isinstance(d,dict): return None
    low={str(k).lower():v for k,v in d.items()}
    for k in keys:
        v=low.get(k.lower())
        if v is not None:
            try:
                if isinstance(v,str): v=re.sub(r"[^0-9.]","",v)
                return float(v)
            except: pass
    return None

def _text(car,*keys):
    value=_pick(car,*keys)
    return str(value or "").strip()

def vehicle_search_text(car):
    parts=[_text(car,"title","vehicle","name","derivative"),_text(car,"description"),_text(car,"fuel","fuel_type","fuelType"),_text(car,"transmission","gearbox")]
    return " ".join(x for x in parts if x).lower()

def extract_fuel(car):
    explicit=_text(car,"fuel","fuel_type","fuelType").title()
    if explicit: return explicit
    txt=vehicle_search_text(car)
    for label,words in [("Plug-in Hybrid",["plug-in hybrid","phev"]),("Hybrid",["hybrid","hev"]),("Electric",["electric","ev"]),("Diesel",["diesel","tdi","crdi","dci","hdi"]),("Petrol",["petrol","tsi","tfsi","ecoboost","gdi"] )]:
        if any(w in txt for w in words): return label
    return ""

def extract_gearbox(car):
    explicit=_text(car,"transmission","gearbox").title()
    if explicit:
        if "Auto" in explicit: return "Automatic"
        if "Manual" in explicit: return "Manual"
        return explicit
    txt=vehicle_search_text(car)
    if any(w in txt for w in ["automatic"," auto "," dsg","cvt","e-cvt","dct","steptronic","s tronic","tiptronic"]): return "Automatic"
    if "manual" in txt: return "Manual"
    return ""

def extract_engine(car):
    # Prefer structured engine fields when the source supplies them.
    for key in ("engine","engine_size","engineSize","engine_capacity","engineCapacity"):
        val=_pick(car,key)
        if val not in (None,""):
            txt=str(val).strip()
            m=re.search(r"(\d\.\d)\s*[Ll]?",txt)
            if m: return m.group(1)+"L"
            try:
                n=float(re.sub(r"[^0-9.]","",txt))
                if n>=500: return f"{n/1000:.1f}L"
                if 0.5<=n<=8: return f"{n:.1f}L"
            except: pass
    txt=" "+vehicle_search_text(car)+" "
    m=re.search(r"(?<!\d)([0-6]\.\d)\s*l?(?!\d)",txt,re.I)
    if m: return m.group(1)+"L"
    # EV battery size is useful as the engine/powertrain choice.
    m=re.search(r"(?<!\d)(\d{2,3}(?:\.\d+)?)\s*kwh",txt,re.I)
    if m: return m.group(1)+"kWh"
    return ""

def extract_derivative(car):
    """Extract trim/spec only; never fall back to advert/dealer titles."""
    # Structured derivative/trim/spec fields are safe sources for this dropdown.
    title=_text(car,"derivative","trim","spec","variant")
    if not title:
        return ""
    title=re.sub(r"^\s*(19|20)\d{2}\s+","",title).strip()
    # Defensive dealer-name filter for messy upstream feeds.
    low=title.lower()
    dealer_terms=(" motors"," motors ltd"," motor company"," vehicle sales"," automotive",
                  " car sales"," cars ltd"," dealership"," garage")
    dealer_exact={"vanacar"}
    if low in dealer_exact or any(term in low for term in dealer_terms):
        return ""
    return title

def build_vehicle_choices(rows):
    engines=sorted({extract_engine(c) for c in rows or [] if extract_engine(c)}, key=lambda x:("kWh" in x,x))
    fuels=sorted({extract_fuel(c) for c in rows or [] if extract_fuel(c)})
    gearboxes=sorted({extract_gearbox(c) for c in rows or [] if extract_gearbox(c)})
    derivatives=[]
    seen=set()
    for c in rows or []:
        d=extract_derivative(c)
        if d and d.lower() not in seen:
            seen.add(d.lower()); derivatives.append(d)
    return engines,fuels,gearboxes,derivatives[:40]

def matches_vehicle_choices(car,engine="",fuel="",gearbox="",spec=""):
    if engine and extract_engine(car).lower()!=engine.lower(): return False
    if fuel and extract_fuel(car).lower()!=fuel.lower(): return False
    if gearbox and extract_gearbox(car).lower()!=gearbox.lower(): return False
    if spec:
        words=[w.lower() for w in re.findall(r"[A-Za-z0-9]+",spec) if len(w)>1]
        txt=vehicle_search_text(car)
        # derivative match is deliberately tolerant: require the meaningful spec tokens to appear.
        if words and sum(w in txt for w in words) < max(1,min(3,len(words))): return False
    return True

def build_comparable_cohort(rows, engine="", fuel="", gearbox="", spec="", max_rows=30):
    """Use exact matches first, then progressively relaxed supporting comps.
    Fuel is retained longest; this avoids a one-advert valuation when the wider
    same-model market has useful evidence, without pretending all comps are exact."""
    rows=[r for r in (rows or []) if isinstance(r,dict)]
    tiers=[
        ("Exact", lambda c: matches_vehicle_choices(c,engine,fuel,gearbox,spec)),
        ("Same engine/fuel/gearbox", lambda c: matches_vehicle_choices(c,engine,fuel,gearbox,"")),
        ("Same engine/fuel", lambda c: matches_vehicle_choices(c,engine,fuel,"","")),
        ("Same fuel/gearbox", lambda c: matches_vehicle_choices(c,"",fuel,gearbox,"")),
        ("Same fuel", lambda c: matches_vehicle_choices(c,"",fuel,"","")),
        ("Same model", lambda c: True),
    ]
    chosen=[]; seen=set(); counts={}
    for label,test in tiers:
        added=0
        for car in rows:
            try:
                ok=test(car)
            except Exception:
                ok=False
            if not ok: continue
            ident=str(_pick(car,"id","vehicle_id","stock_id","url","advert_url","link") or "")
            if not ident:
                ident="|".join(str(_pick(car,k) or "") for k in ("registration","title","price","mileage","year"))
            if ident in seen: continue
            seen.add(ident)
            tagged=dict(car); tagged["_dg_match_tier"]=label
            chosen.append(tagged); added+=1
            if len(chosen)>=max_rows: break
        counts[label]=added
        if len(chosen)>=max_rows: break
    return chosen,counts

def comparable_vehicle_label(car, fallback_make="", fallback_model=""):
    """Build a vehicle label without ever using dealer/seller/business names as the car title."""
    make=_text(car,"make","manufacturer","marque") or str(fallback_make or "").strip()
    model=_text(car,"model","model_name","modelName") or str(fallback_model or "").strip()
    derivative=extract_derivative(car)
    engine=extract_engine(car)
    fuel=extract_fuel(car)
    gearbox=extract_gearbox(car)
    parts=[]
    for x in (make,model,derivative,engine,fuel,gearbox):
        x=str(x or "").strip()
        if x and x.lower() not in [p.lower() for p in parts]:
            parts.append(x)
    return " ".join(parts) if parts else "Comparable vehicle"

def estimate_market_from_comps(rows, year, mileage):
    """Average current asking price from relevant for-sale listings.
    Filters obvious mismatches, then uses year/mileage proximity. No sold-price claim."""
    clean=[]
    for car in rows or []:
        price=_num(car,"price","asking_price","askingPrice")
        cy=_num(car,"year","registration_year","registrationYear")
        cm=_num(car,"mileage","miles","odometer")
        if not price or price < 500 or price > 250000: continue
        # reject cars more than 3 model years away when year is supplied
        if cy and year and abs(cy-float(year))>3: continue
        # reject extreme mileage mismatches; keep unknown mileage listings
        if cm and mileage and abs(cm-float(mileage))>60000: continue
        score=(abs((cy or year)-year)*12000)+(abs((cm or mileage)-mileage))
        clean.append((score,car,float(price),float(cm or 0),float(cy or 0)))
    clean.sort(key=lambda x:x[0])
    chosen=clean[:min(10,len(clean))]
    if not chosen: return None
    prices=[x[2] for x in chosen]
    avg=sum(prices)/len(prices)
    # low/high are observed asking prices in the actual selected sample.
    return {"retail":avg,"average":avg,"low":min(prices),"high":max(prices),
            "count":len(chosen),"rows":[x[1] for x in chosen],
            "source":"Average of closest current for-sale listings"}

def analyse_risk(year,mileage,make,model,notes=""):
    age=max(0,2026-int(year))
    typical=max(1,age*7400)
    ratio=(float(mileage)/typical) if age else 1
    points=0; reasons=[]
    if age>=15: points+=2; reasons.append("15+ years old")
    elif age>=10: points+=1; reasons.append("10+ years old")
    if ratio>=1.5: points+=2; reasons.append("mileage is very high for age")
    elif ratio>=1.15: points+=1; reasons.append("mileage is above typical for age")
    elif ratio<=0.6: points+=1; reasons.append("unusually low mileage needs history verification")
    text=(notes or "").lower()
    flags={"cat s":"Category S history","cat n":"Category N history","warning light":"warning light stated",
           "engine light":"engine warning stated","gearbox":"gearbox issue mentioned","overheat":"overheating mentioned",
           "smoke":"smoke mentioned","no mot":"no MOT stated","knock":"knocking noise mentioned"}
    for term,label in flags.items():
        if term in text: points+=2; reasons.append(label)
    level="High" if points>=4 else ("Medium" if points>=2 else "Low")
    if not reasons: reasons=["No obvious age/mileage/text risk flags detected"]
    return level,reasons


@st.cache_data(ttl=900, show_spinner=False)
def free_mot_outlook(make, model, year, mileage):
    return autoza_mcp_call("mot_outlook",{
        "make":make,"model":model,"year":int(year),"mileage":int(mileage)})

@st.cache_data(ttl=900, show_spinner=False)
def free_model_reliability(make, model):
    return autoza_mcp_call("get_model_reliability",{"make":make,"model":model})

@st.cache_data(ttl=3300, show_spinner=False)
def dvsa_token(client_id, client_secret, token_url, scope):
    body=urlencode({"grant_type":"client_credentials","client_id":client_id,
                    "client_secret":client_secret,"scope":scope}).encode()
    req=urllib.request.Request(token_url,data=body,headers={"Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read().decode())["access_token"]

@st.cache_data(ttl=3600, show_spinner=False)
def dvsa_mot_lookup(reg):
    cfg=st.secrets
    needed=["DVSA_CLIENT_ID","DVSA_CLIENT_SECRET","DVSA_TOKEN_URL","DVSA_SCOPE","DVSA_API_KEY"]
    missing=[k for k in needed if not cfg.get(k)]
    if missing: return {"configured":False,"missing":missing}
    token=dvsa_token(cfg["DVSA_CLIENT_ID"],cfg["DVSA_CLIENT_SECRET"],cfg["DVSA_TOKEN_URL"],cfg["DVSA_SCOPE"])
    vrm=re.sub(r"[^A-Za-z0-9]","",reg).upper()
    base=str(cfg.get("DVSA_API_BASE","https://history.mot.api.gov.uk")).rstrip("/")
    url=base+"/v1/trade/vehicles/registration/"+quote(vrm)
    req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"X-API-Key":cfg["DVSA_API_KEY"],"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=20) as r:
        data=json.loads(r.read().decode())
    return {"configured":True,"data":data}

def mot_risk_summary(data):
    tests=data.get("motTests",[]) if isinstance(data,dict) else []
    tests=sorted(tests,key=lambda x:x.get("completedDate",""),reverse=True)
    latest=tests[0] if tests else {}
    fails=sum(1 for t in tests if str(t.get("testResult","")).upper()=="FAILED")
    advisories=[]; majors=[]; dangerous=[]
    recurring={}
    mileages=[]
    for t in tests:
        try:
            m=int(str(t.get("odometerValue","")).replace(",",""))
            mileages.append((t.get("completedDate",""),m))
        except: pass
        for d in t.get("defects",[]) or []:
            typ=str(d.get("type","")).upper(); txt=str(d.get("text","")).strip()
            if typ=="ADVISORY": advisories.append(txt)
            if typ=="MAJOR": majors.append(txt)
            if typ=="DANGEROUS": dangerous.append(txt)
            key=re.sub(r"[^a-z ]","",txt.lower())
            for word in ("tyre","brake","corrosion","suspension","oil leak","exhaust","windscreen"):
                if word in key: recurring[word]=recurring.get(word,0)+1
    mileage_warning=False
    chrono=sorted(mileages)
    for i in range(1,len(chrono)):
        if chrono[i][1] < chrono[i-1][1]: mileage_warning=True
    return {"latest":latest,"fails":fails,"advisories":advisories,"majors":majors,
            "dangerous":dangerous,"recurring":recurring,"mileage_warning":mileage_warning,"tests":tests}

def dvla_lookup(reg):
    """Official DVLA Vehicle Enquiry Service lookup by VRM."""
    key=str(_secret("DVLA_API_KEY","")).strip()
    if not key:
        raise RuntimeError("DVLA_API_KEY is not configured in Streamlit Secrets.")
    vrm=re.sub(r"[^A-Za-z0-9]","",reg).upper()
    req=urllib.request.Request(
        "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
        data=json.dumps({"registrationNumber":vrm}).encode(),
        headers={"x-api-key":key,"Content-Type":"application/json"},
        method="POST")
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read().decode())

def _pick(obj, *keys):
    if not isinstance(obj,dict): return None
    low={str(k).lower():v for k,v in obj.items()}
    for k in keys:
        if k.lower() in low and low[k.lower()] not in (None,""):
            return low[k.lower()]
    for v in obj.values():
        if isinstance(v,dict):
            hit=_pick(v,*keys)
            if hit not in (None,""): return hit
    return None

def vehicle_label_from_dvla(d):
    bits=[d.get("yearOfManufacture"), d.get("make")]
    # DVLA VES does not reliably return model/derivative; don't invent it.
    return " ".join(str(x) for x in bits if x not in (None,""))

def market_summary(comps):
    if not comps: return None
    prices=[]
    miles=[]
    for c in comps:
        pr=_pick(c,"totalPrice","suppliedPrice","price")
        mi=_pick(c,"odometerReadingMiles","mileage")
        try:
            if pr is not None: prices.append(float(pr))
        except: pass
        try:
            if mi is not None: miles.append(float(mi))
        except: pass
    if not prices: return None
    prices.sort()
    mid=prices[len(prices)//2] if len(prices)%2 else (prices[len(prices)//2-1]+prices[len(prices)//2])/2
    return {"count":len(prices),"low":prices[0],"median":mid,"high":prices[-1]}

def fetch_competitors_from_url(search_url, page_size=10):
    """Fetch official Auto Trader competitor results when the API returns an authorised search URL."""
    if not search_url: return []
    headers=_at_headers()
    sep="&" if "?" in search_url else "?"
    url=search_url + sep + urlencode({"page":1,"pageSize":min(int(page_size),20)})
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=25) as r:
        payload=json.loads(r.read().decode())
    if isinstance(payload,list): return payload
    for key in ("results","adverts","stock","vehicles"):
        if isinstance(payload.get(key),list): return payload[key]
    return []


def scan_advert_image(uploaded):
    """Use OpenAI vision to turn an advert screenshot into structured vehicle data."""
    api_key=str(_secret("OPENAI_API_KEY",""))
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured in Streamlit Secrets.")
    raw=uploaded.getvalue()
    mime=uploaded.type or mimetypes.guess_type(uploaded.name)[0] or "image/jpeg"
    data_url=f"data:{mime};base64,"+base64.b64encode(raw).decode()
    schema={
      "name":"vehicle_advert",
      "schema":{
        "type":"object","additionalProperties":False,
        "properties":{
          "vehicle":{"type":"string"},
          "registration":{"type":"string"},
          "year":{"type":["integer","null"]},
          "mileage":{"type":["integer","null"]},
          "asking_price":{"type":["integer","null"]},
          "fuel":{"type":"string"},
          "gearbox":{"type":"string"},
          "description":{"type":"string"},
          "stated_faults":{"type":"array","items":{"type":"string"}},
          "confidence":{"type":"string","enum":["high","medium","low"]}
        },
        "required":["vehicle","registration","year","mileage","asking_price","fuel","gearbox","description","stated_faults","confidence"]
      }
    }
    body={
      "model":str(_secret("OPENAI_VISION_MODEL","gpt-5-mini")),
      "input":[{"role":"user","content":[
        {"type":"input_text","text":"Read this UK used-car sale advert screenshot. Extract only facts visible in the image. Do not guess missing values. For vehicle, include make/model/derivative if visible. Registration should be blank if not visible. Mileage and asking_price must be whole numbers or null. Summarise the seller description and list explicitly stated faults."},
        {"type":"input_image","image_url":data_url}
      ]}],
      "text":{"format":{"type":"json_schema","name":schema["name"],"strict":True,"schema":schema["schema"]}}
    }
    req=urllib.request.Request("https://api.openai.com/v1/responses",
        data=json.dumps(body).encode(),
        headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
        method="POST")
    with urllib.request.urlopen(req,timeout=45) as r:
        res=json.loads(r.read().decode())
    # Responses API returns output content blocks; locate output_text.
    txt=None
    for item in res.get("output",[]):
        for c in item.get("content",[]):
            if c.get("type")=="output_text":
                txt=c.get("text"); break
        if txt: break
    if not txt:
        raise RuntimeError("Vision service returned no structured advert data.")
    return json.loads(txt)


def import_public_listing(url):
    """Best-effort anonymous import of metadata Facebook exposes on a public URL.
    No login, cookies, account automation or access-control bypass.
    """
    if not url or not url.startswith(("https://www.facebook.com/","https://facebook.com/","https://m.facebook.com/")):
        raise ValueError("Paste a Facebook Marketplace/share URL.")
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36",
        "Accept-Language":"en-GB,en;q=0.9"
    })
    with urllib.request.urlopen(req,timeout=12) as r:
        final_url=r.geturl()
        raw=r.read(1500000).decode("utf-8","ignore")
    text=html.unescape(re.sub(r"<[^>]+>"," ",raw))
    text=re.sub(r"\s+"," ",text)

    # Common public metadata/title/description fields.
    def meta(prop):
        pats=[
          rf'<meta[^>]+(?:property|name)=["\\\']{re.escape(prop)}["\\\'][^>]+content=["\\\']([^"\\\']*)',
          rf'<meta[^>]+content=["\\\']([^"\\\']*)["\\\'][^>]+(?:property|name)=["\\\']{re.escape(prop)}["\\\']'
        ]
        for pat in pats:
            m=re.search(pat,raw,re.I)
            if m:return html.unescape(m.group(1))
        return ""
    title=meta("og:title") or meta("twitter:title")
    desc=meta("og:description") or meta("description") or meta("twitter:description")
    blob=" ".join([title,desc,text[:25000]])

    # Price, mileage, registration and rough vehicle title extraction.
    price=None
    for pat in [r'£\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,6})(?!\s*(?:miles|mi))',
                r'"amount"\\s*:\\s*"?(\\d{3,6})']:
        m=re.search(pat,blob,re.I)
        if m:
            try: price=int(m.group(1).replace(",","")); break
            except: pass
    mileage=None
    for pat in [r'([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,6})\s*(?:miles|mi)\b',
                r'([0-9]{1,3})k\s*(?:miles|mi)\b']:
        m=re.search(pat,blob,re.I)
        if m:
            val=m.group(1).replace(",","")
            mileage=int(val)*(1000 if "k" in m.group(0).lower() and "," not in m.group(1) else 1)
            break
    reg=None
    m=re.search(r'\b([A-Z]{2}[0-9]{2}\s?[A-Z]{3}|[A-Z][0-9]{1,3}\s?[A-Z]{3}|[A-Z]{3}\s?[0-9]{1,3}[A-Z])\b',blob.upper())
    if m: reg=m.group(1).replace(" ","")
    vehicle=title.strip()
    vehicle=re.sub(r'\s*[|·-]\s*Facebook Marketplace.*$','',vehicle,flags=re.I)
    vehicle=re.sub(r'^Marketplace\s*[-:]\s*','',vehicle,flags=re.I)
    if vehicle.lower() in ("facebook","facebook marketplace","marketplace"): vehicle=""

    blocked=("log in" in title.lower() and "facebook" in title.lower()) or len(raw)<2000
    return {"vehicle":vehicle[:100],"price":price,"mileage":mileage,"registration":reg,
            "description":desc[:600],"final_url":final_url,"blocked":blocked}


def calc(asking,retail,prep,fees,risk):
    contingency=prep*st.session_state.contingency_pct/100
    all_in=asking+prep+fees+contingency
    margin=retail-all_in
    roi=margin/all_in*100 if all_in else 0
    max_buy=max(0,retail-prep-fees-contingency-st.session_state.min_profit)
    score=50+min(25,max(-25,(margin-st.session_state.min_profit)/40))+min(15,max(-15,(roi-st.session_state.min_roi)/2))+{"Low":10,"Medium":0,"High":-20}[risk]
    score=max(0,min(100,round(score)))
    verdict="BUY" if margin>=st.session_state.min_profit and roi>=st.session_state.min_roi and risk!="High" else ("RESEARCH" if margin>=st.session_state.min_profit*.6 and risk!="High" else "PASS")
    return contingency,all_in,margin,roi,max_buy,score,verdict

def trend_svg():
    return """<svg viewBox="0 0 200 42" style="width:100%;height:100px;margin-top:8px" aria-label="Illustrative price trend"><line x1="0" y1="38" x2="200" y2="38" stroke="#E2E8F0"/><polyline points="2,12 24,14 46,11 68,18 90,17 112,24 134,20 156,29 178,26 198,31" fill="none" stroke="#1769E0" stroke-width="2.2"/></svg>"""

def reset_appraisal():
    """Clear every appraisal/widget value while preserving saved deals and settings."""
    keep={"contingency_pct","min_profit","min_roi"}
    # Clear widget state and derived appraisal state created during this appraisal.
    for key in list(st.session_state.keys()):
        if key not in keep:
            st.session_state.pop(key,None)

def clear_market_if_vehicle_changed():
    current=(st.session_state.get("selected_make",""),st.session_state.get("selected_model",""),st.session_state.get("selected_year",""))
    previous=st.session_state.get("_market_vehicle_identity")
    if previous is not None and previous!=current:
        st.session_state.pop("market_estimate",None)
        st.session_state.pop("market_retail",None)
    st.session_state["_market_vehicle_identity"]=current

source_advert=st.session_state.get("source_advert_text","")
source_info={}
tabs=st.tabs(["APPRAISAL","SAVED APPRAISALS","MARKET","SETTINGS"])

with tabs[0]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">DG buying desk</div><div class="hero">Appraise a vehicle</div><div class="sub">Vehicle, market, condition and deal risk — one buying decision.</div></div>',unsafe_allow_html=True)
    st.markdown('<div class="section">Choose vehicle</div>',unsafe_allow_html=True)
    st.caption("Choose make, year and model. DG uses its cached official UK catalogue first, with live/API data only as enrichment.")
    official_catalogue,official_catalogue_error=load_official_uk_catalogue()
    catalogue_makes=official_uk_makes(official_catalogue)
    make_options=_merge_unique(UK_MAKES,catalogue_makes)
    a,b=st.columns(2)
    selected_make=a.selectbox("Make",[""]+make_options)
    selected_year=b.selectbox("Year",list(range(2026,1995,-1)),index=16)
    models=[]
    if selected_make:
        try:
            embedded_models=free_models_for_make_year(selected_make,selected_year)
            official_models=official_uk_models(official_catalogue,selected_make,selected_year)
            models=_merge_unique(official_models,embedded_models)
            if selected_make=="Porsche":
                models=_merge_unique(models,["911","Cayman","Boxster","Macan","Cayenne","Panamera","Taycan"])
        except Exception:
            models=free_models_for_make_year(selected_make,selected_year)
    selected_model=st.selectbox("Model",["— Choose model —"]+models,disabled=not bool(selected_make))
    with st.expander("Model missing from the list?"):
        manual_model=st.text_input("Manual model",placeholder="Only use this when the actual model is missing, e.g. Octavia")
        if manual_model.strip():
            selected_model=manual_model.strip()
    if selected_model=="— Choose model —": selected_model=""
    lookup_model=lookup_model_name(selected_make,selected_model)

    # Spec-first selector backed by a separate vehicle taxonomy.
    # Keep selector interaction fast: live adverts are deliberately NOT fetched here.
    # The deeper Autoza market search runs once, only after ANALYSE DEAL is pressed.
    selector_rows=[]

    taxonomy=[]
    taxonomy_error=""
    official_precheck=official_uk_vehicle_choices(official_catalogue,selected_make,selected_model,selected_year) if selected_make and selected_model else ([],[],[],[])
    official_has_choices=any(official_precheck)
    # Speed: official UK bulk data is local-in-memory after the first cached load.
    # Only call the external taxonomy service when official data has no useful choices.
    if selected_make and selected_model and not official_has_choices:
        try: taxonomy=fleetbyte_variants(selected_make,lookup_model,selected_year)
        except Exception as e: taxonomy_error=str(e)

    # Live adverts remain valuation evidence. Taxonomy is the compatibility source.
    engines,fuels,gearboxes,derivatives,choice_sources=robust_vehicle_choices(
        selected_make,lookup_model,selected_year,selector_rows
    ) if selected_make and selected_model else ([],[],[],[],[])
    official_engines,official_fuels,official_gearboxes,official_specs=official_uk_vehicle_choices(
        official_catalogue,selected_make,selected_model,selected_year
    ) if selected_make and selected_model else ([],[],[],[])
    engines=_merge_unique(official_engines,engines)
    fuels=_merge_unique(official_fuels,fuels)
    gearboxes=_merge_unique(official_gearboxes,gearboxes)
    derivatives=_merge_unique(official_specs,derivatives)
    if any((official_engines,official_fuels,official_specs)):
        choice_sources=["official UK bulk catalogue"]+choice_sources
    # Final resilience layer: external sources can ADD choices but cannot erase known
    # model-level data. Manual overrides remain available for exact historical variants.
    dg_engines,dg_fuels,dg_gearboxes,dg_specs=local_vehicle_choices(selected_make,selected_model,selected_year)
    engines=_merge_unique(engines,dg_engines)
    fuels=_merge_unique(fuels,dg_fuels)
    gearboxes=_merge_unique(gearboxes,dg_gearboxes)
    derivatives=_merge_unique(derivatives,dg_specs)

    taxonomy_verified=bool(taxonomy)
    official_catalogue_loaded=not official_catalogue.empty
    if not official_catalogue_loaded:
        st.warning("UK vehicle catalogue connection failed. DG will retry automatically when you change a selection. Year-locking is temporarily unavailable.")
        if st.button("RETRY UK VEHICLE CATALOGUE",key="retry_official_catalogue",use_container_width=True):
            _download_official_uk_catalogue.clear()
            st.rerun()

    # Fuel first: this immediately removes petrol/diesel/hybrid/EV derivatives and engines
    # that cannot belong to the selected fuel type for the exact chosen year.
    if taxonomy_verified:
        _,_,_,tax_fuels,_=taxonomy_options(taxonomy)
        fuel_options=_merge_unique(tax_fuels,fuels)
    else:
        fuel_options=fuels
    fuel_index=1 if len(fuel_options)==1 else 0
    selected_fuel=st.selectbox("Fuel",["— Choose fuel —"]+fuel_options,index=fuel_index,disabled=not bool(selected_model))
    if selected_fuel.startswith("—"): selected_fuel=""

    if taxonomy_verified:
        fuel_rows,tax_specs,_,_,_=taxonomy_options(taxonomy,fuel=selected_fuel)
        candidate_specs=_merge_unique(tax_specs,derivatives)
    else:
        fuel_rows=[]
        candidate_specs=derivatives

    # YEAR-LOCKED SPEC: if official detailed model rows exist for the chosen
    # make/model/year/fuel, only those specs are offered. Generic trims from
    # another year are not merged back into the dropdown.
    official_year_specs=official_year_spec_options(
        official_catalogue,selected_make,selected_model,selected_year,selected_fuel
    )
    verified_dg_specs=dg_year_specs(selected_make,selected_model,selected_year,selected_fuel)
    year_spec_evidence=_merge_unique(official_year_specs,verified_dg_specs)
    # Universal reliability rule: model-level fallback specs are never treated as
    # valid for a selected year. Exact taxonomy is allowed only when year evidence
    # is otherwise unavailable.
    safe_specs,_,safe_sources=reliable_year_choices(
        official_year_specs,[],verified_dg_specs,[],tax_specs if taxonomy_verified else [],
        [],taxonomy_verified
    )
    spec_options=safe_specs
    spec_is_year_constrained=bool(year_spec_evidence)

    if spec_is_year_constrained:
        st.caption(f"Spec list filtered to {selected_year} UK registrations — {len(spec_options)} valid choice(s).")

    selected_spec=st.selectbox("Spec / derivative",["— Choose spec —"]+spec_options,
        disabled=not bool(selected_model),
        help="DG combines structured taxonomy when available, clean live-advert trim fields and built-in UK model trim suggestions. Suggestions are not presented as authoritative historical derivative data.")
    if selected_spec.startswith("—"): selected_spec=""
    if taxonomy_verified:
        st.caption("Fuel → year-valid spec → spec-valid engine → gearbox. Official UK year data constrains choices where available; fallback data is used only where official detail is unavailable.")
    else:
        st.caption("Fuel → spec → engine → gearbox. Where the free feed has no structured spec, DG supplies clean model trim suggestions instead of dealer names; use the manual override if the exact historical trim is missing.")

    if not spec_is_year_constrained:
        with st.expander("Exact spec not listed?"):
            manual_spec=st.text_input("Spec override",placeholder="e.g. vRS")
            if manual_spec.strip(): selected_spec=manual_spec.strip()
    else:
        st.caption("Manual spec override is disabled because year-specific official spec data is available.")

    if taxonomy_verified:
        spec_rows,_,tax_engines,_,_=taxonomy_options(taxonomy,spec=selected_spec,fuel=selected_fuel)
        candidate_engines=_merge_unique(tax_engines,engines)
    else:
        spec_rows=[]
        live_fuel_rows=[c for c in selector_rows if (not selected_fuel or extract_fuel(c).lower()==selected_fuel.lower())]
        live_engines,_,_,_=build_vehicle_choices(live_fuel_rows)
        candidate_engines=_merge_unique(live_engines,engines)

    # IMPOSSIBLE-WRONG-ENGINE selector:
    # once make/model/year/fuel are known, remove engines not evidenced in that year's
    # official UK registrations instead of allowing a bad choice then rejecting it.
    official_year_engines=official_year_engine_options(
        official_catalogue,selected_make,selected_model,selected_year,selected_fuel,selected_spec
    )
    verified_dg_engines=dg_year_engines(
        selected_make,selected_model,selected_year,selected_fuel,selected_spec
    )
    year_engine_evidence=_merge_unique(official_year_engines,verified_dg_engines)
    _,safe_engines,engine_sources=reliable_year_choices(
        [],official_year_engines,[],verified_dg_engines,[],
        tax_engines if taxonomy_verified else [],taxonomy_verified
    )
    engine_options=safe_engines
    engine_is_year_constrained=bool(year_engine_evidence)

    if engine_is_year_constrained:
        st.caption(f"Engine list filtered to {selected_year} UK registrations — {len(engine_options)} valid choice(s).")
    elif selected_model:
        st.caption("No year-specific official engine evidence available; DG fallback choices are shown and will be checked before valuation.")

    coverage_status=catalogue_confidence(spec_options,engine_options)
    if selected_model and coverage_status=="unverified":
        st.warning(f"NO VERIFIED {selected_year} SPEC/ENGINE DATA — DG has hidden broad fallback choices rather than risk showing an engine from the wrong year.")
    elif selected_model and coverage_status=="partial":
        st.warning(f"PARTIAL {selected_year} VEHICLE DATA — only evidenced choices are shown; DG will not invent the missing spec/engine.")
    elif selected_model:
        st.success(f"{selected_year} SPEC/ENGINE FILTER ACTIVE — only year-evidenced choices are shown.")

    selected_engine=st.selectbox("Engine / powertrain",["— Choose engine —"]+engine_options,
        disabled=not bool(selected_model) or not bool(engine_options))
    if selected_engine.startswith("—"): selected_engine=""

    if taxonomy_verified:
        final_rows,_,_,_,tax_gearboxes=taxonomy_options(
            taxonomy,spec=selected_spec,engine=selected_engine,fuel=selected_fuel)
        gearbox_options=_merge_unique(tax_gearboxes,gearboxes)
    else:
        gearbox_options=gearboxes
    selected_gearbox=st.selectbox("Gearbox",["— Choose gearbox —"]+gearbox_options,
        disabled=not bool(selected_model))
    if selected_gearbox.startswith("—"): selected_gearbox=""

    historical_engines=dg_year_engines(selected_make,selected_model,selected_year,selected_fuel,selected_spec)
    if selected_engine and historical_engines:
        combo_check={"status":"verified","reason":f"Engine/spec is in DG's year-bounded verified catalogue for {selected_year}.","spec_verified":True}
    else:
        combo_check=official_combo_verification(
            official_catalogue,selected_make,selected_model,selected_year,
            selected_fuel,selected_spec,selected_engine
        ) if selected_make and selected_model and selected_engine else {"status":"unavailable","reason":"Choose an engine to verify it against the selected year."}
    if selected_engine:
        if combo_check["status"]=="verified":
            st.success("YEAR / ENGINE CHECK ✓  "+combo_check["reason"])
        elif combo_check["status"]=="blocked":
            st.error("YEAR / ENGINE MISMATCH — "+combo_check["reason"]+" Change the selection before valuation.")
        else:
            st.warning("YEAR / ENGINE CHECK LIMITED — "+combo_check["reason"]+" DG will use the available catalogue and market evidence; verify unusual/imported cars manually.")

    with st.expander("Exact engine not listed?"):
        manual_engine=st.text_input("Engine override",placeholder="e.g. 2.0L")
        if manual_engine.strip(): selected_engine=manual_engine.strip()

    if selected_make and selected_model:
        if taxonomy_verified:
            st.success("Compatibility verified by vehicle taxonomy — incompatible engine, fuel and gearbox choices are removed.")
        else:
            st.caption("Exact derivative data is limited for this vehicle/year. DG will not treat broad cross-year fallback choices as verified.")
    cat_mileage=st.number_input("Mileage",0,500000,0,1000,key="catalogue_mileage")
    st.markdown('<div class="section">Source advert</div>',unsafe_allow_html=True)
    source_advert=st.text_area("Paste advert / description",key="source_advert_text",placeholder="Paste the Marketplace or other advert text here. Include its link if you have it.",help="DG keeps the seller wording as context. Confirm the important facts in the appraisal fields.")
    source_info=extract_source_advert(source_advert)
    if source_info:
        detected=[]
        if source_info.get("price") is not None: detected.append(f"asking £{source_info['price']:,}")
        if source_info.get("mileage") is not None: detected.append(f"{source_info['mileage']:,} miles")
        if source_info.get("url"): detected.append("advert link")
        if detected: st.caption("Detected: "+" · ".join(detected))
        st.caption("Detected advert details are not silently substituted for your confirmed appraisal inputs.")
    reg_manual=st.text_input("Registration (optional)",placeholder="e.g. DA59 XDG")
    if selected_make and selected_model:
        label=f"{selected_year} {selected_make} {selected_model}"
        if selected_engine: label+=f" {selected_engine}"
        if selected_fuel and selected_fuel.lower() not in label.lower(): label+=f" {selected_fuel}"
        if selected_gearbox: label+=f" {selected_gearbox}"
        if selected_spec: label+=f" {selected_spec}"
        st.session_state["imp_vehicle"]=label
        st.session_state["imp_mileage"]=int(cat_mileage)
        st.session_state["imp_reg"]=re.sub(r"[^A-Za-z0-9]","",reg_manual).upper()
        st.success(f"Selected: {label}")
        st.session_state["selected_make"]=selected_make
        st.session_state["selected_model"]=selected_model
        st.session_state["selected_year"]=selected_year
        st.session_state["selected_engine"]=selected_engine
        st.session_state["selected_fuel"]=selected_fuel
        st.session_state["selected_gearbox"]=selected_gearbox
        st.session_state["selected_spec"]=selected_spec
        clear_market_if_vehicle_changed()
        st.caption("Live market data is checked automatically when you tap ANALYSE DEAL.")

    market=st.session_state.get("market_estimate")
    if market and not isinstance(market,dict):
        # Ignore stale state from an older deployment instead of crashing.
        market=None
        st.session_state["market_estimate"]=None
    if market:
        market_count=int(safe_market_snapshot(market).get("count",0) or 0)
        st.metric("Est. retail",f'£{st.session_state.get("market_retail",0):,.0f}')
        if market_count>=2:
            c1,c2=st.columns(2)
            c1.metric("Comparable low",f'£{market["low"]:,.0f}')
            c2.metric("Comparable high",f'£{market["high"]:,.0f}')
            st.caption(f'{market_count} close current asking-price comparables. Asking price is not the same as achieved sale price.')
        elif market_count==1:
            st.caption(f'Based on 1 close current asking-price comparable at £{market["low"]:,.0f}. DG will not present a low/high range from one advert.')
        else:
            st.caption("No usable close comparable count returned. Treat the estimate cautiously.")
        chosen_bits=[x for x in [safe_market_snapshot(market).get("engine"),safe_market_snapshot(market).get("fuel"),safe_market_snapshot(market).get("gearbox"),safe_market_snapshot(market).get("spec")] if x]
        if chosen_bits: st.caption("Filtered toward: "+" · ".join(chosen_bits)+f' · {safe_market_snapshot(market).get("selector_match_count",0)} matching advert(s) before closest-car ranking.')
        if safe_market_snapshot(market).get("count",0)<5:
            st.warning(f'Only {safe_market_snapshot(market).get("count",0)} suitable listing(s) found. Treat this average as low-confidence.')
        else:
            st.caption(f'Observed asking range: £{market["low"]:,.0f}–£{market["high"]:,.0f}. Average is based only on the displayed comparable sample.')
        with st.expander(f'Similar cars currently advertised ({len(safe_market_snapshot(market).get("rows",[]))})'):
            if not safe_market_snapshot(market).get("rows"):
                st.info("The market service returned price guidance but no individual comparable adverts for this search.")
            for i,car in enumerate(safe_market_snapshot(market).get("rows",[])[:10],1):
                price=_num(car,"price","asking_price","askingPrice") or 0
                miles=_num(car,"mileage","miles","odometer") or 0
                yr=int(_num(car,"year","registration_year","registrationYear") or 0)
                title_txt=_pick(car,"title","vehicle","name","derivative","description")
                if not title_txt:
                    title_txt=f'{yr or ""} {_pick(car,"make") or selected_make} {_pick(car,"model") or selected_model}'.strip()
                dealer=_pick(car,"dealer","dealer_name","seller","advertiser","location")
                url=_pick(car,"url","advert_url","advertUrl","link")
                detail=f'£{price:,.0f} · {int(miles):,} miles'
                if dealer: detail+=f' · {dealer}'
                st.markdown(f'**{i}. {title_txt}** — {detail}')
                if url: st.markdown(f'[View advert]({url})')

    with st.expander("DG buying checklist"):
        st.markdown("""
- **Identity:** registration, VIN at viewing, make/model/spec and seller identity agree.
- **History:** MOT mileage progression, service invoices, timing-belt/chain evidence where relevant, recalls/campaigns where applicable.
- **Condition:** cold start, warning lights, clutch/gearbox, cooling system, brakes, tyres, suspension, leaks, air-con and electrics.
- **Body:** panel gaps, paint mismatch, corrosion, glass, wheels/tyres and evidence of structural repair.
- **Commercial:** V5C present, keys, finance/write-off/theft provenance check, realistic prep, other buying costs, transport and desired contribution.
- **Exit:** compare against the 10 closest cars and price to sell, not merely to advertise.
""")
    with st.form("appraise"):
        reg=st.text_input("Registration",value=st.session_state.get("imp_reg",""),placeholder="e.g. CV60 ZLZ").upper().replace(" ","")
        vehicle=st.text_input("Vehicle",value=st.session_state.get("imp_vehicle",""),placeholder="Make, model and derivative")
        a,b=st.columns(2); mileage=a.number_input("Mileage",0,300000,int(st.session_state.get("imp_mileage",0)),1000); asking=b.number_input("Seller asking (£)",0,100000,int(st.session_state.get("imp_asking",0)),50)
        a,b=st.columns(2); retail=a.number_input("Retail estimate override (£)",0,150000,0,50,help="Optional. Leave at £0 to use the fresh live-market estimate when you tap ANALYSE DEAL."); prep=b.number_input("Prep budget (£)",0,20000,400,50)
        a,b=st.columns(2); fees=a.number_input("Other buying costs (£)",0,10000,250,25); risk="Medium"
        target_margin=st.number_input("Desired contribution / margin (£)",0,20000,500,50,help="Defaults to £500 for a new appraisal. Change it whenever the deal needs a different target.")
        c1,c2=st.columns(2)
        service_history=c1.selectbox("Service history",["Full","Part","None","Unknown"])
        keys=c2.selectbox("Keys",["2+ keys","1 key","Unknown"])
        c1,c2=st.columns(2)
        provenance=c1.selectbox("Finance / theft check",["Not checked","Clear","Issue found"])
        v5c=c2.selectbox("V5C",["Not checked","Present & matches","Missing / mismatch"])
        c1,c2=st.columns(2)
        insurance_category=c1.selectbox("Insurance / write-off category",["Clear / none known","Cat N","Cat S","Cat D (legacy)","Cat C (legacy)","Cat B","Cat A","Other / unsure"],help="Includes current Cat N/S and older UK Cat C/D classifications.")
        default_cat_adjust={"Clear / none known":0,"Cat N":10,"Cat S":20,"Cat D (legacy)":12,"Cat C (legacy)":18,"Cat B":50,"Cat A":50,"Other / unsure":15}[insurance_category]
        category_discount=c2.number_input("Category retail adjustment (%)",0,50,default_cat_adjust,1,
            help="Editable appraisal assumption. This is not a universal market discount.")
        category_guidance={"Clear / none known":"No known insurance write-off marker entered.","Cat N":"Non-structural damage under the current UK system. Repair quality and provenance still need checking.","Cat S":"Structural damage under the current UK system. Inspect structural repair quality and evidence carefully.","Cat D (legacy)":"Older repairable category. Verify repair quality and provenance; the percentage is an appraisal assumption, not a universal discount.","Cat C (legacy)":"Older repairable category. Repair costs exceeded pre-accident value under the former system; verify repairs and provenance carefully.","Cat B":"Break for parts: the bodyshell must not return to the road. Do not appraise as a normal retail road car.","Cat A":"Scrap only: the complete vehicle must be crushed. Do not appraise as a retail road car.","Other / unsure":"Category unclear. Verify provenance before relying on the valuation."}
        if insurance_category in ("Cat A","Cat B"): st.error(category_guidance[insurance_category])
        else: st.caption(category_guidance[insurance_category])

        modification_level=st.selectbox(
            "Vehicle modifications",
            ["Standard / not modified","Light modifications","Significant modifications","Heavily modified / track-style"],
            help="Defaults to standard. Modification values are DG appraisal assumptions because aftermarket changes can narrow the buyer pool and their value is highly vehicle-specific."
        )
        modification_default={"Standard / not modified":0,"Light modifications":-3,"Significant modifications":-7,"Heavily modified / track-style":-12}[modification_level]
        modification_pct=st.number_input(
            "Modification retail adjustment (%)",-25,15,modification_default,1,
            help="Editable. Negative reduces expected retail; positive can be used only where you have evidence that a desirable modification genuinely adds retail value."
        )
        modification_notes=st.text_input(
            "Modification details",placeholder="e.g. remap, exhaust, suspension, wheels — leave blank if standard",
            disabled=modification_level=="Standard / not modified"
        )
        condition_grade=st.selectbox(
            "Condition grade",
            [1,2,3,4,5],
            index=1,
            format_func=lambda x:{
                1:"1 — Excellent / retail-ready",
                2:"2 — Good / light prep",
                3:"3 — Average / noticeable prep",
                4:"4 — Poor / significant work",
                5:"5 — Major damage / substantial work"
            }[x],
            help="DG 1–5 appraisal grade: 1 is best, 5 is major damage. This is a DG appraisal scale inspired by common vehicle-buying condition grading, not claimed as WBAC's proprietary formula."
        )
        # Context-sensitive defaults use the live estimate currently available for this appraisal.
        scale_value=float(st.session_state.get("market_retail",0) or 0)
        scaled_defaults=scaled_appraisal_adjustments(selected_year,scale_value,condition_grade,service_history,keys,12)
        grade_adjustment=st.number_input(
            "Condition grade retail adjustment (£)",-10000,2000,int(scaled_defaults["condition"]),25,
            help="DG default scales with age and live market value. Editable. Actual repair/prep spend still belongs in Prep."
        )
        st.caption("DG scaled default: "+scaled_defaults["condition_reason"])
        service_adjustment=st.number_input(
            "Service history retail adjustment (£)",-10000,2000,int(scaled_defaults["service"]),25,
            help="DG default scales incomplete history more heavily on younger/higher-value stock. Editable."
        )
        st.caption("DG scaled default: "+scaled_defaults["service_reason"])
        keys_adjustment=st.number_input(
            "Keys retail adjustment (£)",-3000,1000,int(scaled_defaults["keys"]),25,
            help="DG default scales moderately with vehicle context rather than using the same £ amount on every car. Editable."
        )
        st.caption("DG scaled default: "+scaled_defaults["keys_reason"])
        st.markdown('<div class="section">MOT appraisal</div>',unsafe_allow_html=True)
        mot_notes=st.text_area("Notes / advisories from last MOT",placeholder="Paste or type the latest MOT advisories here…",help="Buying-cost planning aid only — not an MOT lookup or garage quote.")
        mot_analysis=analyse_mot_notes(mot_notes)
        if mot_analysis["items"]:
            st.caption("Potential cost areas: "+", ".join(mot_analysis["items"]))
            st.caption(f"Rough planning range: £{mot_analysis['low']:,}–£{mot_analysis['high']:,}.")
        elif mot_notes.strip():
            st.caption("No cost category recognised automatically. Review the wording manually.")
        mot_months=st.slider("Approx. MOT remaining (months)",0,12,12,1)
        scaled_mot=scaled_appraisal_adjustments(selected_year,scale_value,condition_grade,service_history,keys,mot_months)
        mot_time_adj=st.number_input("MOT time remaining adjustment (£)",-3000,500,int(scaled_mot["mot"]),25,help="DG default scales short-MOT impact mainly by vehicle age. Editable.")
        st.caption("DG scaled default: "+scaled_mot["mot_reason"])
        mot_notes_cost=st.number_input("MOT advisory cost allowance (£)",0,5000,int(mot_analysis["planning"]),25,help="Editable likely-cost allowance from the MOT notes. This reduces maximum buy.")

        manual_retail_adjustment=st.number_input(
            "Other retail adjustment (£)",-5000,5000,0,50,
            help="Optional final adjustment for unusual spec, colour, provenance or another factor not already covered."
        )
        notes=st.text_area("Notes",value=st.session_state.get("imp_desc",""),placeholder="History, MOT, tyres, damage, keys…")
        repair_text=" ".join(x for x in [source_advert,notes] if str(x or "").strip())
        repair_intel=analyse_description_repairs(repair_text,selected_make,selected_model,selected_spec)
        detected_repair_default=int(repair_intel.get("allowance",0) or 0)
        if repair_intel.get("items"):
            st.markdown('<div class="section">AI repair intelligence</div>',unsafe_allow_html=True)
            st.caption("DG identifies likely unresolved work from seller wording, then applies vehicle-sensitive buying allowances. Confirm with diagnosis/quote.")
            for item in repair_intel["items"]: st.write(f'**{item["issue"]}:** £{item["low"]:,.0f}–£{item["high"]:,.0f} · allowance **£{item["allowance"]:,.0f}**')
            st.caption(f'Cost factor ×{repair_intel["multiplier"]:.2f} for {selected_make} {selected_model}.')
        detected_repair_cost=st.number_input("Description-detected repair allowance (£)",0,30000,detected_repair_default,25,help="Suggested from advert/notes and vehicle type. Editable after inspection or a garage quote.")
        description_risk=assess_seller_description(source_advert,{"keys":keys,"service_history":service_history,"category":insurance_category}) if source_advert.strip() else {"level":"Unknown","score":0,"flags":[],"positives":[],"questions":[],"conflicts":[]}
        risk,risk_reasons=analyse_risk(st.session_state.get("selected_year",2020),mileage,st.session_state.get("selected_make",""),st.session_state.get("selected_model","")," ".join(x for x in [notes,source_advert] if x))
        if description_risk.get("level")=="High":
            risk="High"; risk_reasons.append("Seller description contains high-risk wording")
        elif description_risk.get("level")=="Medium" and risk=="Low":
            risk="Medium"; risk_reasons.append("Seller description contains cautionary wording")
        if description_risk.get("conflicts"):
            risk="High"; risk_reasons.append("Seller description conflicts with confirmed appraisal inputs")
        mm=st.session_state.get("market_estimate")
        if not mm:
            risk="High"; risk_reasons.append("No live comparable evidence — valuation confidence is low")
        elif mm.get("count",0)<5:
            if risk=="Low": risk="Medium"
            risk_reasons.append("Fewer than 5 close comparables — valuation confidence reduced")
        if service_history=="None":
            if risk=="Low": risk="Medium"
            risk_reasons.append("No service history")
        elif service_history=="Unknown":
            risk_reasons.append("Service history not verified")
        if keys=="1 key":
            risk_reasons.append("Only one key — allow for replacement cost")
        if provenance=="Issue found":
            risk="High"; risk_reasons.append("Provenance check found an issue")
        elif provenance=="Not checked":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Finance/write-off/theft provenance not checked")
        if v5c=="Missing / mismatch":
            risk="High"; risk_reasons.append("V5C missing or details mismatch")
        elif v5c=="Not checked":
            risk_reasons.append("V5C not verified")
        if insurance_category=="Cat S":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Cat S recorded — structural repair history must be assessed and retail adjusted")
        elif insurance_category=="Cat N":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Cat N recorded — non-structural write-off history; verify repair quality/provenance")
        elif insurance_category=="Cat C (legacy)":
            risk="High"; risk_reasons.append("Legacy Cat C recorded — verify repair quality and provenance carefully")
        elif insurance_category=="Cat D (legacy)":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Legacy Cat D recorded — verify repair quality and provenance")
        elif insurance_category in ("Cat A","Cat B"):
            risk="High"; risk_reasons.append(f"{insurance_category} is not suitable for appraisal as a normal retail road car")
        elif insurance_category=="Other / unsure":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Insurance category needs verification")
        if detected_repair_cost>0:
            if detected_repair_cost>=1500: risk="High"
            elif risk=="Low": risk="Medium"
            risk_reasons.append(f"Description implies ~£{detected_repair_cost:,.0f} unresolved repair allowance")
        if modification_level=="Light modifications":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Modified vehicle — verify modification quality, insurance implications and buyer demand")
        elif modification_level=="Significant modifications":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Significant modifications — narrower buyer pool and additional mechanical/insurance checks required")
        elif modification_level=="Heavily modified / track-style":
            risk="High"
            risk_reasons.append("Heavily modified vehicle — retail demand, mechanical use and insurability require extra caution")
        st.markdown(f"**DG risk analysis: {risk}**")
        st.caption(" · ".join(risk_reasons))
        if st.session_state.get("scan_year") or st.session_state.get("scan_fuel") or st.session_state.get("scan_gearbox"):
            st.caption("Detected: " + " · ".join([str(x) for x in [st.session_state.get("scan_year"),st.session_state.get("scan_fuel"),st.session_state.get("scan_gearbox")] if x]))
        if source_advert.strip():
            st.markdown('<div class="section">Description intelligence</div>',unsafe_allow_html=True)
            if description_risk["level"]=="High": st.error("Seller-description risk: High")
            elif description_risk["level"]=="Medium": st.warning("Seller-description risk: Medium")
            else: st.success("Seller-description risk: Low")
            if description_risk["flags"]:
                st.write("**What DG noticed:** "+", ".join(description_risk["flags"]))
            if description_risk["conflicts"]:
                st.write("**Conflicts with your appraisal:**")
                for conflict in description_risk["conflicts"]: st.write("• "+conflict)
            if description_risk["positives"]:
                st.write("**Seller claims worth verifying:**")
                for positive in description_risk["positives"]: st.write("• "+positive)
            if description_risk["questions"]:
                with st.expander("Questions to ask the seller"):
                    for question in description_risk["questions"]: st.write("• "+question)
            st.caption("This screens seller wording for risk and contradictions. Seller claims remain unverified; it does not replace inspection, diagnostics or provenance checks.")
        go=st.form_submit_button("ANALYSE DEAL  →",use_container_width=True,disabled=bool(selected_model) and (not spec_options or not engine_options))
    if go:
        # Safety gate: never produce a valuation from an engine/year combination that
        # we cannot verify. This prevents a plausible-looking value for the wrong derivative.
        historical_engines=dg_year_engines(selected_make,selected_model,selected_year,selected_fuel,selected_spec)
        if selected_engine and selected_engine in historical_engines:
            combo_check={"status":"verified","reason":f"Engine/spec is in DG's year-bounded verified catalogue for {selected_year}.","spec_verified":True}
        else:
            combo_check=official_combo_verification(
                official_catalogue,selected_make,selected_model,selected_year,
                selected_fuel,selected_spec,selected_engine
            ) if selected_make and selected_model and selected_engine else {"status":"unavailable","reason":"Make, model and engine must be selected."}
        valuation_blocked=combo_check.get("status")=="blocked"
        if valuation_blocked:
            st.session_state["current_appraisal_ready"]=False
            st.session_state["current_appraisal_record"]=None
            st.error("VALUATION STOPPED — "+combo_check.get("reason","Vehicle configuration could not be verified.")+" The engine list has been refreshed to valid year-specific choices.")
        # Do not st.stop(): Streamlit must complete the rerun so the user can immediately
        # change a selection. A blocked combination simply skips valuation below.
        # Normalize any stale Streamlit state before result rendering.
        market = safe_market_snapshot(st.session_state.get("market_estimate")) if not valuation_blocked else None
        fresh_market=None
        if selected_make and selected_model and not valuation_blocked:
            try:
                with st.spinner("Checking live market and analysing deal…"):
                    comps=autoza_comparables(selected_make,selected_model,selected_year,100)
                    if not comps:
                        simple_model=re.sub(r"[^A-Za-z0-9 ]+"," ",selected_model).strip()
                        if simple_model and simple_model.lower()!=selected_model.lower():
                            comps=autoza_comparables(selected_make,simple_model,selected_year,100)
                    exact=[c for c in comps if matches_vehicle_choices(c,selected_engine,selected_fuel,selected_gearbox,selected_spec)]
                    cohort,tier_counts=build_comparable_cohort(
                        comps,selected_engine,selected_fuel,selected_gearbox,selected_spec,30)
                    fresh_market=estimate_market_from_comps(cohort or comps,selected_year,mileage)
                    if fresh_market:
                        fresh_market["selector_match_count"]=len(exact)
                        fresh_market["source_count"]=len(comps)
                        fresh_market["tier_counts"]=tier_counts
                        fresh_market["engine"]=selected_engine; fresh_market["fuel"]=selected_fuel; fresh_market["gearbox"]=selected_gearbox; fresh_market["spec"]=selected_spec
                        fresh_market["source"]=f'Closest current asking-price evidence from {len(comps)} source advert(s)'
                        st.session_state["market_estimate"]=fresh_market
                        st.session_state["market_retail"]=int(round(fresh_market["retail"]/50)*50)
            except Exception:
                fresh_market=None
        market = safe_market_snapshot(fresh_market if fresh_market else st.session_state.get("market_estimate"))

        # Rebuild risk AFTER the fresh market lookup. The old flow could mark the
        # whole deal High simply because no market snapshot existed before ANALYSE was tapped.
        vehicle_risk,vehicle_risk_reasons=analyse_risk(
            st.session_state.get("selected_year",2020),mileage,
            st.session_state.get("selected_make",""),st.session_state.get("selected_model",""),
            " ".join(x for x in [notes,source_advert] if x)
        )
        risk=vehicle_risk
        risk_reasons=list(vehicle_risk_reasons)
        if description_risk.get("level")=="High":
            risk="High"; risk_reasons.append("Seller description contains high-risk wording")
        elif description_risk.get("level")=="Medium" and risk=="Low":
            risk="Medium"; risk_reasons.append("Seller description contains cautionary wording")
        if description_risk.get("conflicts"):
            risk="High"; risk_reasons.append("Seller description conflicts with confirmed appraisal inputs")
        if detected_repair_cost>0:
            if detected_repair_cost>=1500: risk="High"
            elif risk=="Low": risk="Medium"
            risk_reasons.append(f"Description-derived repair allowance £{detected_repair_cost:,.0f}")
        if service_history=="None" and risk=="Low":
            risk="Medium"; risk_reasons.append("No service history")
        if provenance=="Issue found":
            risk="High"; risk_reasons.append("Provenance check found an issue")
        elif provenance=="Not checked" and risk=="Low":
            risk="Medium"; risk_reasons.append("Finance/write-off/theft provenance not checked")
        if v5c=="Missing / mismatch":
            risk="High"; risk_reasons.append("V5C missing or details mismatch")
        if insurance_category=="Cat S":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Cat S structural repair history requires verification")
        elif insurance_category=="Cat N":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Cat N repair quality/provenance requires verification")
        elif insurance_category=="Cat C (legacy)":
            risk="High"; risk_reasons.append("Legacy Cat C repair quality/provenance requires careful verification")
        elif insurance_category=="Cat D (legacy)":
            if risk=="Low": risk="Medium"
            risk_reasons.append("Legacy Cat D repair quality/provenance requires verification")
        elif insurance_category in ("Cat A","Cat B"):
            risk="High"; risk_reasons.append(f"{insurance_category} is not suitable for normal retail-road-car appraisal")
        elif insurance_category=="Other / unsure" and risk=="Low":
            risk="Medium"; risk_reasons.append("Insurance category needs verification")

        live_retail=float(st.session_state.get("market_retail",0) or 0) if fresh_market else 0.0
        appraisal_retail=float(retail or live_retail or 0)
        effective_mot_history_cost,mot_history_weight=weighted_mot_history_cost(mot_notes_cost,mot_months)
        contingency,all_in,margin,roi,max_buy,score,verdict=calc(asking,appraisal_retail,prep,fees,risk)
        max_buy=max(0,appraisal_retail-prep-fees-contingency-target_margin)
        verdict="BUY" if margin>=target_margin and roi>=st.session_state.min_roi and risk!="High" else ("RESEARCH" if margin>=target_margin*.6 and risk!="High" else "PASS")
        klass={"BUY":"good","RESEARCH":"warn","PASS":"bad"}[verdict]
        # Turn the raw live-market average into a recommendation for THIS car.
        market_average=float(appraisal_retail)
        category_adjustment=-(market_average*(category_discount/100.0))
        modification_adjustment=market_average*(float(modification_pct)/100.0)
        recommended_retail=max(0,
            market_average
            + category_adjustment
            + modification_adjustment
            + grade_adjustment
            + service_adjustment
            + keys_adjustment
            + mot_time_adj
            + manual_retail_adjustment
        )
        max_buy=max(0,recommended_retail-prep-fees-detected_repair_cost-effective_mot_history_cost-contingency-target_margin)
        target_buy=max_buy-250
        opening_offer=target_buy-250
        target_buy_display=f"£{target_buy:,.0f}" if target_buy>0 else "N/A"
        opening_offer_display=f"£{opening_offer:,.0f}" if opening_offer>0 else "N/A"
        contribution_at_ask=recommended_retail-(asking+prep+fees+detected_repair_cost+effective_mot_history_cost+contingency)
        roi_at_ask=(contribution_at_ask/(asking+prep+fees+detected_repair_cost+contingency)*100) if (asking+prep+fees+detected_repair_cost+contingency)>0 else 0

        st.markdown(f'<div class="card"><div class="label">DG appraisal</div><div class="car">{vehicle or "Vehicle appraisal"}</div><div class="meta">{reg or "No registration"} · {mileage:,} miles · {insurance_category}</div></div>',unsafe_allow_html=True)
        st.markdown(f"""<div class="card" style="border:2px solid #111827">
        <div class="label">WHAT TO DO</div>
        <div class="meta">Open at</div><div class="car">{opening_offer_display}</div>
        <div class="meta">Aim to buy at</div><div class="car">{target_buy_display}</div>
        <div class="meta">Do not pay more than</div><div class="car">£{max_buy:,.0f}</div>
        <hr>
        <div class="meta">Advertise at</div><div class="car">£{recommended_retail:,.0f}</div>
        </div>""",unsafe_allow_html=True)

        st.markdown('<div class="section">DG buyer overview</div>',unsafe_allow_html=True)
        if mot_months>4 and mot_notes_cost>0:
            st.caption(f"MOT history weighting: {mot_months} months remain, so prior MOT-note cost is weighted at 15% (£{effective_mot_history_cost:,.0f} of £{mot_notes_cost:,.0f}). Current condition still needs checking.")
        result_market=safe_market_snapshot(market,market_average)
        buyer_notes=dg_buyer_overview(market_average,recommended_retail,asking,max_buy,insurance_category,category_adjustment,condition_grade,service_history,keys,mot_months,mot_analysis,effective_mot_history_cost,prep,fees,contingency,target_margin,result_market["count"],result_market["low"],result_market["high"])
        for overview_title,overview_body in buyer_notes:
            st.markdown(f"**{overview_title}:** {overview_body}")
        if not isinstance(description_risk,dict):
            description_risk={"level":"Unknown","score":0,"flags":[],"positives":[],"questions":[],"conflicts":[]}
        if description_risk.get("level")!="Unknown":
            details=[]
            if description_risk.get("flags"): details.append(", ".join(description_risk["flags"]))
            if description_risk.get("conflicts"): details.append(f'{len(description_risk["conflicts"])} conflict(s) with entered appraisal data')
            st.markdown(f'**Seller-description risk:** {description_risk["level"]} — {"; ".join(details) if details else "no specific caution phrase recognised"}. Seller wording is unverified.')
        if source_advert.strip():
            st.markdown("**Seller advert context:** seller wording is treated as unverified until checked against the car, paperwork and provenance.")
            with st.expander("View source advert"):
                st.write(source_advert)
                if source_info.get("url"): st.markdown(f"[Open original advert]({source_info['url']} )")

        st.markdown('<div class="section">Why that retail price?</div>',unsafe_allow_html=True)
        a,b=st.columns(2); a.metric("Live market average",f"£{market_average:,.0f}"); b.metric("DG recommended retail",f"£{recommended_retail:,.0f}")
        st.markdown("**How DG got to that selling price**")
        st.caption(f"Context-sensitive defaults: {scaled_mot['age']}-year-old vehicle · live market context ~£{market_average:,.0f}. You can override every adjustment.")
        st.write(f"Live market average: **£{market_average:,.0f}**")
        st.write(f"{insurance_category}: **£{category_adjustment:+,.0f}** ({category_discount}% adjustment)")
        st.write(f"Condition grade {condition_grade}: **£{grade_adjustment:+,.0f}**")
        st.write(f"Service history ({service_history}): **£{service_adjustment:+,.0f}**")
        st.write(f"Keys ({keys}): **£{keys_adjustment:+,.0f}**")
        st.write(f"Modifications ({modification_level}): **£{modification_adjustment:+,.0f}** ({modification_pct:+.0f}%)")
        if modification_notes.strip(): st.caption("Modification notes: "+modification_notes.strip())
        st.write(f"MOT time remaining: **£{mot_time_adj:+,.0f}**")
        if manual_retail_adjustment:
            st.write(f"Other retail adjustment: **£{manual_retail_adjustment:+,.0f}**")
        st.write(f"**DG recommended retail: £{recommended_retail:,.0f}**")
        st.caption("These are editable appraisal assumptions. Actual preparation spend is deducted separately below, so the app does not hide repair costs inside the retail adjustment.")
        st.markdown("**How DG got to the maximum buy**")
        st.write(f"Recommended retail: **£{recommended_retail:,.0f}**")
        st.write(f"Prep: **−£{prep:,.0f}**")
        st.write(f"Other buying costs: **−£{fees:,.0f}**")
        if detected_repair_cost>0: st.write(f"Description-detected repairs: **−£{detected_repair_cost:,.0f}**")
        st.write(f"MOT advisory allowance: **−£{mot_notes_cost:,.0f}**")
        st.write(f"Contingency: **−£{contingency:,.0f}**")
        st.write(f"Required contribution: **−£{target_margin:,.0f}**")
        st.write(f"**Maximum buy: £{max_buy:,.0f}**")
        st.divider()
        if asking:
            if asking<=target_buy:
                st.success(f"Seller asking £{asking:,.0f}: inside DG target. Estimated contribution at asking: £{contribution_at_ask:,.0f}.")
            elif asking<=max_buy:
                st.warning(f"Seller asking £{asking:,.0f}: workable, but negotiate toward £{target_buy:,.0f}. Estimated contribution at asking: £{contribution_at_ask:,.0f}.")
            else:
                st.error(f"Seller asking £{asking:,.0f}: above DG maximum of £{max_buy:,.0f}. Negotiate down or leave it.")
        a,b=st.columns(2); a.metric("Contribution at asking",f"£{contribution_at_ask:,.0f}"); b.metric("ROI at asking",f"{roi_at_ask:.1f}%")
        st.caption(f"ROI means estimated contribution ÷ cash tied up at the asking price and entered costs. Here that is {roi_at_ask:.1f}%. A negative figure means the entered deal assumptions lose money before the target margin is considered.")


        st.markdown('<div class="section">What if things go wrong?</div>',unsafe_allow_html=True)
        downside_retail=max(0,recommended_retail-500)
        stress_retail=downside_retail-(asking+prep+fees+detected_repair_cost+effective_mot_history_cost+contingency)
        stress_prep=recommended_retail-(asking+prep+500+fees+mot_notes_cost+contingency)
        stress_both=downside_retail-(asking+prep+500+fees+mot_notes_cost+contingency)
        break_even=asking+prep+fees+effective_mot_history_cost+contingency
        st.caption("Quick downside check using the same costs as the main appraisal.")
        st.markdown(f"**£500 lower sale:** £{stress_retail:,.0f} contribution")
        st.caption("DG retail reduced by £500.")
        st.markdown(f"**£500 extra prep:** £{stress_prep:,.0f} contribution")
        st.caption("Prep costs £500 more than entered.")
        st.markdown(f"**Both together:** £{stress_both:,.0f} contribution")
        st.caption("Lower retail and extra prep happen together.")
        st.markdown(f"**Break-even sale price:** £{break_even:,.0f}")
        st.caption("Approximate sale price where contribution reaches £0, including the MOT advisory allowance.")
        if stress_both<0:
            st.error(f"Downside verdict: weak buffer — both changes would produce about a £{abs(stress_both):,.0f} loss.")
        elif stress_both<target_margin/2:
            st.warning(f"Downside verdict: thin buffer — about £{stress_both:,.0f} contribution remains.")
        else:
            st.success(f"Downside verdict: useful buffer — about £{stress_both:,.0f} contribution remains.")

        st.markdown('<div class="section">Quick risk check</div>',unsafe_allow_html=True)
        # Component risks are derived here so the UI cannot reference undefined legacy names.
        # Self-contained component risks: use only values definitely available in this result branch.
        mechanical_risk = "High" if vehicle_risk=="High" else ("Medium" if vehicle_risk=="Medium" else "Low")
        comparable_count = int(result_market.get("count",0) or 0)
        valuation_risk = "High" if comparable_count==0 else ("Medium" if comparable_count<5 else "Low")
        provenance_risk = "High" if provenance=="Issue found" or v5c=="Missing / mismatch" else ("Medium" if provenance=="Not checked" or v5c=="Not checked" else "Low")
        commercial_risk="Low" if stress_both>=target_margin*0.5 else ("Medium" if stress_both>0 else "High")
        description_level=description_risk.get("level","Unknown") if isinstance(description_risk,dict) else "Unknown"
        description_component="Medium" if description_level=="Unknown" else description_level
        risk_rank={"Low":1,"Medium":2,"High":3}
        overall_risk=max([mechanical_risk,valuation_risk,provenance_risk,commercial_risk,description_component],key=lambda x:risk_rank.get(x,2))
        st.markdown(f"**Overall buying risk: {overall_risk}**")
        st.caption("Low = more evidence/headroom · High = more caution.")
        st.write(f"Car/repair **{mechanical_risk}** · Valuation **{valuation_risk}** · History **{provenance_risk}** · Seller wording **{description_level}** · Deal **{commercial_risk}**")
        risk_notes=[]
        if mechanical_risk!="Low": risk_notes.append("mechanical/prep uncertainty")
        if valuation_risk!="Low": risk_notes.append(f"only {comparable_count} close comparable(s)")
        if provenance_risk!="Low": risk_notes.append("history/paperwork needs resolving")
        if commercial_risk=="High": risk_notes.append("small price/prep changes can wipe out margin")
        elif commercial_risk=="Medium": risk_notes.append("commercial headroom is limited")
        if risk_notes: st.caption("Why: "+" · ".join(risk_notes)+".")
        if mm and recommended_retail:
            delta=asking-recommended_retail
            st.caption(f"Seller asking is £{abs(delta):,.0f} {'below' if delta<0 else 'above'} DG recommended retail." if delta else "Seller asking matches DG recommended retail.")

        st.markdown('<div class="section">Market evidence</div>',unsafe_allow_html=True)
        comparable_count=int(result_market.get("count",0) or 0)
        exact_count=int(result_market.get("selector_match_count",0) or 0)
        source_count=int(result_market.get("source_count",comparable_count) or comparable_count)
        if comparable_count==0:
            st.markdown('<div class="market-note bad"><strong>No usable market sample</strong>No close current adverts were suitable enough for the valuation.</div>',unsafe_allow_html=True)
        elif exact_count<=1:
            st.markdown(f'<div class="market-note low"><strong>Limited exact-match evidence</strong>{exact_count} exact match(es), but DG found {source_count} same-model source advert(s) and used the closest {comparable_count} as supporting market evidence.</div>',unsafe_allow_html=True)
        elif comparable_count<5:
            st.markdown(f'<div class="market-note low"><strong>Limited market sample</strong>{exact_count} exact match(es) · {comparable_count} comparable advert(s) used.</div>',unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="market-note good"><strong>Useful current market sample</strong>{exact_count} exact match(es) · {comparable_count} closest comparable advert(s) used from {source_count} source advert(s).</div>',unsafe_allow_html=True)
        if comparable_count:
            low=float(result_market.get("low",0) or 0); high=float(result_market.get("high",0) or 0)
            st.write(f"Observed asking range: **£{low:,.0f}–£{high:,.0f}**" if comparable_count>1 else f"Current comparable asking price: **£{low:,.0f}**")
            rows=result_market.get("rows",[])
            if rows:
                with st.expander(f"View the {min(len(rows),10)} comparable advert(s) used"):
                    for i,car in enumerate(rows[:10],1):
                        price=_num(car,"price","asking_price","askingPrice") or 0
                        miles=_num(car,"mileage","miles","odometer") or 0
                        yr=int(_num(car,"year","registration_year","registrationYear") or 0)
                        title_txt=comparable_vehicle_label(car,selected_make,selected_model)
                        tier=str(car.get("_dg_match_tier","Comparable"))
                        st.markdown(f"**{i}. {yr or 'Year n/a'} {title_txt}**")
                        st.caption(f"{tier} · Asking £{price:,.0f}" + (f" · {int(miles):,} miles" if miles else ""))
        st.caption("DG prioritises exact matches, then progressively uses the closest same-model evidence when the exact derivative market is thin. Asking prices are not achieved sale prices.")

        appraisal_record={"date":datetime.now().strftime("%Y-%m-%d %H:%M"),"display_name":(reg.strip().upper() if str(reg or "").strip() else vehicle),"registration":reg,"vehicle":vehicle,"mileage":mileage,"asking":asking,"retail_est":appraisal_retail,"prep":prep,"fees":fees,"potential_contribution":round(margin,2),"roi_pct":round(roi,1),"max_buy":round(max_buy,2),"risk":risk,"score":score,"verdict":verdict,"notes":notes,"spec":selected_spec,"service_history":service_history,"keys":keys,"condition_grade":condition_grade,"grade_adjustment":grade_adjustment,"adjustment_age":scaled_mot["age"],"adjustment_market_value":round(market_average,2),"service_adjustment":service_adjustment,"keys_adjustment":keys_adjustment,"category":insurance_category,"category_discount":category_discount,"modification_level":modification_level,"modification_pct":modification_pct,"modification_adjustment":round(modification_adjustment,2),"modification_notes":modification_notes,"description_repair_allowance":detected_repair_cost,"description_repair_items":"; ".join(x["issue"] for x in repair_intel.get("items",[])),"recommended_retail":round(recommended_retail,2),"provenance":provenance,"v5c":v5c,"listing":""}
        st.session_state["current_appraisal_record"]=appraisal_record
        # Persist repair findings as part of the RESULT, not only as pre-submit form text.
        st.session_state["current_repair_result"]={
            "items":[dict(x) for x in repair_intel.get("items",[])],
            "allowance":detected_repair_cost,
            "multiplier":repair_intel.get("multiplier",1.0),
            "make":selected_make,"model":selected_model
        }
        # Persist a compact result summary so action buttons survive Streamlit button reruns.
        st.session_state["current_appraisal_ready"]=True

    # IMPORTANT: actions are intentionally OUTSIDE `if go:`. Streamlit reruns the script
    # when a button is clicked; nesting SAVE inside `if go:` made it disappear before its
    # click handler could reliably run.
    if st.session_state.get("current_appraisal_ready") and st.session_state.get("current_appraisal_record"):
        record_preview=st.session_state["current_appraisal_record"]
        repair_result=st.session_state.get("current_repair_result") or {}
        if repair_result.get("items"):
            st.markdown('<div class="section">Problems found in seller description</div>',unsafe_allow_html=True)
            for item in repair_result["items"]:
                st.warning(f'{item["issue"]} — estimated £{item["low"]:,.0f}–£{item["high"]:,.0f}; DG allowance £{item["allowance"]:,.0f}')
            st.markdown(f'**Total repair allowance factored into this appraisal: £{float(repair_result.get("allowance",0)):,.0f}**')
            st.caption(f'Cost scaling ×{float(repair_result.get("multiplier",1)):.2f} for {repair_result.get("make","")} {repair_result.get("model","")}. Confirm diagnosis before purchase.')
        elif record_preview.get("notes") or st.session_state.get("source_advert_text"):
            st.markdown('<div class="section">Problems found in seller description</div>',unsafe_allow_html=True)
            st.success("No unresolved repair phrase recognised automatically. Still inspect and diagnose the vehicle before purchase.")
        st.markdown('<div class="section">Finish appraisal</div>',unsafe_allow_html=True)
        reg_preview=str(record_preview.get("registration","") or "").strip().upper()
        if reg_preview:
            st.caption(f"Ready to save as **{reg_preview}**")
        save_col,new_col=st.columns(2)
        if save_col.button("SAVE APPRAISAL",use_container_width=True,type="primary",key="save_appraisal_btn"):
            record=dict(st.session_state["current_appraisal_record"])
            fingerprint="|".join(str(record.get(k,"")) for k in ("registration","vehicle","mileage","asking","recommended_retail"))
            if st.session_state.get("_last_saved_fingerprint")==fingerprint:
                st.info("This appraisal is already saved.")
            else:
                saved=pd.DataFrame([record])
                saved.loc[0,"date"]=datetime.now().strftime("%Y-%m-%d %H:%M")
                if DATA.exists():
                    try:
                        existing=pd.read_csv(DATA)
                        saved=pd.concat([existing,saved],ignore_index=True)
                    except Exception:
                        pass
                saved.to_csv(DATA,index=False)
                st.session_state["_last_saved_fingerprint"]=fingerprint
                st.success(f"Saved as {(str(record.get('registration','')).strip().upper() or str(record.get('vehicle','Vehicle appraisal')))}. Open SAVED APPRAISALS to view it.")
        if new_col.button("APPRAISE NEW VEHICLE",use_container_width=True,key="new_appraisal_btn"):
            reset_appraisal()
            st.rerun()
    st.markdown('</div>',unsafe_allow_html=True)

with tabs[2]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">Market intelligence</div><div class="hero">Market history</div><div class="sub">DG will build a genuine trend from appraisals you save over time.</div></div>',unsafe_allow_html=True)
    if DATA.exists():
        try:
            hist=pd.read_csv(DATA)
            st.metric("Saved market observations",f"{len(hist):,}")
            st.caption("As repeated comparable observations build up, this page can show real price movement rather than a decorative preview line.")
        except Exception:
            st.info("No usable saved market history yet.")
    else:
        st.info("No saved market history yet. Keep appraising cars and DG will build its own evidence.")
    st.markdown('</div>',unsafe_allow_html=True)

with tabs[1]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">DG appraisal library</div><div class="hero">Saved appraisals</div><div class="sub">Find previous appraisals by registration, vehicle, spec or notes.</div></div>',unsafe_allow_html=True)
    if DATA.exists():
        try:
            df=pd.read_csv(DATA)
        except Exception:
            df=pd.DataFrame()
        if not df.empty:
            if "date" in df.columns: df=df.sort_values("date",ascending=False)
            search=st.text_input("Search saved appraisals",placeholder="Search reg, vehicle, spec or notes…",key="saved_appraisal_search")
            if search.strip():
                q=search.strip().lower()
                search_cols=[c for c in ["registration","vehicle","spec","notes","date"] if c in df.columns]
                mask=df[search_cols].fillna("").astype(str).apply(lambda col: col.str.lower().str.contains(q,regex=False)).any(axis=1)
                view=df[mask]
            else:
                view=df
            st.caption(f"{len(view)} appraisal{'s' if len(view)!=1 else ''} shown · {len(df)} saved")
            if view.empty:
                st.info("No saved appraisal matches that search.")
            for _,r in view.iterrows():
                reg_name=str(r.get("registration","") or "").strip().upper()
                appraisal_name=reg_name if reg_name else str(r.get("vehicle","Vehicle appraisal") or "Vehicle appraisal")
                vehicle_name=str(r.get("vehicle","Vehicle") or "Vehicle")
                klass={"BUY":"good","BUY CANDIDATE":"good","RESEARCH":"warn","INVESTIGATE":"warn","PASS":"bad"}.get(str(r.get("verdict")),"warn")
                saved_date=str(r.get("date",""))
                mileage_val=float(r.get("mileage",0) or 0)
                st.markdown(f'<div class="card"><div class="label">SAVED APPRAISAL</div><div class="car">{appraisal_name}</div><div class="meta">{vehicle_name} · {mileage_val:,.0f} miles · Saved {saved_date}</div><span class="chip {klass}">{r.get("verdict","")}</span></div>',unsafe_allow_html=True)
                a,b,c=st.columns(3)
                a.metric("Ask",f"£{float(r.get('asking',0) or 0):,.0f}")
                b.metric("Retail",f"£{float(r.get('recommended_retail',r.get('retail_est',0)) or 0):,.0f}")
                c.metric("Max buy",f"£{float(r.get('max_buy',0) or 0):,.0f}")
                st.caption(f"Target contribution result: £{float(r.get('potential_contribution',0) or 0):,.0f} · Risk {r.get('risk','')} · Score {int(float(r.get('score',0) or 0))}")
            st.download_button("Export saved appraisals",view.to_csv(index=False).encode(),"dg_saved_appraisals.csv","text/csv",use_container_width=True)
        else:
            st.info("No saved appraisals yet.")
    else:
        st.info("No saved appraisals yet. Save an appraisal and it will appear here under its registration.")
    st.markdown('</div>',unsafe_allow_html=True)

with tabs[3]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">Buying discipline</div><div class="hero">Your rules</div><div class="sub">Set the economics every stock opportunity has to clear.</div></div>',unsafe_allow_html=True)
    st.session_state.min_profit=st.number_input("Minimum contribution (£)",0,10000,int(st.session_state.min_profit),50)
    st.session_state.min_roi=st.number_input("Minimum ROI (%)",0,200,int(st.session_state.min_roi),1)
    st.session_state.contingency_pct=st.number_input("Prep contingency (%)",0,100,int(st.session_state.contingency_pct),5)
    st.markdown('<div class="card"><div class="meta"><b>Contribution</b> is estimated retail less purchase, prep, selling costs and prep contingency. It is not net profit after fixed overhead, tax or finance.</div></div></div>',unsafe_allow_html=True)