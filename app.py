import csv
from urllib.parse import urlencode
from urllib.parse import quote
from io import BytesIO
from urllib.request import Request, urlopen
import streamlit as st
import io
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import json
import urllib.parse
import urllib.request
import urllib.error
import re
import statistics
import datetime
import html
import base64
import mimetypes
from urllib.parse import urlencode, urlparse, parse_qs, quote
from html import unescape
from urllib.parse import quote

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



DG_INTEL_BANK=Path(__file__).with_name("dg_buying_intelligence.csv")
DG_INTEL_FIELDS=["fingerprint","make","model","year_from","year_to","engine_terms","fuel","gearbox","issue",
                 "severity","ask","check","cost_low","cost_high","source","source_url","evidence_type",
                 "confidence","first_seen","last_seen","times_seen"]

def dg_load_intel_bank():
    if not DG_INTEL_BANK.exists(): return []
    try:
        with DG_INTEL_BANK.open("r",encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
    except Exception:return []

def dg_store_intel(rows):
    """Merge sourced intelligence into DG's bank. No source => no learned fact."""
    if not rows:return
    now=datetime.datetime.now().strftime("%Y-%m-%d")
    old=dg_load_intel_bank(); by={r.get("fingerprint",""):r for r in old if r.get("fingerprint")}
    for r in rows:
        if not r.get("source") or not r.get("issue"): continue
        fp=_dg_norm("|".join(map(str,[r.get("make",""),r.get("model",""),r.get("issue",""),r.get("source","")])))
        if not fp: continue
        if fp in by:
            x=by[fp]; x["last_seen"]=now
            try:x["times_seen"]=str(int(x.get("times_seen") or 1)+1)
            except:x["times_seen"]="2"
        else:
            x={k:str(r.get(k,"") or "") for k in DG_INTEL_FIELDS}; x["fingerprint"]=fp
            x["first_seen"]=now;x["last_seen"]=now;x["times_seen"]="1";by[fp]=x
    try:
        with DG_INTEL_BANK.open("w",encoding="utf-8",newline="") as f:
            wr=csv.DictWriter(f,fieldnames=DG_INTEL_FIELDS);wr.writeheader();wr.writerows(by.values())
    except Exception:pass

def dg_bank_buying_intelligence(make,model,year,engine,fuel,gearbox=""):
    hay=_dg_norm(" ".join(map(str,[engine,fuel,gearbox])))
    out=[]
    for r in dg_load_intel_bank():
        if _dg_norm(r.get("make",""))!=_dg_norm(make):continue
        rm=_dg_norm(r.get("model",""))
        if rm and rm!=_dg_norm(model):continue
        try:
            yf=int(float(r.get("year_from") or 0)); yt=int(float(r.get("year_to") or 9999))
            if year and not(yf<=int(year)<=yt):continue
        except:pass
        terms=[_dg_norm(x) for x in str(r.get("engine_terms","")).split("|") if x.strip()]
        if terms and not any(t in hay for t in terms):continue
        out.append(r)
    return out


DG_WEB_ISSUE_PATTERNS=[
 ("Timing belt / wet belt",["wet belt","timing belt","belt degradation"],"High",
  "Has the timing belt/wet belt been inspected or replaced? When, at what mileage, and is there an invoice?",
  "Check documented belt history, correct oil/service history and any oil-pressure warnings.",500,1800),
 ("Timing chain",["timing chain","chain rattle","chain stretch"],"High",
  "Has the timing chain or tensioner ever been inspected or replaced? Is there an invoice?",
  "Listen for cold-start rattle and verify oil-change history.",700,2500),
 ("Automatic gearbox / transmission",["gearbox problem","transmission problem","transmission failure","gearbox failure"],"High",
  "Has the gearbox been serviced or repaired? When was the fluid/filter last changed and is there an invoice?",
  "Road-test from cold and hot for delay, flare, shudder, harsh shifts or warning messages.",500,3500),
 ("DSG / dual-clutch gearbox",["dsg problem","dsg failure","mechatronic","dual clutch"],"High",
  "Has the DSG/dual-clutch gearbox had its required servicing, clutch or mechatronic work? Is there an invoice?",
  "Check service evidence and road-test for judder, hesitation and harsh engagement.",500,3000),
 ("DPF / emissions system",["dpf problem","dpf failure","diesel particulate filter","dpf blocked"],"Medium",
  "Has the DPF ever been cleaned or replaced, and has the car had any recurring emissions warnings?",
  "Check warning lights, regeneration history where available and whether usage suits a diesel.",250,1800),
 ("AdBlue / SCR system",["adblue problem","adblue fault","scr fault","adblue failure"],"Medium",
  "Has the AdBlue/SCR system had any repairs, warning countdowns or replacement parts?",
  "Check dash warnings and diagnostic history for SCR/NOx/AdBlue faults.",300,1800),
 ("Cooling system",["coolant leak","water pump failure","thermostat failure","cooling system problem"],"Medium",
  "Has the water pump, thermostat or any major cooling-system component been replaced? Is there evidence?",
  "Inspect coolant level/leaks and check warm-up temperature and overheating history.",250,1500),
 ("Air suspension",["air suspension problem","air suspension failure","air spring failure"],"High",
  "Has any air-suspension compressor, strut or air spring been replaced? Is there an invoice?",
  "Check ride height after standing, compressor operation and suspension warnings.",500,3000),
 ("Transfer case / AWD",["transfer case problem","transfer box problem","transfer case failure","xdrive problem"],"High",
  "Has the transfer case/transfer box had fluid changes or repairs? Are all four tyres correctly matched?",
  "Road-test tight turns for binding/judder and inspect tyre size/tread matching.",500,2500),
 ("Turbocharger",["turbo failure","turbo problem","turbocharger failure"],"High",
  "Has the turbo ever been replaced or investigated? Any oil-use, smoke or boost issues?",
  "Check cold start, smoke, boost delivery, oil leaks and service history.",600,2500),
]

def _dg_strip_html(x):
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",str(x or "")))).strip()



DG_CORE_RISK_BANK = [
 {"make":"Volkswagen","models":["Golf","Polo","Passat","Tiguan"],"fuel":"Diesel","issue":"EGR/DPF emissions-system faults are common buying checks on diesel VWs","severity":"High","ask":"Any EGR, DPF or emissions work, warning lights or forced regenerations? Are there invoices?","check":"Cold start, warning lights, smoke, limp mode and evidence of EGR/DPF work.","cost_low":400,"cost_high":1800},
 {"make":"Volkswagen","models":["Golf","Polo","Passat","Tiguan"],"fuel":"","issue":"DSG mechatronic/clutch faults are a known risk on DSG-equipped cars","severity":"High","ask":"Has the DSG had clutch, mechatronic or oil-service work?","check":"Check for judder, delayed drive engagement, harsh shifts and DSG service evidence.","cost_low":800,"cost_high":2500,"gearbox_terms":["dsg","automatic"]},
 {"make":"Audi","models":["A1","A3","A4","A5","A6"],"fuel":"Diesel","issue":"Diesel emissions, EGR/DPF and related intake faults are important checks","severity":"High","ask":"Any EGR, DPF, intake or emissions-system repairs or warning lights?","check":"Check cold start, smoke, warning lights, limp mode and invoices.","cost_low":400,"cost_high":1800},
 {"make":"Audi","models":["A3","A4","A5","A6"],"fuel":"","issue":"Automatic gearbox/mechatronic servicing and faults need checking","severity":"High","ask":"Has the automatic gearbox had its scheduled oil service or any mechatronic/clutch repairs?","check":"Test from cold and hot for judder, hesitation and harsh engagement.","cost_low":800,"cost_high":3000,"gearbox_terms":["automatic","s tronic","multitronic","dsg"]},
 {"make":"BMW","models":["1 Series","2 Series","3 Series","4 Series","5 Series","X1","X3"],"fuel":"Diesel","issue":"Timing-chain condition and diesel emissions hardware are key BMW diesel buying checks","mileage_from":60000,"mileage_note":'Extra scrutiny from roughly 60k miles.',"severity":"High","ask":"Any timing-chain, EGR, DPF or turbo work? Are there invoices or recall records?","check":"Listen from cold for chain noise; check EGR/DPF warnings, smoke and service history.","cost_low":700,"cost_high":2500},
 {"make":"Peugeot","models":["208","2008","308","3008","5008"],"fuel":"Petrol","issue":"PureTech petrol engines can require careful timing-belt/oil-system history checks","severity":"High","ask":"Has the timing belt been inspected/replaced and is the correct oil documented?","check":"Verify engine type, belt history, oil-pressure warnings and service invoices.","cost_low":500,"cost_high":1800},
 {"make":"Peugeot","models":["208","2008","308","3008","5008"],"fuel":"Diesel","issue":"BlueHDi AdBlue/SCR faults and emissions-system repairs are common buying checks","severity":"High","ask":"Any AdBlue tank, injector, NOx sensor, EGR or DPF work?","check":"Check countdown/emissions warnings, AdBlue history and invoices.","cost_low":500,"cost_high":1500},
 {"make":"Citroen","models":["C3","C4","C5 Aircross","Berlingo"],"fuel":"Petrol","issue":"PureTech petrol engines can require careful timing-belt/oil-system history checks","severity":"High","ask":"Has the timing belt been inspected/replaced and is the correct oil documented?","check":"Verify engine type, belt history, oil-pressure warnings and service invoices.","cost_low":500,"cost_high":1800},
 {"make":"Citroen","models":["C3","C4","C5 Aircross","Berlingo"],"fuel":"Diesel","issue":"BlueHDi AdBlue/SCR and emissions-system faults are important checks","severity":"High","ask":"Any AdBlue tank, NOx sensor, EGR or DPF work?","check":"Check emissions warnings, countdown messages and repair invoices.","cost_low":500,"cost_high":1500},
 {"make":"Ford","models":["Fiesta","Focus","EcoSport","Puma"],"fuel":"Petrol","issue":"EcoBoost timing-belt/cooling-system history can be a major buying risk on affected engines","severity":"High","ask":"Is it an EcoBoost, and if so has the timing belt and cooling-system work been documented?","check":"Confirm engine family first; inspect belt/service evidence, coolant level and overheating history.","cost_low":600,"cost_high":2200},
 {"make":"Ford","models":["Fiesta","Focus","Kuga"],"fuel":"","issue":"PowerShift automatic gearbox faults are a significant risk on affected cars","severity":"High","ask":"Is it PowerShift, and has the gearbox had clutch/mechatronic repairs and scheduled servicing?","check":"Check for judder, hesitation, warning messages and repair invoices.","cost_low":900,"cost_high":2500,"gearbox_terms":["automatic","powershift"]},
 {"make":"Nissan","models":["Qashqai","Juke","Micra","X-Trail"],"fuel":"","issue":"CVT condition is a major buying check on CVT-equipped Nissans","mileage_from":60000,"mileage_note":'Transmission history becomes increasingly important around 60k+ miles.',"severity":"High","ask":"Is it CVT, and has the transmission fluid been serviced or the gearbox repaired?","check":"Check for flare, shudder, whining, delayed engagement and gearbox warnings.","cost_low":1200,"cost_high":3500,"gearbox_terms":["automatic","cvt"]},
 {"make":"Land Rover","models":["Range Rover Evoque","Discovery Sport","Range Rover Sport","Discovery"],"fuel":"Diesel","issue":"Diesel timing-chain, DPF/EGR and oil-dilution history can create expensive exposure","severity":"High","ask":"Any timing-chain, DPF, EGR, turbo or oil-dilution related work?","check":"Cold-start chain noise, oil level/history, emissions warnings and invoices.","cost_low":900,"cost_high":3500},
 {"make":"Jaguar","models":["XE","XF","F-Pace","E-Pace"],"fuel":"Diesel","issue":"Ingenium diesel timing-chain and emissions-system history are important buying checks","mileage_from":50000,"mileage_note":'Extra scrutiny from roughly 50k miles; service interval/history matters.',"severity":"High","ask":"Any timing-chain, DPF, EGR, turbo or oil-dilution related work?","check":"Listen from cold, inspect service intervals/oil history and check emissions warnings.","cost_low":900,"cost_high":3500},
 {"make":"Mercedes-Benz","models":["A-Class","B-Class","C-Class","E-Class","CLA","GLA"],"fuel":"Diesel","issue":"Diesel emissions hardware, AdBlue/NOx and DPF/EGR faults can be costly","severity":"High","ask":"Any AdBlue, NOx sensor, EGR, DPF or emissions repairs?","check":"Check warning messages, limp mode, emissions history and invoices.","cost_low":500,"cost_high":1800},
 {"make":"Honda","models":["Civic","Accord","CR-V"],"fuel":"Diesel","issue":"Clutch/dual-mass flywheel and diesel emissions condition are worthwhile checks","severity":"High","ask":"Any clutch/DMF, EGR or DPF work?","check":"Check clutch bite/slip, DMF noise, smoke and emissions warnings.","cost_low":700,"cost_high":1800},
]


DG_BROAD_RISK_BANK = [
 {"makes":["Jaguar","Land Rover"],"fuel":"Diesel","issue":"DPF/EGR and emissions-system faults are important diesel buying checks","severity":"Medium","ask":"Any DPF, EGR, emissions warnings or forced regenerations?","check":"Check warning lights, smoke, limp mode, regeneration history and invoices.","cost_low":350,"cost_high":1800,"mileage_from":50000,"mileage_note":"More relevant as mileage and short-trip use build."},
 {"makes":["Jaguar","Land Rover"],"fuel":"Diesel","issue":"Turbo, boost-hose and intake faults can create expensive diesel problems","severity":"Medium","ask":"Any turbo, intercooler, boost-hose or intake repairs?","check":"Check boost delivery, smoke, whistle, oil leaks and stored boost faults.","cost_low":250,"cost_high":2200,"mileage_from":60000,"mileage_note":"Give extra attention on higher-mileage cars."},
 {"makes":["Jaguar","Land Rover"],"fuel":"","issue":"Suspension arms, bushes and wheel bearings are worthwhile checks on heavier models","severity":"Medium","ask":"Any suspension arm, bush or wheel-bearing work?","check":"Listen for knocks; inspect tyre wear and check for play/noise.","cost_low":250,"cost_high":1200,"mileage_from":50000},
 {"makes":["Jaguar","Land Rover"],"fuel":"","issue":"Electrical, battery, camera and infotainment faults are worthwhile model-wide checks","severity":"Medium","ask":"Any battery drain, electrical warnings, camera, screen or infotainment faults?","check":"Test every electrical function and battery/charging health.","cost_low":150,"cost_high":1500},
 {"makes":["Jaguar","Land Rover"],"fuel":"","issue":"Water ingress and tailgate/door seal problems are worth checking","severity":"Medium","ask":"Any water leaks, damp carpets, boot water or electrical issues after rain?","check":"Inspect carpets, spare-wheel well, headlining and seals for damp/water marks.","cost_low":100,"cost_high":1000},
 {"makes":["BMW","Mercedes-Benz","Audi","Volkswagen","Skoda","SEAT"],"fuel":"Diesel","issue":"DPF/EGR/NOx emissions hardware is a common diesel buying-risk area","severity":"Medium","ask":"Any DPF, EGR, NOx sensor or emissions repairs?","check":"Check warnings, regeneration history, smoke and stored faults.","cost_low":350,"cost_high":1800,"mileage_from":60000},
 {"makes":["BMW","Mercedes-Benz","Audi"],"fuel":"","issue":"Cooling-system leaks, pumps and thermostats deserve inspection as mileage builds","severity":"Medium","ask":"Any coolant leaks, water-pump, thermostat or overheating work?","check":"Check coolant level, leaks and temperature stability.","cost_low":250,"cost_high":1200,"mileage_from":60000},
 {"makes":["Peugeot","Citroen","DS"],"fuel":"Diesel","issue":"AdBlue/SCR/NOx faults are important BlueHDi buying checks","severity":"High","ask":"Any AdBlue tank, pump, injector, NOx sensor or countdown faults?","check":"Check emissions countdown/warnings and invoices.","cost_low":500,"cost_high":1600,"mileage_from":50000},
 {"makes":["Peugeot","Citroen","DS"],"fuel":"Petrol","issue":"On affected PureTech engines, timing-belt degradation and oil-system history require verification","severity":"High","ask":"Confirm engine type. If PureTech, has the belt been inspected/replaced and correct oil used?","check":"Verify engine family before applying this risk; inspect belt/service evidence.","cost_low":500,"cost_high":1800},
 {"makes":["Ford"],"fuel":"Diesel","issue":"DPF/EGR, turbo and injector condition are important higher-mileage diesel checks","severity":"Medium","ask":"Any DPF, EGR, turbo or injector work?","check":"Check smoke, boost, warning lights and invoices.","cost_low":350,"cost_high":1800,"mileage_from":60000},
 {"makes":["Nissan","Renault"],"fuel":"Diesel","issue":"DPF/EGR and turbo/injector condition are worthwhile diesel checks","severity":"Medium","ask":"Any DPF, EGR, turbo or injector repairs?","check":"Check smoke, cold start, boost and emissions warnings.","cost_low":350,"cost_high":1800,"mileage_from":60000},
 {"makes":["Vauxhall"],"fuel":"Diesel","issue":"DPF/EGR and emissions-system condition are important diesel checks","severity":"Medium","ask":"Any DPF, EGR or emissions repairs?","check":"Check warning lights, regeneration history and smoke.","cost_low":350,"cost_high":1600,"mileage_from":60000},
 {"makes":["Toyota","Lexus"],"fuel":"Hybrid","issue":"Hybrid battery health and cooling-system condition should be verified","severity":"Medium","ask":"Any hybrid battery repairs or health checks?","check":"Check hybrid warnings, battery cooling intake and available health-check history.","cost_low":300,"cost_high":2500,"mileage_from":80000},
]
def dg_core_risk_matches(make,model,fuel,gearbox):
    import unicodedata as _ud
    def _key(v):
        v=_ud.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().lower()
        return re.sub(r"[^a-z0-9]+","",v)
    mk=_key(make); md=str(model or "").strip().lower()
    fu=_key(fuel); gb=str(gearbox or "").strip().lower()
    out=[]
    for r in DG_CORE_RISK_BANK:
        if _key(r["make"])!=mk: continue
        if not any(x.lower()==md or x.lower() in md or md in x.lower() for x in r["models"]): continue
        if r.get("fuel") and _key(r["fuel"])!=fu: continue
        terms=[str(x).lower() for x in r.get("gearbox_terms",[])]
        if terms and not any(t in gb for t in terms): continue
        q=dict(r)
        q.update({"year_from":"","year_to":"","engine_terms":"","source":"DG core UK buying-risk bank",
                  "source_url":"https://www.caradvertcheck.co.uk/car-data",
                  "evidence_type":"broader model/fuel buying risk — confirm applicability","confidence":"Low"})
        out.append(q)
    for r in DG_BROAD_RISK_BANK:
        if mk not in [_key(x) for x in r.get("makes",[])]: continue
        if r.get("fuel") and _key(r.get("fuel"))!=fu: continue
        q=dict(r)
        q.update({"year_from":"","year_to":"","engine_terms":"","source":"DG broader UK buying-risk bank",
                  "source_url":"","evidence_type":"broader make/model-family + fuel risk — confirm applicability","confidence":"Low"})
        out.append(q)
    seen=set(); clean=[]
    for q in out:
        k=str(q.get("issue","")).strip().lower()
        if k and k not in seen:
            seen.add(k); clean.append(q)
    return clean

def dg_model_fault_page(make,model,year,engine,fuel,gearbox):
    """Read a free public UK model-fault page directly; return sourced issues, never guessed faults."""
    import re as _re
    from html import unescape as _unescape
    from urllib.parse import quote as _quote
    def slug(x):
        x=str(x or "").strip().lower().replace("&","and")
        return _re.sub(r"[^a-z0-9]+","-",x).strip("-")
    url=f"https://www.caradvertcheck.co.uk/problems/{slug(make)}/{slug(model)}"
    try:
        req=Request(url,headers={"User-Agent":"Mozilla/5.0 DG-Deal-Finder/1.0","Accept":"text/html"})
        with urlopen(req,timeout=4) as resp:
            raw=resp.read().decode("utf-8","replace")
    except Exception:
        return {"status":"unavailable","issues":[],"url":url}
    # Convert headings/paragraphs/list text into compact lines without external parser deps.
    x=_re.sub(r"(?is)<(script|style).*?>.*?</\\1>"," ",raw)
    x=_re.sub(r"(?i)</?(?:h1|h2|h3|h4|p|li|div|br)[^>]*>","\n",x)
    x=_unescape(_re.sub(r"(?s)<[^>]+>"," ",x))
    lines=[" ".join(z.split()) for z in x.splitlines()]
    lines=[z for z in lines if z]
    eng=str(engine or "").lower()
    yr=int(year) if str(year or "").isdigit() else 0
    issues=[]
    # Site uses issue headings followed by Rough guide / symptoms / affected vehicles.
    for i,line in enumerate(lines):
        low=line.lower()
        if not any(k in low for k in ["failure","premature","stretch","snapping","fault","leak","overheat","consumption","breakage","crystallization","contamination"]):
            continue
        if len(line)<18 or len(line)>220: continue
        context=" | ".join(lines[i:min(i+14,len(lines))])
        # Prefer exact engine evidence when the page gives affected-engine detail.
        engine_ok=(not eng) or any(tok in context.lower() for tok in _re.findall(r"[a-z0-9]+",eng) if len(tok)>=3)
        # Keep model-level evidence even when the exact engine token is absent.
        # Applicability is surfaced as broader evidence rather than silently discarded.
        _broad_applicability=("affected vehicles" in context.lower() and not engine_ok)
        money=_re.search(r"£\s*([0-9,]+)\s*[-–]\s*£?\s*([0-9,]+)",context)
        lo=hi=0
        if money:
            lo=float(money.group(1).replace(",","")); hi=float(money.group(2).replace(",",""))
        ask=f"Has the car had any work relating to {line.rstrip('.').lower()}, and is there an invoice?"
        check="Check service/repair invoices and inspect/test specifically for the listed symptoms before buying."
        issues.append({"make":make,"model":model,"year_from":year or "","year_to":year or "",
          "engine_terms":str(engine or ""),"fuel":fuel,"gearbox":gearbox,"issue":line.rstrip("."),
          "severity":"High" if any(k in low for k in ["engine","chain","belt","gearbox","overheat","break"]) else "Medium",
          "ask":ask,"check":check,"cost_low":lo,"cost_high":hi,
          "source":"Car Advert Check UK model fault data","source_url":url,
          "evidence_type":("model-level fault evidence — confirm engine applicability" if _broad_applicability else "model fault database + specialist/owner/recall sources"),
          "confidence":("Low" if _broad_applicability else "Medium")})
        if len(issues)>=6: break
    return {"status":"found" if issues else "insufficient","issues":issues,"url":url}

DG_ISSUE_BANK=Path(__file__).with_name("dg_issue_bank.csv")

@st.cache_data(show_spinner=False)
def dg_load_issue_bank():
    try:
        import csv
        with DG_ISSUE_BANK.open("r",encoding="utf-8-sig",newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []

def dg_structured_issue_matches(make,model,year,engine,fuel,gearbox,mileage=0):
    import unicodedata as _ud
    def key(v):
        return re.sub(r"[^a-z0-9]+","",_ud.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().lower())
    mk,md,fu,gb=key(make),key(model),key(fuel),key(gearbox)
    hay=key(" ".join(map(str,[engine,gearbox])))
    out=[]
    for r in dg_load_issue_bank():
        if key(r.get("make"))!=mk: continue
        rm=r.get("model","")
        if rm not in ("","*") and key(rm) not in md and md not in key(rm): continue
        rf=key(r.get("fuel"))
        if rf and rf!=fu: continue
        try:
            y=int(year or 0); y0=int(float(r.get("year_from") or 0)); y1=int(float(r.get("year_to") or 9999))
            if y and not (y0<=y<=y1): continue
        except Exception: pass
        terms=[key(x) for x in str(r.get("engine_terms","")).split("|") if x.strip()]
        if terms and hay and not any(t in hay for t in terms): continue
        gterms=[key(x) for x in str(r.get("gearbox_terms","")).split("|") if x.strip()]
        if gterms and gb and not any(t in gb for t in gterms): continue
        q=dict(r)
        for k in ("cost_low","cost_high","mileage_from","mileage_to"):
            try:q[k]=float(q.get(k) or 0)
            except:q[k]=0
        q["source"]=q.get("source") or "DG structured evidence bank"
        out.append(q)
    return out

DG_BAD_ISSUE_PHRASES=[
 "years and engines with","common problems","known faults","known problems",
 "what to look for","things to check","buying guide","common issues",
 "years affected","engines affected","serious known fault"
]
DG_COMPONENT_TERMS=[
 "bearing","chain","belt","gearbox","transmission","clutch","flywheel","turbo","injector",
 "pump","thermostat","coolant","radiator","engine","piston","ring","valve","egr","dpf",
 "adblue","scr","nox","sensor","rack","steering","suspension","bush","spring","damper",
 "alternator","starter","battery","ecu","mechatronic","actuator","compressor","oil",
 "water","seal","leak","cylinder","head gasket","timing","ims","bore","scoring"
]
DG_FAILURE_TERMS=[
 "fail","failure","wear","worn","stretch","snap","break","broken","crack","leak","fault",
 "judder","rattle","overheat","corrosion","consumption","starvation","loss","damage",
 "seiz","blocked","clog","misfire","slip","noise"
]

def dg_issue_quality(row):
    text=" ".join(str(row.get(k,"")) for k in ("issue","ask","check")).lower()
    issue=str(row.get("issue","")).strip().lower()
    if not issue or len(issue)<12:return 0
    if any(p in issue for p in DG_BAD_ISSUE_PHRASES):return 0
    has_component=any(x in text for x in DG_COMPONENT_TERMS)
    has_failure=any(x in text for x in DG_FAILURE_TERMS)
    score=(2 if has_component else 0)+(2 if has_failure else 0)
    if row.get("source"):score+=1
    if row.get("year_from") or row.get("engine_terms"):score+=1
    return score

def dg_clean_issue_rows(rows):
    good=[]
    for r in rows or []:
        if dg_issue_quality(r)<4: continue
        # Generic auto-generated seller questions are replaced with a direct evidence request.
        ask=str(r.get("ask","")).strip()
        issue=str(r.get("issue","")).strip()
        if (not ask) or ("work relating to" in ask.lower()):
            component=issue.split(":")[-1].strip()
            r=dict(r); r["ask"]=f"Has this specific issue been inspected or repaired? If yes, at what mileage and is there an invoice? ({component[:90]})"
        good.append(r)
    # Near-duplicate suppression: specific/longer issue wins.
    good.sort(key=lambda x:(dg_issue_quality(x),len(str(x.get("issue","")))),reverse=True)
    final=[]
    for r in good:
        norm=re.sub(r"[^a-z0-9]+"," ",str(r.get("issue","")).lower()).strip()
        toks=set(norm.split())
        duplicate=False
        for e in final:
            en=set(re.sub(r"[^a-z0-9]+"," ",str(e.get("issue","")).lower()).split())
            if toks and en and len(toks&en)/max(1,min(len(toks),len(en)))>=0.75:
                duplicate=True;break
        if not duplicate:final.append(r)
    return final
@st.cache_data(ttl=86400,show_spinner=False)
def dg_web_research(make,model,year,engine,fuel,gearbox):
    """Live no-key research with explicit status. Never equates blocked search with 'no issues'."""
    from urllib.parse import quote_plus as _q
    import json as _json
    vehicle=" ".join(str(x).strip() for x in [year,make,model,engine,fuel,gearbox] if str(x or "").strip())
    texts=[]; sources=[]; transport_ok=False
    direct=dg_model_fault_page(make,model,year,engine,fuel,gearbox)
    direct_issues=direct.get("issues",[]) if isinstance(direct,dict) else []
    _dg_match_level="exact"
    # If exact engine/spec evidence is thin, progressively broaden to model + fuel,
    # then model-only. This improves coverage without presenting broader evidence as exact.
    if not direct_issues and fuel:
        _broad=dg_model_fault_page(make,model,year,"",fuel,"")
        direct_issues=_broad.get("issues",[]) if isinstance(_broad,dict) else []
        if direct_issues:
            _dg_match_level="model_fuel"
            for _r in direct_issues:
                _r["confidence"]="Medium"
                _r["evidence_type"]="model + fuel-type fault evidence"
                _r["issue"]="[Model/fuel] "+str(_r.get("issue","Known issue"))
    if not direct_issues:
        _broad2=dg_model_fault_page(make,model,year,"","","")
        direct_issues=_broad2.get("issues",[]) if isinstance(_broad2,dict) else []
        if direct_issues:
            _dg_match_level="model"
            for _r in direct_issues:
                _r["confidence"]="Low"
                _r["evidence_type"]="model-level fault evidence — confirm engine applicability"
                _r["issue"]="[Model-level] "+str(_r.get("issue","Known issue"))
    if isinstance(direct,dict) and direct.get("status")!="unavailable":
        transport_ok=True

    # DuckDuckGo Instant Answer is supplemental discovery, not the sole evidence source.: structured/no-key. It is not a full SERP,
    # so absence of deep fault results is "insufficient", not "no known issues".
    for suffix in [" common problems reliability", " "+str(fuel or "")+" common faults", " recalls service campaigns", " buying guide problems", " engine gearbox problems"]:
        try:
            url="https://api.duckduckgo.com/?q="+_q(vehicle+suffix)+"&format=json&no_html=1&skip_disambig=1"
            req=Request(url,headers={"User-Agent":"DG-Deal-Finder/1.0","Accept":"application/json"})
            with urlopen(req,timeout=4) as resp:
                data=_json.loads(resp.read().decode("utf-8","replace")); transport_ok=True
            for k in ("AbstractText","Answer","Definition"):
                if data.get(k): texts.append(str(data[k]))
            if data.get("AbstractURL"): sources.append({"domain":"duckduckgo.com","url":data["AbstractURL"]})
            def walk(items):
                for it in items or []:
                    if isinstance(it,dict):
                        if it.get("Text"): texts.append(str(it["Text"]))
                        if it.get("FirstURL"): sources.append({"domain":_dg_domain(it["FirstURL"]),"url":it["FirstURL"]})
                        walk(it.get("Topics"))
            walk(data.get("RelatedTopics"))
        except Exception:
            pass

    blob=" ".join(texts).lower()
    learned=[]
    for issue,terms,severity,ask,check,lo,hi in DG_WEB_ISSUE_PATTERNS:
        matched=[t for t in terms if t in blob]
        if not matched: continue
        doms=sorted(set(x["domain"] for x in sources if x.get("domain")))
        learned.append({"make":make,"model":model,"year_from":year or "","year_to":year or "",
          "engine_terms":str(engine or ""),"fuel":fuel,"gearbox":gearbox,"issue":issue,"severity":severity,
          "ask":ask,"check":check,"cost_low":lo,"cost_high":hi,
          "source":" + ".join(doms[:3]) or "DuckDuckGo structured web evidence",
          "source_url":sources[0]["url"] if sources else "",
          "evidence_type":"live structured web research","confidence":"Medium" if len(matched)>=2 else "Low"})

    combined=direct_issues+learned
    _local_risks=dg_core_risk_matches(make,model,fuel,gearbox)
    combined += _local_risks
    if _local_risks and not (direct_issues or learned):
        _dg_match_level="model_fuel"
    seen=set(); final=[]
    for row in combined:
        key=" ".join(str(row.get("issue","")).lower().split())
        if key and key not in seen:
            seen.add(key); final.append(row)
    status="issues_found" if final else ("insufficient_evidence" if transport_ok else "research_unavailable")
    return {"status":status,"issues":final,"evidence_items":len(texts)+len(direct_issues),"vehicle":vehicle,
            "direct_source":direct.get("url","") if isinstance(direct,dict) else "", "match_level":_dg_match_level}

def _dg_domain(url):
    try:
        from urllib.parse import urlparse
        return urlparse(str(url)).netloc.lower().replace("www.","")
    except Exception:return ""

DG_MODEL_BUYING_INTEL=[
 {"makes":["Peugeot","Citroen","DS","Vauxhall"],"engine_terms":["1.0 puretech","1.2 puretech","eb2","1.2 petrol"],
  "years":(2012,2022),"issue":"Oil-bathed timing belt degradation / oil-pressure risk",
  "severity":"High","ask":"Has the wet timing belt been inspected or replaced? If yes, when, at what mileage, and is there an invoice?",
  "check":"Verify service history and correct oil specification; inspect belt condition and ask about low-oil-pressure warnings.",
  "cost_low":499,"cost_high":1500,"source":"Manufacturer / Stellantis PureTech support"},
]
def dg_buying_intelligence(make,model,year,engine,fuel,description=""):
    hay=" ".join(map(str,[make,model,engine,fuel,description])).lower()
    out=[]
    for x in DG_MODEL_BUYING_INTEL:
        if make and str(make).lower() not in [m.lower() for m in x["makes"]]: continue
        y0,y1=x.get("years",(0,9999))
        try:
            if year and not (y0<=int(year)<=y1): continue
        except: pass
        terms=x.get("engine_terms",[])
        # Require powertrain evidence. Don't apply a PureTech warning to every Peugeot.
        if terms and not any(t in hay for t in terms): continue
        out.append(x)
    return out

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

st.markdown('<style>\n.dg-section{margin:1.1rem 0 .45rem;font-size:1.22rem;font-weight:800;color:#0f1b33}\n.dg-sub{color:#667085;font-size:.88rem;margin:-.15rem 0 .75rem}\n.dg-intel-card{border:1px solid #e4e7ec;border-left:6px solid #98a2b3;border-radius:14px;padding:15px 16px;margin:10px 0;background:#fff;box-shadow:0 1px 2px rgba(16,24,40,.04)}\n.dg-intel-card.high{border-left-color:#d92d20;background:#fff7f6}.dg-intel-card.medium{border-left-color:#f79009;background:#fffcf5}.dg-intel-card.low{border-left-color:#12b76a;background:#f6fef9}\n.dg-pill{display:inline-block;border-radius:999px;padding:3px 9px;font-size:.75rem;font-weight:800;margin-right:8px}\n.dg-pill.high{background:#fee4e2;color:#b42318}.dg-pill.medium{background:#fef0c7;color:#b54708}.dg-pill.low{background:#d1fadf;color:#027a48}\n.dg-issue{font-weight:800;color:#101828;line-height:1.3}.dg-row{margin:.5rem 0;color:#344054;line-height:1.5}.dg-row b{color:#101828}\n.dg-cost{margin-top:.7rem;padding-top:.65rem;border-top:1px solid #eaecf0;font-weight:800;color:#101828}.dg-status{border-radius:12px;padding:11px 13px;background:#f2f4f7;color:#344054;margin:.4rem 0 .8rem;font-size:.9rem}\n</style>', unsafe_allow_html=True)
st.caption("DG Deal Finder • V103 intelligence quality control")
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
    with urllib.request.urlopen(req,timeout=4) as r:
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
        with urlopen(req,timeout=4) as r:
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



@st.cache_data(ttl=86400,show_spinner=False)
def dg_official_uk_vehicle_rows():
    """Latest DfT/DVLA first-registration catalogue: detailed model, fuel, engine band and registration-year columns."""
    url="https://assets.publishing.service.gov.uk/media/69ef3ecf9ca985145673b9ec/df_VEH0270.csv"
    try:
        req=Request(url,headers={"User-Agent":"DG-Deal-Finder/1.0","Accept":"text/csv"})
        with urlopen(req,timeout=18) as resp:
            text=resp.read().decode("utf-8-sig","replace")
        return list(csv.DictReader(io.StringIO(text)))
    except Exception:
        return []

def dg_official_vehicle_choices(make,model,year):
    """Return only evidenced UK choices; never invent an engine or derivative."""
    rows=dg_official_uk_vehicle_rows()
    if not rows or not make or not model: return [],[],[]
    nm=_dg_norm(make); nd=_dg_norm(model)
    hits=[]
    for r in rows:
        mk=_dg_norm(r.get("Make","")); gm=_dg_norm(r.get("GenModel","")); detail=str(r.get("Model","") or "").strip()
        if mk!=nm: continue
        # Match the selected generic model to DfT generic model, allowing make prefix.
        gm2=gm
        if gm2.startswith(nm+" "): gm2=gm2[len(nm)+1:]
        if gm2!=nd and nd not in gm2: continue
        # VEH0270 year columns are counts of first registrations. Require evidence in target year where available.
        if year:
            y=str(int(year))
            ycols=[k for k in r if y in str(k)]
            if ycols:
                def active(v):
                    t=str(v or "").strip().lower().replace(",","")
                    if t in ("","0","[x]","[z]"): return False
                    if t=="[c]": return True
                    try:return float(t)>0
                    except:return False
                if not any(active(r.get(k)) for k in ycols): continue
        hits.append(r)
    fuels=[]; engines=[]; specs=[]
    for r in hits:
        f=str(r.get("Fuel","") or "").strip()
        e=str(r.get("EngineSizeDesc","") or "").strip()
        d=str(r.get("Model","") or "").strip()
        if f and f not in fuels: fuels.append(f)
        if e and e not in engines: engines.append(e)
        if d and d not in specs: specs.append(d)
    return engines,fuels,specs

def dg_catalogue_coverage(make,model):
    """Describe bundled-bank completeness so thin placeholder rows never masquerade as verified data."""
    try:
        p=Path(__file__).with_name("dg_vehicle_bank.csv")
        if not p.exists(): return {"rows":0,"year":False,"fuel":False,"engine":False,"gearbox":False,"spec":False,"thin":True}
        with p.open("r",encoding="utf-8-sig",newline="") as f:
            rr=[r for r in csv.DictReader(f) if _dg_norm(r.get("make",""))==_dg_norm(make) and _dg_norm(r.get("model",""))==_dg_norm(model)]
        has=lambda k:any(str(r.get(k,"") or "").strip() for r in rr)
        return {"rows":len(rr),"year":has("year"),"fuel":has("fuel"),"engine":has("engine"),
                "gearbox":has("gearbox"),"spec":has("spec"),
                "thin":not (has("fuel") and has("engine") and has("spec"))}
    except Exception:
        return {"rows":0,"year":False,"fuel":False,"engine":False,"gearbox":False,"spec":False,"thin":True}

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
def autoza_comparables(make, model, year, limit=100):
    """Live-stock retrieval: strict first, then widen only if the market is thin."""
    wanted=max(1,min(int(limit or 100),150))
    queries=[
        {"make":str(make).strip(),"model":str(model).strip(),"min_year":max(1990,int(year)-1),"max_year":int(year)+1},
        {"make":str(make).strip(),"model":str(model).strip(),"min_year":max(1990,int(year)-2),"max_year":int(year)+2},
        {"make":str(make).strip(),"model":str(model).strip(),"min_year":max(1990,int(year)-4),"max_year":int(year)+4},
        {"make":str(make).strip(),"model":str(model).strip()},
    ]
    rows=[]; seen=set()
    for base_params in queries:
        for page in range(1,4):
            params=dict(base_params); params.update({"page":page,"limit":50})
            url="https://autoza.co.uk/api/v1/vehicles?"+urlencode(params)
            try:
                req=Request(url,headers={"Accept":"application/json","User-Agent":"DG-Deal-Finder/1.0"})
                with urlopen(req,timeout=20) as response:
                    payload=json.loads(response.read().decode("utf-8"))
            except Exception:
                break
            batch=[]
            if isinstance(payload,list): batch=payload
            elif isinstance(payload,dict):
                for key in ("vehicles","results","data","items"):
                    value=payload.get(key)
                    if isinstance(value,list):
                        batch=value; break
                    if isinstance(value,dict):
                        for sub in ("vehicles","results","items","data"):
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
            meta=payload.get("meta",{}) if isinstance(payload,dict) else {}
            if meta.get("has_more") is False or len(batch)<50: break
        if len(rows)>=8: break
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



def _dg_market_stats_values(payload, make="", model=""):
    """Extract a usable asking-price guide from Autoza public market-stats JSON."""
    candidates=[]
    def walk(x):
        if isinstance(x,dict):
            candidates.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(payload)
    make_l=str(make or "").strip().lower(); model_l=str(model or "").strip().lower()
    scored=[]
    for d in candidates:
        blob=" ".join(str(d.get(k,"")) for k in ("make","manufacturer","model","name","label")).lower()
        score=(2 if make_l and make_l in blob else 0)+(3 if model_l and model_l in blob else 0)
        vals={}
        for out,keys in {
            "typical":("typical","median","average","avg","averagePrice","avgPrice","medianPrice"),
            "low":("lowest","low","min","minPrice","lowestPrice"),
            "high":("highest","high","max","maxPrice","highestPrice"),
            "count":("count","total","sampleSize","sample_size","vehicles","listings")
        }.items():
            for k in keys:
                try:
                    v=d.get(k)
                    if v not in (None,""):
                        vals[out]=float(str(v).replace("£","").replace(",",""))
                        break
                except Exception: pass
        if vals.get("typical",0)>250:
            scored.append((score,vals))
    if not scored: return {}
    scored.sort(key=lambda z:z[0],reverse=True)
    return scored[0][1]


def _mcp_payloads(raw):
    out=[]
    try: out.append(json.loads(raw))
    except Exception:
        for line in str(raw or "").splitlines():
            if line.startswith("data:"):
                try: out.append(json.loads(line[5:].strip()))
                except Exception: pass
    return out

def _autoza_mcp_post(body):
    req=Request("https://autoza.co.uk/api/mcp",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream",
                 "User-Agent":"DG-Deal-Finder/1.0"},method="POST")
    with urlopen(req,timeout=20) as resp:
        raw=resp.read().decode("utf-8","ignore")
    return _mcp_payloads(raw)

@st.cache_data(ttl=3600, show_spinner=False)
def autoza_mcp_tools():
    try:
        for payload in _autoza_mcp_post({"jsonrpc":"2.0","id":1,"method":"tools/list"}):
            tools=(payload.get("result",{}) or {}).get("tools") or []
            if tools: return tools
    except Exception: pass
    return []

def autoza_price_guide(make="", model=""):
    tools=autoza_mcp_tools()
    tool=next((x for x in tools if isinstance(x,dict) and x.get("name")=="get_uk_price_guide"),None)
    if not tool: return {}
    schema=tool.get("inputSchema") or tool.get("input_schema") or {}
    props=schema.get("properties") or {}; required=schema.get("required") or []
    args={}
    for key in props:
        lk=key.lower()
        if lk in ("make","manufacturer") and make: args[key]=str(make).strip()
        elif lk in ("model","vehicle_model") and model: args[key]=str(model).strip()
        elif lk in ("query","vehicle","search") and (make or model):
            args[key]=" ".join(x for x in (str(make).strip(),str(model).strip()) if x)
    if any(k not in args for k in required): return {}
    try:
        payloads=_autoza_mcp_post({"jsonrpc":"2.0","id":2,"method":"tools/call",
          "params":{"name":"get_uk_price_guide","arguments":args}})
    except Exception: return {}
    def parse_any(x):
        vals=_dg_market_stats_values(x,make,model) if isinstance(x,(dict,list)) else {}
        if vals.get("typical",0)>250: return vals
        blob=json.dumps(x,ensure_ascii=False) if not isinstance(x,str) else x
        try:
            vals=_dg_market_stats_values(json.loads(blob),make,model)
            if vals.get("typical",0)>250: return vals
        except Exception: pass
        def labelled(labels):
            for label in labels:
                for pat in (rf'{label}\s*(?:asking\s*price|price)?\s*[:=\-–—]?\s*£?\s*([\d,]+(?:\.\d+)?)',
                            rf'{label}[^£\d]{{0,80}}£\s*([\d,]+(?:\.\d+)?)'):
                    m=re.search(pat,blob,re.I)
                    if m:
                        try: return float(m.group(1).replace(",",""))
                        except Exception: pass
            return 0
        typical=labelled(["typical","median","average","avg"])
        low=labelled(["lowest","low","minimum","min"]); high=labelled(["highest","high","maximum","max"])
        if typical>250: return {"typical":typical,"low":low,"high":high,"count":0}
        gbp=[]
        for m in re.finditer(r'£\s*([\d,]+(?:\.\d+)?)',blob):
            try:
                v=float(m.group(1).replace(",",""))
                if 500<=v<=250000: gbp.append(v)
            except Exception: pass
        uniq=[]
        for v in gbp:
            if v not in uniq: uniq.append(v)
        if len(uniq)==3:
            ordered=sorted(uniq); return {"typical":ordered[1],"low":ordered[0],"high":ordered[2],"count":0}
        return {}
    for payload in payloads:
        if not isinstance(payload,dict): continue
        result=payload.get("result") or {}
        for candidate in (result.get("structuredContent"),result.get("structured_content"),result.get("data"),result):
            if candidate:
                vals=parse_any(candidate)
                if vals.get("typical",0)>250: vals["source"]="Autoza UK model price guide"; return vals
        for item in result.get("content") or []:
            if isinstance(item,dict):
                vals=parse_any(item.get("text") or item)
                if vals.get("typical",0)>250: vals["source"]="Autoza UK model price guide"; return vals
    return {}

def autoza_market_stats(make="", model=""):
    """Current public endpoint exposes broad make averages; keep only as low-confidence rescue."""
    url="https://autoza.co.uk/api/public/market-stats"
    try:
        req=Request(url,headers={"Accept":"application/json","User-Agent":"DG-Deal-Finder/1.0"})
        with urlopen(req,timeout=4) as resp:
            payload=json.loads(resp.read().decode("utf-8"))
        wanted=str(make or "").strip().lower()
        for row in (payload.get("pricesByMake") or []):
            if str(row.get("make","")).strip().lower()==wanted:
                price=float(row.get("averagePrice") or 0)
                if price>250:
                    return {"typical":price,"low":0,"high":0,"count":0,"source_url":url,"broad_make_only":True}
    except Exception:
        pass
    return {}

def _comp_num(row,*keys):
    for k in keys:
        try:
            v=row.get(k)
            if v not in (None,""): return float(str(v).replace("£","").replace(",",""))
        except Exception: pass
    return None

def dg_multi_signal_valuation(rows, target_year, target_mileage):
    """DG asking-price triangulation: median, mileage regression, market position."""
    clean=[]
    for r in (rows or []):
        if not isinstance(r,dict): continue
        price=_comp_num(r,"price","askingPrice","asking_price")
        year=_comp_num(r,"year","registrationYear","registration_year")
        miles=_comp_num(r,"mileage","miles","odometer")
        if not price or price<=250 or not year or abs(int(year)-int(target_year))>1: continue
        clean.append({"price":float(price),"year":int(year),"mileage":float(miles) if miles is not None else None})
    if not clean: return {}
    used=clean
    prices=sorted(x["price"] for x in clean)
    if len(clean)>=8:
        mid=len(prices)//2
        q1=statistics.median(prices[:mid]); q3=statistics.median(prices[(len(prices)+1)//2:])
        iqr=max(q3-q1,1); lo=q1-1.5*iqr; hi=q3+1.5*iqr
        trimmed=[x for x in clean if lo<=x["price"]<=hi]
        if len(trimmed)>=5: used=trimmed
    prices=sorted(x["price"] for x in used)
    med=float(statistics.median(prices))
    reg=[x for x in used if x["mileage"] is not None]
    mileage_est=None; slope=None
    if len(reg)>=5 and len({x["mileage"] for x in reg})>=3:
        xs=[x["mileage"] for x in reg]; ys=[x["price"] for x in reg]
        xm=sum(xs)/len(xs); ym=sum(ys)/len(ys); den=sum((x-xm)**2 for x in xs)
        if den>0:
            slope=max(min(sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/den,0.0),-0.20)
            mileage_est=ym+slope*(float(target_mileage)-xm)
            mileage_est=max(min(mileage_est,max(prices)*1.12),min(prices)*0.88)
    if reg:
        ranked=sorted(reg,key=lambda x:abs(x["mileage"]-float(target_mileage)))
        near=ranked[:max(3,min(len(ranked),math.ceil(len(ranked)/2)))]
        position=float(statistics.median([x["price"] for x in near]))
    else:
        position=med
    signals=[med,position]+([float(mileage_est)] if mileage_est is not None else [])
    combined=float(statistics.median(signals))
    low=float(prices[max(0,int((len(prices)-1)*0.20))])
    high=float(prices[min(len(prices)-1,int((len(prices)-1)*0.80))])
    spread=(high-low)/combined if combined else 1
    n=len(used)
    confidence="High" if n>=10 and spread<=0.30 and mileage_est is not None else ("Medium" if n>=5 else "Low")
    return {"value":combined,"median":med,"mileage_estimate":mileage_est,
            "market_position":position,"low":low,"high":high,"count":n,
            "mileage_slope":slope,"confidence":confidence,
            "evidence":"DG multi-signal valuation (median + mileage + market position)"}


def dg_progressive_valuation(rows, target_year, target_mileage):
    """Try strict ±1-year evidence first, then progressively broaden only when needed."""
    rows=rows or []
    # Level A: target year ±1 (preferred)
    strict=dg_multi_signal_valuation(rows,target_year,target_mileage)
    if strict.get("value",0)>0:
        strict["level"]="A"
        strict["evidence"]="Primary comparables: target year ±1"
        return strict

    # Level B: target year ±2. This is rescue evidence, clearly labelled.
    within2=[]
    for r in rows:
        try:
            ry=int(r.get("year") or r.get("registrationYear") or r.get("registration_year") or 0)
        except Exception:
            ry=0
        if ry and abs(ry-int(target_year))<=2:
            rr=dict(r); rr["year"]=int(target_year)  # pass cohort into signal engine after explicit filtering
            within2.append(rr)
    b=dg_multi_signal_valuation(within2,target_year,target_mileage)
    if b.get("value",0)>0:
        b["level"]="B"; b["confidence"]="Medium" if b.get("confidence")=="High" else b.get("confidence","Low")
        b["evidence"]="Rescue comparables: target year ±2"
        return b

    # Level C: broader same-model rows already supplied by Autoza cohort logic.
    # Cap to ±4 years so an old/new generation cannot dominate.
    within4=[]
    for r in rows:
        try:
            ry=int(r.get("year") or r.get("registrationYear") or r.get("registration_year") or 0)
        except Exception:
            ry=0
        if ry and abs(ry-int(target_year))<=4:
            rr=dict(r); rr["year"]=int(target_year)
            within4.append(rr)
    c=dg_multi_signal_valuation(within4,target_year,target_mileage)
    if c.get("value",0)>0:
        c["level"]="C"; c["confidence"]="Low"
        c["evidence"]="Broad rescue comparables: same-model evidence within ±4 years"
        return c
    return {}



DG_FULL_UK_BANK_PATH=Path(__file__).with_name("dg_full_uk_vehicle_bank.csv")

DG_ENGINE_BANK_PATH=Path(__file__).with_name("dg_engine_bank.csv")
DG_ENGINE_BANK_URL="https://raw.githubusercontent.com/gor3a/vehicle-makes-models/main/data/csv/engines.csv"

def dg_build_engine_bank(force=False):
    """Build supplementary generation/engine bank from the open ODbL vehicle-makes-models dataset."""
    if DG_ENGINE_BANK_PATH.exists() and not force:
        try:
            d=pd.read_csv(DG_ENGINE_BANK_PATH,low_memory=False)
            if len(d)>10000: return d
        except Exception: pass
    raw=_dg_http_csv(DG_ENGINE_BANK_URL)
    wanted=[
        "make","model","generation","gen_year_start","gen_year_end","body_type",
        "engine_label","fuel_type","cylinders","displacement_cc","power_hp","torque_nm",
        "transmission","drivetrain","zero_to_100_s","top_speed_kmh",
        "fuel_economy_combined_l100","curb_weight_kg"
    ]
    keep=[c for c in wanted if c in raw.columns]
    d=raw[keep].copy()
    for c in wanted:
        if c not in d.columns: d[c]=""
    d["make"]=d["make"].astype(str).str.strip()
    d["model"]=d["model"].astype(str).str.strip()
    d["generation"]=d["generation"].astype(str).str.strip()
    d["engine_label"]=d["engine_label"].astype(str).str.strip()
    d=d[(d["make"]!="")&(d["model"]!="")&(d["engine_label"]!="")]
    d["source"]="vehicle-makes-models / ODbL 1.0"
    d=d[wanted+["source"]].drop_duplicates()
    d.to_csv(DG_ENGINE_BANK_PATH,index=False)
    return d

@st.cache_data(show_spinner=False)
def dg_engine_bank_lookup(make="",model="",year=0):
    if not DG_ENGINE_BANK_PATH.exists(): return pd.DataFrame()
    try:
        d=pd.read_csv(DG_ENGINE_BANK_PATH,low_memory=False)
        if make: d=d[d["make"].astype(str).str.casefold()==str(make).casefold()]
        if model: d=d[d["model"].astype(str).str.casefold()==str(model).casefold()]
        if year:
            ys=pd.to_numeric(d["gen_year_start"],errors="coerce")
            ye=pd.to_numeric(d["gen_year_end"],errors="coerce").fillna(9999)
            d=d[(ys<=int(year))&(ye>=int(year))]
        return d.head(5000)
    except Exception:
        return pd.DataFrame()

def dg_engine_options(make,model,year):
    """Return sourced engine/spec options for the selected make/model/year."""
    d=dg_engine_bank_lookup(make,model,year)
    if d.empty: return []
    out=[]
    for _,r in d.iterrows():
        out.append({
            "generation":str(r.get("generation","") or ""),
            "engine":str(r.get("engine_label","") or ""),
            "fuel":str(r.get("fuel_type","") or ""),
            "cc":r.get("displacement_cc",""),
            "cylinders":r.get("cylinders",""),
            "bhp":r.get("power_hp",""),
            "torque_nm":r.get("torque_nm",""),
            "gearbox":str(r.get("transmission","") or ""),
            "drivetrain":str(r.get("drivetrain","") or ""),
            "source":"vehicle-makes-models / ODbL 1.0",
        })
    return out


DG_DFT_SOURCES={
    "age_am":"https://assets.publishing.service.gov.uk/media/69ef3c3a20a498c16734afd1/df_VEH0124_AM.csv",
    "age_nz":"https://assets.publishing.service.gov.uk/media/69ef3c8520a498c16734afd2/df_VEH0124_NZ.csv",
    "engine":"https://assets.publishing.service.gov.uk/media/69ef3ea808ecdb5c6f34afad/df_VEH0220.csv",
}

def _dg_http_csv(url):
    req=Request(url,headers={"User-Agent":"DG-Deal-Finder/62","Accept":"text/csv,*/*"})
    with urlopen(req,timeout=60) as r:
        return pd.read_csv(io.BytesIO(r.read()),low_memory=False)

def dg_build_full_uk_vehicle_bank(force=False):
    if DG_FULL_UK_BANK_PATH.exists() and not force:
        try:
            cached=pd.read_csv(DG_FULL_UK_BANK_PATH,low_memory=False)
            if len(cached)>10000: return cached
        except Exception: pass
    age_parts=[]
    for key in ("age_am","age_nz"):
        d=_dg_http_csv(DG_DFT_SOURCES[key])
        keep=[c for c in ["BodyType","Make","GenModel","Model","YearFirstUsed","YearManufacture","LicenceStatus"] if c in d.columns]
        d=d[keep]
        if "BodyType" in d: d=d[d["BodyType"].astype(str).str.lower().eq("cars")]
        if "LicenceStatus" in d: d=d[d["LicenceStatus"].astype(str).str.lower().eq("licensed")]
        age_parts.append(d)
    age=pd.concat(age_parts,ignore_index=True).drop_duplicates()
    eng=_dg_http_csv(DG_DFT_SOURCES["engine"])
    keep=[c for c in ["BodyType","Make","GenModel","Model","Fuel","EngineSizeSimple","EngineSizeDesc","LicenceStatus"] if c in eng.columns]
    eng=eng[keep]
    if "BodyType" in eng: eng=eng[eng["BodyType"].astype(str).str.lower().eq("cars")]
    if "LicenceStatus" in eng: eng=eng[eng["LicenceStatus"].astype(str).str.lower().eq("licensed")]
    eng=eng.drop_duplicates()
    join=[c for c in ["Make","GenModel","Model"] if c in age.columns and c in eng.columns]
    full=age.merge(eng.drop(columns=[c for c in ["BodyType","LicenceStatus"] if c in eng.columns]),on=join,how="left")
    full["year"]=pd.to_numeric(full.get("YearFirstUsed"),errors="coerce")
    full["year"]=full["year"].fillna(pd.to_numeric(full.get("YearManufacture"),errors="coerce"))
    full=full[(full["year"]>=1970)&(full["year"]<=datetime.datetime.now().year+1)]
    full["year"]=full["year"].astype(int)
    full["make"]=full["Make"].astype(str).str.strip().str.title()
    full["model"]=full["GenModel"].astype(str).str.strip()
    full["spec"]=full["Model"].astype(str).str.strip()
    full["fuel"]=full["Fuel"].astype(str).str.strip() if "Fuel" in full else ""
    full["engine_cc"]=pd.to_numeric(full["EngineSizeSimple"],errors="coerce") if "EngineSizeSimple" in full else None
    full["engine_band"]=full["EngineSizeDesc"].astype(str).str.strip() if "EngineSizeDesc" in full else ""
    full["source"]="DfT/DVLA vehicle licensing statistics"
    out=full[["make","model","year","spec","fuel","engine_cc","engine_band","source"]].drop_duplicates()
    out.to_csv(DG_FULL_UK_BANK_PATH,index=False)
    return out

def dg_vehicle_bank_status():
    result={"seed_rows":0,"official_rows":0,"makes":0}
    try:
        d=pd.read_csv(DG_VEHICLE_BANK_PATH,low_memory=False)
        result["seed_rows"]=len(d); result["makes"]=d["make"].nunique()
    except Exception: pass
    try:
        d=pd.read_csv(DG_FULL_UK_BANK_PATH,low_memory=False)
        result["official_rows"]=len(d); result["makes"]=max(result["makes"],d["make"].nunique())
    except Exception: pass
    return result

@st.cache_data(show_spinner=False)
def dg_official_bank_lookup(make="",model="",year=0):
    if not DG_FULL_UK_BANK_PATH.exists(): return pd.DataFrame()
    try:
        d=pd.read_csv(DG_FULL_UK_BANK_PATH,low_memory=False)
        if make: d=d[d["make"].astype(str).str.casefold()==str(make).casefold()]
        if model: d=d[d["model"].astype(str).str.casefold()==str(model).casefold()]
        if year: d=d[pd.to_numeric(d["year"],errors="coerce")==int(year)]
        return d.head(5000)
    except Exception: return pd.DataFrame()

DG_VEHICLE_BANK_PATH=Path(__file__).with_name("dg_vehicle_bank.csv")
DG_MARKET_BANK_PATH=Path(__file__).with_name("dg_market_bank.csv")

def _dg_norm(x):
    return re.sub(r"[^a-z0-9]+"," ",str(x or "").lower()).strip()

def dg_store_market_observations(rows,make="",model=""):
    """Persistent DG Market Bank: retain genuine asking-price observations and their history."""
    if not rows: return 0
    path=DG_MARKET_BANK_PATH
    cols=["observation_id","make","model","title","year","mileage","price","fuel","gearbox",
          "source","source_id","first_seen","last_seen","times_seen","previous_price",
          "price_change","status"]
    today=datetime.date.today().isoformat()
    existing={}
    if path.exists():
        try:
            with path.open("r",encoding="utf-8-sig",newline="") as f:
                for r in csv.DictReader(f):
                    oid=r.get("observation_id") or r.get("source_id") or ""
                    if oid: existing[oid]=r
        except Exception: pass
    changed=0
    for r in rows:
        if not isinstance(r,dict): continue
        price=float(_num(r,"price","asking_price") or 0)
        year=int(_num(r,"year") or 0); mileage=int(_num(r,"mileage","miles") or 0)
        if price<500 or year<1970: continue
        src=str(r.get("source") or "market")
        sid=str(r.get("source_id") or r.get("id") or "").strip()
        title=str(r.get("title") or "").strip()
        oid=sid or f"{_dg_norm(make)}|{_dg_norm(model)}|{year}|{mileage}|{int(price)}|{_dg_norm(title)[:60]}"
        oldr=existing.get(oid,{})
        oldprice=float(_num(oldr,"price") or 0)
        first=oldr.get("first_seen") or today
        times=int(float(oldr.get("times_seen") or 0))+1
        rec={"observation_id":oid,"make":str(r.get("make") or make),"model":str(r.get("model") or model),
             "title":title,"year":year,"mileage":mileage,"price":price,
             "fuel":str(r.get("fuel") or ""),"gearbox":str(r.get("gearbox") or ""),
             "source":src,"source_id":sid,"first_seen":first,"last_seen":today,"times_seen":times,
             "previous_price":oldprice if oldprice and oldprice!=price else oldr.get("previous_price",""),
             "price_change":(price-oldprice) if oldprice and oldprice!=price else 0,
             "status":"active"}
        existing[oid]=rec; changed+=1
    try:
        with path.open("w",encoding="utf-8",newline="") as f:
            wr=csv.DictWriter(f,fieldnames=cols); wr.writeheader()
            for r in existing.values(): wr.writerow({k:r.get(k,"") for k in cols})
    except Exception:
        return 0
    return changed

def dg_market_bank_summary(make="",model="",days=180):
    """Historical observed-advert summary. 'Left market' is never represented as a sold price."""
    if not DG_MARKET_BANK_PATH.exists(): return {}
    cutoff=datetime.date.today()-datetime.timedelta(days=int(days))
    rows=[]
    try:
        with DG_MARKET_BANK_PATH.open("r",encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f):
                if make and _dg_norm(r.get("make",""))!=_dg_norm(make): continue
                if model and _dg_norm(r.get("model",""))!=_dg_norm(model): continue
                try:
                    d=datetime.date.fromisoformat(r.get("last_seen",""))
                    if d<cutoff: continue
                except Exception: pass
                p=float(_num(r,"price") or 0)
                if p>0: rows.append(r)
    except Exception: return {}
    if not rows: return {}
    prices=sorted(float(_num(r,"price") or 0) for r in rows if _num(r,"price"))
    changes=[float(_num(r,"price_change") or 0) for r in rows if float(_num(r,"price_change") or 0)!=0]
    return {"count":len(rows),"median_price":statistics.median(prices) if prices else 0,
            "low":prices[max(0,int(len(prices)*.2)-1)] if prices else 0,
            "high":prices[min(len(prices)-1,int(len(prices)*.8))] if prices else 0,
            "price_changes":len(changes),
            "median_price_change":statistics.median(changes) if changes else 0,
            "days":int(days)}


def dg_bank_valuation(make, model, year, mileage):
    """Value from DG's remembered genuine asking-price observations."""
    if not DG_MARKET_BANK_PATH.exists(): return {}
    try: df=pd.read_csv(DG_MARKET_BANK_PATH)
    except Exception: return {}
    if df.empty: return {}
    mk=_dg_norm(make); md=_dg_norm(model)
    d=df[(df["make"].map(_dg_norm)==mk) & (df["model"].map(_dg_norm)==md)].copy()
    if d.empty: return {}
    d["year"]=pd.to_numeric(d["year"],errors="coerce")
    d["mileage"]=pd.to_numeric(d["mileage"],errors="coerce").fillna(0)
    d["price"]=pd.to_numeric(d["price"],errors="coerce")
    d=d[(d["price"]>=500)&(d["price"]<=250000)]
    # Prefer ±1 year; widen only if the bank has too little evidence.
    exact=d[(d["year"]-int(year)).abs()<=1]
    cohort=exact if len(exact)>=3 else d[(d["year"]-int(year)).abs()<=3]
    if cohort.empty: return {}
    cohort=cohort.assign(_dist=(cohort["year"]-int(year)).abs()*12000+(cohort["mileage"]-float(mileage or 0)).abs())
    cohort=cohort.sort_values("_dist").head(12)
    prices=cohort["price"].dropna().tolist()
    if not prices: return {}
    med=float(statistics.median(prices))
    ps=sorted(prices)
    lo=float(ps[max(0,int((len(ps)-1)*.2))]); hi=float(ps[min(len(ps)-1,int((len(ps)-1)*.8))])
    return {"value":med,"retail":med,"low":lo,"high":hi,"count":len(prices),
            "confidence":"High" if len(prices)>=8 else ("Medium" if len(prices)>=4 else "Low"),
            "evidence":"DG Market Bank — remembered genuine asking prices","manual_required":False}

def autoza_mcp_comparables(make,model,year,limit=100):
    tools=autoza_mcp_tools()
    tool=next((x for x in tools if isinstance(x,dict) and x.get("name")=="search_used_cars"),None)
    if not tool: return []
    schema=tool.get("inputSchema") or tool.get("input_schema") or {}
    props=schema.get("properties") or {}; required=schema.get("required") or []
    args={}
    for key in props:
        lk=key.lower()
        if lk in ("make","manufacturer") and make: args[key]=str(make).strip()
        elif lk in ("model","vehicle_model") and model: args[key]=str(model).strip()
        elif lk in ("year","registration_year") and year: args[key]=int(year)
        elif lk in ("min_year","year_from") and year: args[key]=max(1990,int(year)-2)
        elif lk in ("max_year","year_to") and year: args[key]=int(year)+2
        elif lk in ("limit","page_size","per_page"): args[key]=min(int(limit or 100),100)
        elif lk in ("query","search") and (make or model):
            args[key]=" ".join(x for x in (str(make).strip(),str(model).strip()) if x)
    if any(k not in args for k in required): return []
    try:
        payloads=_autoza_mcp_post({"jsonrpc":"2.0","id":3,"method":"tools/call",
            "params":{"name":"search_used_cars","arguments":args}})
    except Exception: return []
    rows=[]
    def walk(x):
        if isinstance(x,list):
            for v in x: walk(v)
        elif isinstance(x,dict):
            price=_num(x,"price","asking_price","askingPrice")
            if price and 500<=price<=250000 and any(k in x for k in ("make","model","year","mileage","title")): rows.append(x)
            else:
                for v in x.values(): walk(v)
        elif isinstance(x,str):
            try: walk(json.loads(x))
            except Exception: pass
    for payload in payloads:
        if not isinstance(payload,dict): continue
        result=payload.get("result") or {}
        walk(result.get("structuredContent") or result.get("structured_content") or result.get("data") or {})
        for item in result.get("content") or []:
            if isinstance(item,dict): walk(item.get("text") or item)
    return rows[:max(1,int(limit or 100))]

def autoza_public_market_comparables(make,model,limit=100):
    """Extract genuine Autoza listing cards; bind each price to its own year/mileage."""
    if not make or not model: return []
    mk=quote(str(make).strip().lower().replace(" ","-"))
    md=quote(str(model).strip().lower().replace(" ","-"))
    urls=[f"https://autoza.co.uk/cars/{mk}/model/{md}",f"https://autoza.co.uk/cars/{mk}"]
    rows=[]; seen=set(); target=_dg_norm(model)
    for url in urls:
        try:
            req=Request(url,headers={"User-Agent":"DG-Deal-Finder/68","Accept":"text/html,*/*"})
            with urlopen(req,timeout=20) as r: raw=r.read().decode("utf-8","ignore")
        except Exception: continue
        raw=unescape(re.sub(r'<[^>]+>',' ',raw))
        text=" ".join(raw.split())
        # Autoza visible listings use "... Compare <vehicle> <year><miles> miles <fuel> £<price> ..."
        starts=[m.start() for m in re.finditer(r'\bCompare\b',text,re.I)]
        cards=[]
        for i,st in enumerate(starts):
            en=starts[i+1] if i+1<len(starts) else min(len(text),st+900)
            cards.append(text[st:en])
        # JSON-LD / alternate markup fallback: small windows around each GBP price.
        if not cards:
            for pm in re.finditer(r'£\s*[\d,]{3,}',text):
                cards.append(text[max(0,pm.start()-300):min(len(text),pm.end()+180)])
        for c in cards:
            if target not in _dg_norm(c): continue
            pm=re.search(r'£\s*([\d,]{3,})',c)
            ym=re.search(r'\b((?:19|20)\d{2})\b',c)
            if not pm or not ym: continue
            try: price=float(pm.group(1).replace(",","")); year=int(ym.group(1))
            except Exception: continue
            if not (500<=price<=250000 and 1970<=year<=datetime.datetime.now().year+1): continue
            mm=re.search(r'([\d,]{1,7})\s*miles\b',c,re.I)
            mileage=float(mm.group(1).replace(",","")) if mm else 0
            fm=re.search(r'\b(Petrol|Diesel|Electric|Hybrid|Plug[- ]?in Hybrid|LPG)\b',c,re.I)
            gm=re.search(r'\b(Manual|Automatic|Auto|PDK|DSG|Tiptronic|CVT)\b',c,re.I)
            sid=f"{year}|{int(mileage)}|{int(price)}"
            if sid in seen: continue
            seen.add(sid)
            rows.append({"make":make,"model":model,"year":year,"mileage":mileage,"price":price,
                         "fuel":fm.group(1) if fm else "","gearbox":gm.group(1) if gm else "",
                         "title":c[:260],"source":"Autoza public market page","source_id":sid})
            if len(rows)>=limit: break
        if len(rows)>=limit: break
    return rows[:limit]

def autoza_public_model_guide(make,model):
    """Model-page headline asking-price guide; only used as low-confidence fallback."""
    if not make or not model: return {}
    mk=quote(str(make).strip().lower().replace(" ","-"))
    md=quote(str(model).strip().lower().replace(" ","-"))
    url=f"https://autoza.co.uk/cars/{mk}/model/{md}"
    try:
        req=Request(url,headers={"User-Agent":"DG-Deal-Finder/65","Accept":"text/html,*/*"})
        with urlopen(req,timeout=20) as r:
            raw=r.read().decode("utf-8","ignore")
        text=" ".join(unescape(re.sub(r'<[^>]+>',' ',raw)).split())
        m=re.search(r'Average price\s*£\s*([\d,]+)',text,re.I)
        lo=re.search(r'From\s*£\s*([\d,]+)',text,re.I)
        if m:
            typical=float(m.group(1).replace(",",""))
            return {"typical":typical,"low":float(lo.group(1).replace(",","")) if lo else 0,
                    "high":0,"count":0,"source":"Autoza public model page"}
    except Exception:
        pass
    return {}

def dg_sparse_age_relevant_value(rows,year,mileage,make="",model=""):
    """Use sparse real listings only when they are age-relevant; never price an old generation from a new one."""
    clean=[]
    ty=int(year or 0); tm=float(mileage or 0)
    for r in rows or []:
        if not isinstance(r,dict): continue
        ry=int(_num(r,"year") or 0); rp=float(_num(r,"price","asking_price") or 0); rm=float(_num(r,"mileage","miles") or 0)
        if not (1970<=ry<=datetime.datetime.now().year+1 and 500<=rp<=250000): continue
        gap=abs(ry-ty) if ty else 99
        if gap<=3:
            clean.append((gap,abs(rm-tm) if rm and tm else 999999,ry,rm,rp,r))
    if not clean: return {}
    clean.sort(key=lambda x:(x[0],x[1]))
    # Sparse mode intentionally uses only the nearest 5 real observations.
    chosen=clean[:5]
    prices=[x[4] for x in chosen]
    # With one observation, use its asking price as low-confidence market evidence, not a fabricated model.
    value=float(statistics.median(prices))
    lo=min(prices); hi=max(prices)
    return {"value":value,"retail":value,"low":lo,"high":hi,"count":len(chosen),
            "confidence":"Low" if len(chosen)<3 else "Medium",
            "evidence":"Sparse age-relevant UK asking-price evidence","manual_required":False,
            "comparables":[x[5] for x in chosen]}

def dg_collect_market(make,model,year,mileage=0):
    """One on-demand collection pass using permitted free sources already supported by DG."""
    rows=[]; source_counts={"REST":0,"MCP":0,"Public":0}
    try:
        rr=autoza_comparables(make,model,year) or []
        rows.extend(rr); source_counts["REST"]=len(rr)
    except Exception: pass
    try:
        rr=autoza_mcp_comparables(make,model,year,50) or []
        rows.extend(rr); source_counts["MCP"]=len(rr)
    except Exception: pass
    try:
        rr=autoza_public_market_comparables(make,model,100) or []
        rows.extend(rr); source_counts["Public"]=len(rr)
    except Exception: pass
    # de-dupe before storing
    clean=[]; seen=set()
    for r in rows:
        if not isinstance(r,dict): continue
        y=int(_num(r,"year") or 0); p=int(_num(r,"price","asking_price") or 0); mi=int(_num(r,"mileage","miles") or 0)
        if y<1970 or p<500: continue
        k=(str(r.get("source_id","")),y,mi,p)
        if k in seen: continue
        seen.add(k); clean.append(r)
    stored=dg_store_market_observations(clean,make,model)
    return {"rows":clean,"stored":stored,"sources":source_counts}

def dg_market_bank_stats():
    if not DG_MARKET_BANK_PATH.exists(): return {"rows":0,"models":0}
    try:
        with DG_MARKET_BANK_PATH.open("r",encoding="utf-8-sig",newline="") as f:
            rr=list(csv.DictReader(f))
        models={( _dg_norm(r.get("make","")), _dg_norm(r.get("model","")) ) for r in rr if r.get("make") and r.get("model")}
        return {"rows":len(rr),"models":len(models)}
    except Exception:
        return {"rows":0,"models":0}

def robust_market_value(rows,year,mileage,make="",model="",asking=0):
    live=list(rows or [])
    for fn,args in [
        (autoza_mcp_comparables,(make,model,year,50)),
        (autoza_public_market_comparables,(make,model,100)),
    ]:
        try:
            live.extend(fn(*args) or [])
        except Exception:
            pass

    # de-duplicate but do not discard valid sparse observations
    clean=[]; seen=set()
    for r in live:
        if not isinstance(r,dict): continue
        y=int(_num(r,"year") or 0); p=float(_num(r,"price","asking_price") or 0)
        mi=int(_num(r,"mileage","miles") or 0)
        if not (1970<=y<=datetime.datetime.now().year+1 and 500<=p<=250000): continue
        key=(str(r.get("source_id","")),y,mi,int(p))
        if key in seen: continue
        seen.add(key); clean.append(r)
    live=clean

    try: dg_store_market_observations(live,make,model)
    except Exception: pass

    try:
        est=estimate_market_from_comps(live,year,mileage) or {}
        val=float(est.get("retail") or est.get("value") or est.get("average") or 0)
        if val>0:
            return {"value":val,"retail":val,"low":float(est.get("low") or val),
                    "high":float(est.get("high") or val),"count":int(est.get("count") or len(live)),
                    "confidence":est.get("confidence","Medium"),
                    "evidence":est.get("evidence","Current UK asking-price comparables"),
                    "manual_required":False,"comparables":est.get("comparables",live[:10])}
    except Exception:
        pass

    # Critical rescue: genuine same-model observations within ±3 years.
    sparse=dg_sparse_age_relevant_value(live,year,mileage,make,model)
    if float(sparse.get("value",0) or 0)>0:
        return sparse

    try:
        bank=dg_bank_valuation(make,model,year,mileage) or {}
        if float(bank.get("value",0) or 0)>0: return bank
    except Exception: pass

    try:
        hist=dg_market_bank_summary(make,model,180) or {}
        if hist.get("count",0)>=3 and float(hist.get("median_price",0) or 0)>0:
            v=float(hist["median_price"])
            return {"value":v,"retail":v,"low":float(hist.get("low") or v),
                    "high":float(hist.get("high") or v),"count":int(hist["count"]),
                    "confidence":"Medium" if hist["count"]>=6 else "Low",
                    "evidence":"DG observed asking-price bank","manual_required":False,"comparables":[]}
    except Exception: pass

    try:
        guide=autoza_price_guide(make,model) or {}
        if float(guide.get("value",0) or 0)>0: return guide
    except Exception: pass

    return {"value":0,"retail":0,"low":0,"high":0,"count":0,"confidence":"No data",
            "evidence":"No usable market valuation","manual_required":True,"comparables":[]}

def manual_market_override(default=0):
    return st.number_input("Manual retail estimate (£)",min_value=0,max_value=250000,
                           value=int(default or 0),step=100,
                           help="Use only when free market sources cannot produce a defensible value.")

def estimate_market_from_comps(rows, year, mileage):

    # V52: valuation evidence is restricted to the target year ±1.
    # Missing/invalid listing years are excluded from market-derived valuation.
    _year_filtered=[]
    for _r in (rows or []):
        try:
            _ry=int(_r.get("year") or _r.get("registrationYear") or _r.get("registration_year") or 0)
        except Exception:
            _ry=0
        if _ry and abs(_ry-int(year)) <= 1:
            _year_filtered.append(_r)
    rows=_year_filtered
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
    with urllib.request.urlopen(req,timeout=4) as r:
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
with st.sidebar.expander("DG UK Vehicle Bank", expanded=False):
    _bs=dg_vehicle_bank_status()
    _engine_rows=0
    try:
        if DG_ENGINE_BANK_PATH.exists(): _engine_rows=len(pd.read_csv(DG_ENGINE_BANK_PATH,low_memory=False))
    except Exception: pass
    st.caption(f"Bundled: {_bs['seed_rows']:,} • Official UK: {_bs['official_rows']:,} • Engines: {_engine_rows:,}")
    if st.button("BUILD / REFRESH UK + ENGINE BANKS", key="dg_build_full_bank"):
        with st.spinner("Building UK vehicle and engine/spec banks…"):
            try:
                _b=dg_build_full_uk_vehicle_bank(force=True)
                st.success(f"UK Vehicle Bank ready: {len(_b):,} rows across {_b['make'].nunique():,} makes.")
            except Exception as _e:
                st.error("Official UK bank download could not complete. Bundled DG data remains available.")
                st.caption(str(_e)[:240])
            try:
                _eb=dg_build_engine_bank(force=True)
                st.success(f"Engine Bank ready: {len(_eb):,} engine variants across {_eb['make'].nunique():,} makes.")
            except Exception as _e:
                st.error("Engine Bank download could not complete. Existing curated engine rules remain available.")
                st.caption(str(_e)[:240])
            st.cache_data.clear()

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
    # V79: fill thin bundled records from current official DfT/DVLA UK registration data.
    _gov_engines,_gov_fuels,_gov_specs=dg_official_vehicle_choices(selected_make,selected_model,selected_year)
    engines=_merge_unique(_gov_engines,engines)
    fuels=_merge_unique(_gov_fuels,fuels)
    derivatives=_merge_unique(_gov_specs,derivatives)
    # V77 gap closer: common models must not dead-end just because the bundled
    # bank lacks an exact-year row. Fall back to all known rows for that model.
    if selected_make and selected_model:
        _all_engines,_all_fuels,_all_gearboxes,_all_specs=local_vehicle_choices(selected_make,selected_model,None)
        if not engines: engines=_merge_unique(engines,_all_engines)
        if not fuels: fuels=_merge_unique(fuels,_all_fuels)
        if not gearboxes: gearboxes=_merge_unique(gearboxes,_all_gearboxes)
        if not derivatives: derivatives=_merge_unique(derivatives,_all_specs)
        _dg_cov=dg_catalogue_coverage(selected_make,selected_model)
    else:
        _dg_cov={"thin":False}
    # Never block appraisal because taxonomy is incomplete. These are user choices,
    # not claims that every powertrain existed for the selected model/year.
    if selected_make and selected_model and not fuels:
        fuels=["Petrol","Diesel","Hybrid","Plug-in Hybrid","Electric"]
    if selected_make and selected_model and not gearboxes:
        gearboxes=["Manual","Automatic"]

    taxonomy_verified=bool(taxonomy)
    official_catalogue_loaded=not official_catalogue.empty
    if not official_catalogue_loaded:
        st.caption("Using DG bundled UK vehicle catalogue. Live catalogue enrichment is temporarily unavailable.")

    # Fuel first: this immediately removes petrol/diesel/hybrid/EV derivatives and engines
    # that cannot belong to the selected fuel type for the exact chosen year.
    if taxonomy_verified:
        _,_,_,tax_fuels,_=taxonomy_options(taxonomy)
        fuel_options=_merge_unique(tax_fuels,fuels)
    else:
        fuel_options=fuels
    fuel_index=1 if len(fuel_options)==1 else 0
    if selected_make and selected_model and _dg_cov.get("thin"):
        st.caption("DG has partial catalogue detail for this model. Appraisal remains available; exact spec/engine can be entered manually.")
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
    spec_options=filter_specs_to_official_year(candidate_specs,year_spec_evidence)
    spec_is_year_constrained=bool(year_spec_evidence)
    if official_catalogue_loaded and not year_spec_evidence:
        # The official catalogue loaded successfully but has no year row for this car:
        # don't leak broad model-level DG specs from other years into a supposedly safe selector.
        spec_options=_merge_unique(tax_specs if taxonomy_verified else [])
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
    engine_options=filter_engines_to_official_year(candidate_engines,year_engine_evidence)
    # Preserve verified historical labels (e.g. 2.7 Flat-6) rather than replacing
    # them with broad model-level fallback labels.
    if verified_dg_engines:
        engine_options=_merge_unique(verified_dg_engines)
    engine_is_year_constrained=bool(year_engine_evidence)
    if not year_engine_evidence:
        # Reliability first: broad model-level engines are not year evidence.
        # Only exact taxonomy may populate this dropdown; otherwise leave it empty.
        engine_options=_merge_unique(tax_engines if taxonomy_verified else [])
    if engine_is_year_constrained:
        st.caption(f"Engine list filtered to {selected_year} UK registrations — {len(engine_options)} valid choice(s).")
    elif selected_model:
        st.caption("Year-specific official engine evidence is limited. Catalogue choices remain available; verify unusual or imported vehicles manually.")

    selected_engine=st.selectbox("Engine / powertrain",["— Choose engine —"]+engine_options,
        disabled=not bool(selected_model))
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
        go=st.form_submit_button("ANALYSE DEAL  →",use_container_width=True)
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
                    # V51 free valuation rescue: never turn missing evidence into a £0 recommendation.
                    try:
                        _dg_existing_value=float(market_estimate.get("market",0) if isinstance(market_estimate,dict) else (market_estimate or 0))
                    except Exception:
                        _dg_existing_value=0.0
                    if _dg_existing_value <= 0:
                        _dg_rescue=robust_market_value(comps, selected_year, mileage, selected_make, selected_model, asking)
                        if _dg_rescue["value"] > 0:
                            market_estimate={"market":float(_dg_rescue["value"]),"retail":float(_dg_rescue["value"]),
                                             "value":float(_dg_rescue["value"]),"average":float(_dg_rescue["value"]),
                                             "low":float(_dg_rescue.get("low") or _dg_rescue["value"]),
                                             "high":float(_dg_rescue.get("high") or _dg_rescue["value"]),
                                             "count":int(_dg_rescue.get("count") or 1),
                                             "confidence":_dg_rescue.get("confidence","Low"),
                                             "evidence":_dg_rescue.get("evidence","Current UK asking-price comparables")}
                            market_retail=float(_dg_rescue["value"])
                            st.session_state["market_retail"]=market_retail
                            st.session_state["market_estimate"]=market_estimate
                            st.info(f'Market rescue used: {_dg_rescue["evidence"]} · confidence {_dg_rescue["confidence"]}')
                        else:
                            st.warning("FREE MARKET DATA INSUFFICIENT — enter your own realistic retail estimate below. DG will still calculate the deal.")
                            _manual_retail=manual_market_override(int(asking or 0))
                            if _manual_retail > 0:
                                market_estimate={"market":float(_manual_retail),"low":float(_manual_retail),"high":float(_manual_retail),"count":0}
                                st.caption("Manual retail estimate — not presented as market-derived evidence.")

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

        # V76 canonical valuation handoff: every successful valuation source must
        # feed the SAME retail value into all commercial calculations.
        try:
            _dg_canonical_retail=float(
                market_retail
                or (market_estimate or {}).get("retail",0)
                or (market_estimate or {}).get("market",0)
                or (market_estimate or {}).get("value",0)
                or (market_estimate or {}).get("average",0)
                or 0
            )
        except Exception:
            _dg_canonical_retail=0.0
        if _dg_canonical_retail > 0:
            market_retail=_dg_canonical_retail
            appraisal_retail=_dg_canonical_retail
            market_average=_dg_canonical_retail
            # Recalculate the vehicle-specific recommended retail and deal numbers
            # from the canonical valuation, regardless of which rescue source won.
            category_adjustment=-(market_average*(category_discount/100.0))
            modification_adjustment=market_average*(float(modification_pct)/100.0)
            recommended_retail=max(0,
                market_average + category_adjustment + modification_adjustment
                + grade_adjustment + service_adjustment + keys_adjustment
                + mot_time_adj + manual_retail_adjustment
            )
            max_buy=max(0,recommended_retail-prep-fees-detected_repair_cost-effective_mot_history_cost-contingency-target_margin)
            target_buy=max_buy-250
            opening_offer=target_buy-250
            target_buy_display=f"£{target_buy:,.0f}" if target_buy>0 else "N/A"
            opening_offer_display=f"£{opening_offer:,.0f}" if opening_offer>0 else "N/A"
            contribution_at_ask=recommended_retail-(asking+prep+fees+detected_repair_cost+effective_mot_history_cost+contingency)
            roi_at_ask=(contribution_at_ask/(asking+prep+fees+detected_repair_cost+contingency)*100) if (asking+prep+fees+detected_repair_cost+contingency)>0 else 0
            st.session_state["market_retail"]=market_retail
            st.session_state["market_estimate"]=market_estimate

        # V64 hard guard: missing valuation can never reach commercial cards.
        try:
            _dg_render_market=float(market_retail or 0)
        except Exception:
            _dg_render_market=0.0
        _dg_final_value=float(market_retail or (market_estimate or {}).get("retail",0) or (market_estimate or {}).get("market",0) or (market_estimate or {}).get("value",0) or (market_estimate or {}).get("average",0) or 0)
        if _dg_final_value>0:
            market_retail=_dg_final_value

        if _dg_render_market <= 0:
            st.error("NO USABLE MARKET VALUATION — no commercial recommendation calculated.")
            try:
                _dg_tools=autoza_mcp_tools()
                _dg_has_guide=any(isinstance(x,dict) and x.get("name")=="get_uk_price_guide" for x in _dg_tools)
                st.caption("Valuation source status: free UK price-guide service " + ("reachable." if _dg_has_guide else "not reachable."))
            except Exception:
                pass
            st.session_state["current_appraisal_ready"]=False
            with st.expander("VALUATION DEBUG", expanded=True):
                try:
                    _dbg_rest=len(comps or []) if "comps" in locals() else 0
                except Exception: _dbg_rest=0
                try:
                    _dbg_mcp=autoza_mcp_comparables(selected_make,selected_model,selected_year,20)
                except Exception as _e:
                    _dbg_mcp=[]; st.caption("MCP error: "+str(_e)[:180])
                try:
                    _dbg_pub=autoza_public_market_comparables(selected_make,selected_model,20)
                except Exception as _e:
                    _dbg_pub=[]; st.caption("Public-page error: "+str(_e)[:180])
                try:
                    _dbg_guide=autoza_price_guide(selected_make,selected_model)
                except Exception as _e:
                    _dbg_guide={}; st.caption("Guide error: "+str(_e)[:180])
                st.caption(f"REST rows: {_dbg_rest} • MCP usable rows: {len(_dbg_mcp)} • Public-page rows: {len(_dbg_pub)}")
                _dbg_age=[r for r in _dbg_pub if abs(int(_num(r,"year") or 0)-int(selected_year or 0))<=3]
                st.caption(f"Age-relevant public rows (±3 years): {len(_dbg_age)}")
                st.caption("Price guide parsed: "+(str(_dbg_guide)[:300] if _dbg_guide else "NO"))
                if _dbg_pub:
                    st.caption("Public sample: "+str(_dbg_pub[0])[:350])
            st.stop()

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

        # V100: structured evidence bank first. Web research is enrichment, never a dependency.
        try:
            _dg_bank_intel=dg_structured_issue_matches(selected_make,selected_model,selected_year,selected_engine,selected_fuel,selected_gearbox,mileage) or []
        except Exception:
            _dg_bank_intel=[]
        try:
            _dg_local_intel=dg_core_risk_matches(selected_make,selected_model,selected_fuel,selected_gearbox) or []
        except Exception:
            _dg_local_intel=[]
        try:
            _dg_research=dg_web_research(selected_make,selected_model,selected_year,selected_engine,selected_fuel,selected_gearbox)
        except Exception as _dg_research_error:
            _dg_research={"status":"research_unavailable","issues":[],"error":type(_dg_research_error).__name__}
        _dg_web_intel=_dg_research.get("issues",[]) if isinstance(_dg_research,dict) else []
        _dg_web_intel=dg_clean_issue_rows(_dg_web_intel)
        _dg_bank_intel=dg_clean_issue_rows(_dg_bank_intel)
        _dg_local_intel=dg_clean_issue_rows(_dg_local_intel)
        _dg_live_intel=_dg_bank_intel+_dg_local_intel+_dg_web_intel
        _seen_now=set()
        _dg_live_intel=[x for x in _dg_live_intel if not ((_dg_norm(x.get("issue","")) in _seen_now) or _seen_now.add(_dg_norm(x.get("issue",""))))]
        _dg_research_status=_dg_research.get("status","research_unavailable") if isinstance(_dg_research,dict) else "research_unavailable"
        _dg_match_level=_dg_research.get("match_level","exact") if isinstance(_dg_research,dict) else "exact"
        try:
            dg_store_intel(dg_clean_issue_rows(_dg_live_intel))
        except Exception:
            pass
        _dg_intel=[]
        # Legacy starter rules are optional; the live/learned engine must never crash if absent.
        _dg_legacy=globals().get("dg_buying_intelligence")
        if callable(_dg_legacy):
            try:
                _dg_intel=_dg_legacy(selected_make,selected_model,selected_year,selected_engine,selected_fuel,desc) or []
            except Exception:
                _dg_intel=[]
        try:
            _dg_intel+=dg_bank_buying_intelligence(selected_make,selected_model,selected_year,selected_engine,selected_fuel,selected_gearbox)
        except Exception:
            pass
        # Include newly researched findings immediately; dedupe by issue.
        _dg_intel+=_dg_live_intel
        _seen_issue=set()
        _dg_intel=[x for x in _dg_intel if not (_dg_norm(x.get("issue","")) in _seen_issue or _seen_issue.add(_dg_norm(x.get("issue",""))))]
        # Seed/refresh the learning bank from evidence that has passed DG's matching rules.
        _learn=[]
        for _i in _dg_intel:
            _x=dict(_i); _x.update({"make":selected_make,"model":selected_model,
                "year_from":_i.get("years",(selected_year,selected_year))[0] if isinstance(_i.get("years"),tuple) else _i.get("year_from",selected_year),
                "year_to":_i.get("years",(selected_year,selected_year))[1] if isinstance(_i.get("years"),tuple) else _i.get("year_to",selected_year),
                "engine_terms":"|".join(_i.get("engine_terms",[])) if isinstance(_i.get("engine_terms"),list) else _i.get("engine_terms",""),
                "fuel":selected_fuel,"gearbox":selected_gearbox,"evidence_type":_i.get("evidence_type","model knowledge"),
                "confidence":_i.get("confidence","Medium")})
            _learn.append(_x)
        dg_store_intel(_learn)
        st.markdown('<div class="dg-section">3 · Buying risks</div>',unsafe_allow_html=True)
        st.markdown('<div class="dg-sub">Known model problems first. High-severity items are shown before lower-risk checks.</div>',unsafe_allow_html=True)
        if any(str(x.get("severity","")).title()=="High" for x in _dg_live_intel):
            st.warning("Model-risk flag: HIGH to verify before buying — known risk, not a confirmed fault on this car.")
        elif any(str(x.get("severity","")).title()=="Medium" for x in _dg_live_intel):
            st.info("Model-risk flag: MEDIUM to verify before buying.")
        _status_label=_dg_research_status.replace("_"," ").title()
        _match_text={"exact":"Exact vehicle","model_fuel":"Model + fuel type","model":"Model-level"}.get(_dg_match_level,"Exact vehicle")
        with st.expander("Research details"):
            st.caption("DG combines its structured issue bank with live research. Safety recalls still need confirmation against the official recall service / registration where available.")
            st.markdown(f"**Status:** {_status_label}  \n**Coverage:** {_match_text}  \n**Findings:** {len(_dg_live_intel)}")
        if _dg_live_intel:
            st.success(f"DG found {len(_dg_live_intel)} relevant buying issue(s). Evidence bank: {len(_dg_bank_intel)} · live research: {len(_dg_web_intel)}.")
        elif _dg_intel: st.info("Using DG’s existing sourced buying-intelligence bank.")
        elif _dg_research_status=="research_unavailable": st.warning("Live research was unavailable. DG has not treated that as no known issues.")
        else: st.info("No verified exact match. DG is still showing broader model/fuel evidence where available.")
        if _dg_intel:
            _sev_order={"High":0,"Medium":1,"Low":2}
            _dg_intel=sorted(_dg_intel,key=lambda x:_sev_order.get(str(x.get("severity","Medium")).title(),1))
            for _i in _dg_intel:
                import html as _html
                _sev=str(_i.get("severity","Medium")).title(); _cls=_sev.lower() if _sev in ("High","Medium","Low") else "medium"
                _issue=_html.escape(str(_i.get("issue","Known issue"))); _ask=_html.escape(str(_i.get("ask","Ask for evidence of relevant maintenance or repair work."))); _check=_html.escape(str(_i.get("check","Inspect and verify before buying."))); _source=_html.escape(str(_i.get("source","Sourced model intelligence")))
                _etype=str(_i.get("evidence_type",""))
                _is_general=("general inspection risk" in _etype.lower())
                if _is_general and _sev=="High": _sev="Medium"
                _badge=("GENERAL BUYING CHECK" if _is_general else "KNOWN / SOURCED ISSUE")
                _lo=float(_i.get("cost_low",0) or 0); _hi=float(_i.get("cost_high",0) or 0); _mid=round(((_lo+_hi)/2)/50)*50 if (_lo or _hi) else 0
                _cost=(f"£{_lo:,.0f}–£{_hi:,.0f}" if _hi else "Cost not verified"); _plan=(f" · DG allowance £{_mid:,.0f}" if _mid else "")
                _mfrom=int(_i.get("mileage_from",0) or 0); _mnote=_html.escape(str(_i.get("mileage_note","") or "")); _current_miles=int(mileage or 0); _mileage_line=""
                if _mfrom:
                    _mileage_line=(f'<div class="dg-row"><b>Mileage relevance</b><br>This car is at {_current_miles:,} miles. DG holds this risk as more relevant from about {_mfrom:,} miles. {_mnote}</div>')
                _card=f'<div class="dg-intel-card {_cls}"><div><span class="dg-pill {_cls}">{_sev.upper()}</span><span class="dg-issue">{_issue}</span></div><div class="dg-row"><b>Ask seller</b><br>{_ask}</div><div class="dg-row"><b>Check before buying</b><br>{_check}</div>{_mileage_line}<div class="dg-row"><b>Evidence</b><br><strong>{_badge}</strong> · {_source} · {_html.escape(str(_i.get("confidence","Low")))} confidence</div><div class="dg-cost">Likely work: {_cost}{_plan}</div><div class="dg-row" style="font-size:.8rem;color:#667085">Source: {_source}</div></div>' 
                st.markdown(_card,unsafe_allow_html=True)
            _dg_cost_lows=[float(x.get("cost_low",0) or 0) for x in _dg_intel]; _dg_cost_highs=[float(x.get("cost_high",0) or 0) for x in _dg_intel]
            _dg_total_low=sum(_dg_cost_lows); _dg_total_high=sum(_dg_cost_highs); _dg_planning=round((sum((a+b)/2 for a,b in zip(_dg_cost_lows,_dg_cost_highs)))/50)*50
            if _dg_total_high>0:
                st.markdown(f'<div class="dg-intel-card"><div class="dg-issue">Potential work exposure</div><div class="dg-cost">£{_dg_total_low:,.0f}–£{_dg_total_high:,.0f}</div><div class="dg-row">Planning allowance: <b>£{_dg_planning:,.0f}</b></div><div class="dg-row" style="font-size:.82rem;color:#667085">Risk exposure only — confirm work before deducting it from the deal.</div></div>',unsafe_allow_html=True)
        else:
            st.markdown("""<div class="dg-intel-card"><div class="dg-issue">General seller questions</div>
<div class="dg-row">• Major maintenance or repairs — are there invoices?</div>
<div class="dg-row">• Warning lights, intermittent faults, oil/coolant use or starting issues?</div>
<div class="dg-row">• When were gearbox/transmission and scheduled fluids last serviced?</div>
<div class="dg-row">• Recent tyres, brakes, suspension, battery or air-conditioning work?</div></div>""",unsafe_allow_html=True)
        appraisal_record={"date":datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),"display_name":(reg.strip().upper() if str(reg or "").strip() else vehicle),"registration":reg,"vehicle":vehicle,"mileage":mileage,"asking":asking,"retail_est":appraisal_retail,"prep":prep,"fees":fees,"potential_contribution":round(margin,2),"roi_pct":round(roi,1),"max_buy":round(max_buy,2),"risk":risk,"score":score,"verdict":verdict,"notes":notes,"spec":selected_spec,"service_history":service_history,"keys":keys,"condition_grade":condition_grade,"grade_adjustment":grade_adjustment,"adjustment_age":scaled_mot["age"],"adjustment_market_value":round(market_average,2),"service_adjustment":service_adjustment,"keys_adjustment":keys_adjustment,"category":insurance_category,"category_discount":category_discount,"modification_level":modification_level,"modification_pct":modification_pct,"modification_adjustment":round(modification_adjustment,2),"modification_notes":modification_notes,"description_repair_allowance":detected_repair_cost,"description_repair_items":"; ".join(x["issue"] for x in repair_intel.get("items",[])),"recommended_retail":round(recommended_retail,2),"provenance":provenance,"v5c":v5c,"listing":""}
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
        st.markdown('<div class="dg-section">4 · Bid decision</div>',unsafe_allow_html=True)
        _dg_bid_position=(f"Seller asking £{float(asking):,.0f}" if float(asking or 0)>0 else "No seller asking price entered")
        if float(asking or 0)<=0:
            stress_retail_display=stress_prep_display=stress_both_display="N/A — enter seller asking"
        else:
            stress_retail_display=f"£{stress_retail:,.0f}"
            stress_prep_display=f"£{stress_prep:,.0f}"
            stress_both_display=f"£{stress_both:,.0f}"
        st.markdown(f"""<div class="dg-intel-card" style="border-left-color:#0f1b33"><div class="dg-issue">Your numbers to bid</div><div class="dg-row">{_dg_bid_position}</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px"><div><small>OPEN AT</small><div style="font-size:1.45rem;font-weight:800">£{opening_offer:,.0f}</div></div><div><small>AIM TO BUY</small><div style="font-size:1.45rem;font-weight:800">£{target_buy:,.0f}</div></div><div><small>MAXIMUM BUY</small><div style="font-size:1.45rem;font-weight:800">£{max_buy:,.0f}</div></div><div><small>ADVERTISE</small><div style="font-size:1.45rem;font-weight:800">£{recommended_retail:,.0f}</div></div></div><div class="dg-row"><b>Bid includes:</b> prep £{float(prep):,.0f} · other buying costs £{float(fees):,.0f} · MOT allowance £{float(effective_mot_history_cost):,.0f} · contingency £{float(contingency):,.0f} · target contribution £{float(target_margin):,.0f}</div><div class="dg-row"><b>If things go wrong</b><br>£500 lower retail: {stress_retail_display} · £500 extra prep: {stress_prep_display} · both: {stress_both_display}</div></div>""",unsafe_allow_html=True)
        st.markdown('<div class="dg-section">5 · Save appraisal</div>',unsafe_allow_html=True)
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
                saved.loc[0,"date"]=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
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
with st.sidebar.expander("DG MARKET COLLECTOR", expanded=False):
    _bank_stats=dg_market_bank_stats()
    st.caption(f"Saved observations: {_bank_stats['rows']} • model cohorts: {_bank_stats['models']}")
    st.caption("Every appraisal already saves genuine market observations. Use COLLECT NOW to run an extra pass for the currently selected vehicle.")
    if st.button("COLLECT CURRENT VEHICLE", use_container_width=True, key="dg_collect_current"):
        try:
            _cr=dg_collect_market(selected_make,selected_model,selected_year,mileage)
            st.success(f"Collected {len(_cr['rows'])} usable observations • wrote {_cr['stored']} records")
            st.caption("Sources: "+", ".join(f"{k} {v}" for k,v in _cr["sources"].items()))
        except Exception as _e:
            st.error(f"Collector could not complete: {_e}")
