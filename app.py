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


@st.cache_data(ttl=900, show_spinner=False)
def _autoza_mcp(tool_name, arguments):
    body={"jsonrpc":"2.0","id":1,"method":"tools/call",
          "params":{"name":tool_name,"arguments":arguments}}
    req=urllib.request.Request(
        "https://autoza.co.uk/api/mcp",
        data=json.dumps(body).encode(),
        headers={"User-Agent":"DG-Deal-Finder/1.0","Content-Type":"application/json","Accept":"application/json, text/event-stream"},
        method="POST")
    with urllib.request.urlopen(req,timeout=25) as r:
        raw=r.read().decode("utf-8","ignore")
    # MCP may answer JSON or SSE. Extract the last JSON data frame if SSE.
    candidates=[]
    if raw.lstrip().startswith("{"):
        candidates=[raw]
    else:
        candidates=[ln[6:] for ln in raw.splitlines() if ln.startswith("data: ")]
    if not candidates: raise RuntimeError("No response from market service")
    res=json.loads(candidates[-1])
    if res.get("error"): raise RuntimeError(str(res["error"]))
    result=res.get("result",{})
    # MCP content commonly wraps tool output as JSON text.
    for c in result.get("content",[]) if isinstance(result,dict) else []:
        if isinstance(c,dict) and c.get("type")=="text":
            txt=c.get("text","")
            try: return json.loads(txt)
            except: return {"text":txt}
    return result

def autoza_comparables(make, model, year, limit=25):
    # Documented MCP tool: live UK dealer stock.
    payload=_autoza_mcp("search_used_cars",{
        "make":make,"model":model,"min_year":max(1990,int(year)-1),
        "max_year":int(year)+1,"limit":min(int(limit),50)
    })
    if isinstance(payload,list): return payload
    if isinstance(payload,dict):
        for key in ("vehicles","results","cars","data","listings"):
            if isinstance(payload.get(key),list): return payload[key]
    return []

def autoza_price_guide(make, model):
    # Documented MCP tool: current asking-price guidance.
    return _autoza_mcp("get_uk_price_guide",{"make":make,"model":model})

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

def estimate_market_from_comps(rows, target_year, target_mileage):
    clean=[]
    for x in rows:
        if not isinstance(x,dict): continue
        price=_num(x,"price","asking_price","askingPrice")
        miles=_num(x,"mileage","miles","odometer")
        year=_num(x,"year","registration_year","registrationYear")
        if price and price>0:
            year=int(year or target_year); miles=float(miles or target_mileage or 0)
            clean.append((price,miles,year,x))
    if not clean: return None
    tm=float(target_mileage or 0)
    clean.sort(key=lambda z:(abs(z[2]-int(target_year))*30000 + (abs(z[1]-tm) if tm else 0)))
    chosen=clean[:min(12,len(clean))]
    prices=sorted(z[0] for z in chosen)
    n=len(prices); median=prices[n//2] if n%2 else (prices[n//2-1]+prices[n//2])/2
    return {"retail":median,"low":prices[0],"high":prices[-1],"count":len(chosen),"rows":[z[3] for z in chosen]}

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

tabs=st.tabs(["SOURCE","MARKET","DEALS","RULES"])

with tabs[0]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">Stock appraisal</div><div class="hero">Is it worth buying?</div><div class="sub">Appraise a car against your target margin before you message the seller.</div></div>',unsafe_allow_html=True)
    st.markdown('<div class="section">Choose vehicle</div>',unsafe_allow_html=True)
    st.caption("Choose make, year and model from built-in lists. Model options update instantly — no API key required.")
    a,b=st.columns(2)
    selected_make=a.selectbox("Make",[""]+UK_MAKES)
    selected_year=b.selectbox("Year",list(range(2026,1995,-1)),index=16)
    models=[]
    if selected_make:
        try:
            models=free_models_for_make_year(selected_make,selected_year)
        except Exception:
            models=[]
    selected_model=st.selectbox("Model",["— Choose model —"]+models,disabled=not bool(selected_make))
    if selected_model=="— Choose model —": selected_model=""
    specs=COMMON_UK_SPECS.get((selected_make,selected_model),[])
    if specs:
        selected_spec=st.selectbox("Trim / spec",[""]+specs)
    else:
        selected_spec=""
        if selected_model:
            st.info("Exact UK trim isn't in the free catalogue yet, so DG won't guess it.")
    cat_mileage=st.number_input("Mileage",0,500000,0,1000,key="catalogue_mileage")
    reg_manual=st.text_input("Registration (optional)",placeholder="e.g. DA59 XDG")
    if selected_make and selected_model:
        label=f"{selected_year} {selected_make} {selected_model}"
        if selected_spec: label+=f" {selected_spec}"
        st.session_state["imp_vehicle"]=label
        st.session_state["imp_mileage"]=int(cat_mileage)
        st.session_state["imp_reg"]=re.sub(r"[^A-Za-z0-9]","",reg_manual).upper()
        st.success(f"Selected: {label}")
        st.session_state["selected_make"]=selected_make
        st.session_state["selected_model"]=selected_model
        st.session_state["selected_year"]=selected_year
        if st.button("GET LIVE MARKET ESTIMATE",use_container_width=True,type="primary"):
            try:
                with st.spinner("Checking similar UK dealer adverts…"):
                    comps=autoza_comparables(selected_make,selected_model,selected_year,25)
                    market=estimate_market_from_comps(comps,selected_year,cat_mileage)
                    if not market:
                        guide=autoza_price_guide(selected_make,selected_model)
                        # Extract common price-guide names recursively.
                        typical=_pick(guide,"typical","typical_price","typicalPrice","median","average","average_price")
                        low=_pick(guide,"lowest","low","min","minimum")
                        high=_pick(guide,"highest","high","max","maximum")
                        def cv(v):
                            try: return float(re.sub(r"[^0-9.]","",str(v)))
                            except: return None
                        typical,low,high=cv(typical),cv(low),cv(high)
                        if typical:
                            market={"retail":typical,"low":low or typical,"high":high or typical,"count":0,"rows":[]}
                if market:
                    st.session_state["market_estimate"]=market
                    st.session_state["market_retail"]=int(round(market["retail"]/50)*50)
                    st.success(f'Found {market["count"]} close comparables · estimated retail £{st.session_state["market_retail"]:,.0f}')
                else:
                    st.session_state.pop("market_estimate",None)
                    st.session_state.pop("market_retail",None)
                    st.warning("No close live comparables found for that vehicle.")
            except Exception as e:
                st.error("Live market lookup is temporarily unavailable.")
                with st.expander("Technical detail"): st.code(str(e))

    market=st.session_state.get("market_estimate")
    if market:
        c1,c2,c3=st.columns(3)
        c1.metric("Est. retail",f'£{st.session_state.get("market_retail",0):,.0f}')
        c2.metric("Comparable low",f'£{market["low"]:,.0f}')
        c3.metric("Comparable high",f'£{market["high"]:,.0f}')
        st.caption(f'Based on {market["count"]} closest live dealer asking prices. Asking price is not the same as achieved sale price.')
        with st.expander("Similar cars currently advertised"):
            for car in market["rows"][:8]:
                title=f'{car.get("year","")} {car.get("make","")} {car.get("model","")}'
                detail=f'£{float(car.get("price",0)):,.0f} · {int(car.get("mileage") or 0):,} miles'
                url=car.get("url")
                if url:
                    st.markdown(f'**{title}** — {detail}  \n[View advert]({url})')
                else:
                    st.write(f'{title} — {detail}')

    with st.form("appraise"):
        reg=st.text_input("Registration",value=st.session_state.get("imp_reg",""),placeholder="e.g. CV60 ZLZ").upper().replace(" ","")
        vehicle=st.text_input("Vehicle",value=st.session_state.get("imp_vehicle",""),placeholder="Make, model and derivative")
        a,b=st.columns(2); mileage=a.number_input("Mileage",0,300000,int(st.session_state.get("imp_mileage",0)),1000); asking=b.number_input("Seller asking (£)",0,100000,int(st.session_state.get("imp_asking",0)),50)
        a,b=st.columns(2); retail=a.number_input("Retail estimate (£)",0,150000,int(st.session_state.get("market_retail",0)),50,help="Auto-filled from live market data; editable."); prep=b.number_input("Prep budget (£)",0,20000,400,50)
        a,b=st.columns(2); fees=a.number_input("Fees / warranty (£)",0,10000,250,25); risk="Medium"
        target_margin=st.number_input("Desired contribution / margin (£)",0,20000,int(st.session_state.min_profit),50,help="Your target gross contribution before fixed overhead and tax.")
        notes=st.text_area("Notes",value=st.session_state.get("imp_desc",""),placeholder="History, MOT, tyres, damage, keys…")
        risk,risk_reasons=analyse_risk(st.session_state.get("selected_year",2020),mileage,st.session_state.get("selected_make",""),st.session_state.get("selected_model",""),notes)
        st.markdown(f"**DG risk analysis: {risk}**")
        st.caption(" · ".join(risk_reasons))
        if st.session_state.get("scan_year") or st.session_state.get("scan_fuel") or st.session_state.get("scan_gearbox"):
            st.caption("Detected: " + " · ".join([str(x) for x in [st.session_state.get("scan_year"),st.session_state.get("scan_fuel"),st.session_state.get("scan_gearbox")] if x]))
        go=st.form_submit_button("ANALYSE DEAL",use_container_width=True)
    if go:
        contingency,all_in,margin,roi,max_buy,score,verdict=calc(asking,retail,prep,fees,risk)
        max_buy=max(0,retail-prep-fees-contingency-target_margin)
        verdict="BUY" if margin>=target_margin and roi>=st.session_state.min_roi and risk!="High" else ("RESEARCH" if margin>=target_margin*.6 and risk!="High" else "PASS")
        klass={"BUY":"good","RESEARCH":"warn","PASS":"bad"}[verdict]
        st.markdown(f'<div class="card"><div class="label">DG appraisal</div><div class="car">{vehicle or "Vehicle appraisal"}</div><div class="meta">{reg or "No registration"} · {mileage:,} miles</div><span class="chip {klass}">{verdict} · DG SCORE {score}/100</span></div>',unsafe_allow_html=True)
        a,b=st.columns(2); a.metric("Estimated retail",f"£{retail:,.0f}"); b.metric("Potential margin",f"£{margin:,.0f}")
        a,b=st.columns(2); a.metric("Maximum buy",f"£{max_buy:,.0f}"); b.metric("ROI",f"{roi:.1f}%")

        st.markdown('<div class="section">Auto Trader market guide</div>',unsafe_allow_html=True)
        if at_configured() and reg:
            try:
                at_raw=fetch_at_vehicle(reg,mileage)
                at=normalise_at(at_raw)
                st.markdown('<div class="card"><div class="label">Official Auto Trader Connect</div><div class="car">Live market intelligence</div><div class="meta">Vehicle lookup using registration and mileage.</div></div>',unsafe_allow_html=True)
                c1,c2=st.columns(2); c1.metric("Retail",money(at["retail"])); c2.metric("Trade",money(at["trade"]))
                if at["retail"] is not None:
                    at_margin=at["retail"]-(asking+prep+fees+contingency)
                    at_max=max(0,at["retail"]-prep-fees-contingency-target_margin)
                    c1,c2=st.columns(2); c1.metric("Margin @ AT retail",f"£{at_margin:,.0f}"); c2.metric("Max buy @ target",f"£{at_max:,.0f}")
                c1,c2=st.columns(2); c1.metric("Private",money(at["private"])); c2.metric("Part exchange",money(at["part_exchange"]))
                c1,c2=st.columns(2); c1.metric("Retail rating","—" if at["retail_rating"] is None else f'{at["retail_rating"]:.0f}/100'); c2.metric("Days to sell","—" if at["days_to_sell"] is None else f'{at["days_to_sell"]:.0f} days')
                c1,c2=st.columns(2); c1.metric("Demand",metric_pct(at["demand"])); c2.metric("Supply",metric_pct(at["supply"]))
                st.metric("Market condition",metric_pct(at["market_condition"]))
            except Exception as e:
                st.warning("Auto Trader Connect is configured but the live request did not complete. Check the endpoint/header settings in Streamlit Secrets.")
                with st.expander("Connection detail"):
                    st.code(str(e))
        else:
            st.markdown('<div class="card"><div class="label">Auto Trader Connect</div><div class="car">Ready for official live data</div><div class="meta">Add your Auto Trader Connect production or sandbox credentials in Streamlit Secrets to activate Retail, Trade, Private, Part Exchange, Retail Rating, Days to Sell, Supply, Demand and Market Condition.</div></div>',unsafe_allow_html=True)

        st.markdown('<div class="section">Market trend</div>',unsafe_allow_html=True)
        st.markdown(f'<div class="card"><div class="label">6 month retail value</div><div class="car">£{retail:,.0f} estimated retail</div>{trend_svg()}<div class="meta">Preview only — connect live valuation/comparable data before using this trend for buying decisions.</div></div>',unsafe_allow_html=True)
        row=pd.DataFrame([{"date":datetime.now().strftime("%Y-%m-%d %H:%M"),"registration":reg,"vehicle":vehicle,"mileage":mileage,"asking":asking,"retail_est":retail,"prep":prep,"fees":fees,"potential_contribution":round(margin,2),"roi_pct":round(roi,1),"max_buy":round(max_buy,2),"risk":risk,"score":score,"verdict":verdict,"notes":notes,"listing":listing}])
        if DATA.exists(): row=pd.concat([pd.read_csv(DATA),row],ignore_index=True)
        row.to_csv(DATA,index=False)
    st.markdown('</div>',unsafe_allow_html=True)

with tabs[1]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">Market intelligence</div><div class="hero">What is moving?</div><div class="sub">Pricing, demand and days-to-sell signals will live here.</div></div>',unsafe_allow_html=True)
    st.markdown(f'<div class="card"><div class="label">Retail price movement</div><div class="car">Target market trend</div>{trend_svg()}<div class="meta">No fake data: this becomes live once a valuation/comparables source is connected.</div></div>',unsafe_allow_html=True)
    a,b=st.columns(2); a.metric("Retail valuation","LIVE" if at_configured() else "—"); b.metric("Days to sell","LIVE" if at_configured() else "—")
    a,b=st.columns(2); a.metric("Retail rating","LIVE" if at_configured() else "—"); b.metric("Demand","LIVE" if at_configured() else "—")
    st.markdown('<div class="card"><div class="label">Planned intelligence</div><div class="car">Fastest sellers · biggest margins · falling values</div><div class="meta">Filter by make, model, fuel, age, mileage and retail price band.</div></div></div>',unsafe_allow_html=True)

with tabs[2]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">Opportunity list</div><div class="hero">Saved deals</div><div class="sub">Keep your strongest sourcing opportunities in one place.</div></div>',unsafe_allow_html=True)
    if DATA.exists():
        df=pd.read_csv(DATA).sort_values(["score","potential_contribution"],ascending=False)
        for _,r in df.iterrows():
            klass={"BUY":"good","BUY CANDIDATE":"good","RESEARCH":"warn","INVESTIGATE":"warn","PASS":"bad"}.get(str(r.get("verdict")),"warn")
            st.markdown(f'<div class="card"><div class="car">{r.get("vehicle","Vehicle")}</div><div class="meta">{r.get("registration","")} · {int(r.get("mileage",0)):,} miles</div><span class="chip {klass}">{r.get("verdict","")}</span></div>',unsafe_allow_html=True)
            a,b,c=st.columns(3); a.metric("Ask",f"£{r.get('asking',0):,.0f}"); b.metric("Margin",f"£{r.get('potential_contribution',0):,.0f}"); c.metric("Score",f"{int(r.get('score',0))}")
        st.download_button("Export deals",df.to_csv(index=False).encode(),"dg_deals.csv","text/csv",use_container_width=True)
    else: st.info("No saved deals yet.")
    st.markdown('</div>',unsafe_allow_html=True)

with tabs[3]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">Buying discipline</div><div class="hero">Your rules</div><div class="sub">Set the economics every stock opportunity has to clear.</div></div>',unsafe_allow_html=True)
    st.session_state.min_profit=st.number_input("Minimum contribution (£)",0,10000,int(st.session_state.min_profit),50)
    st.session_state.min_roi=st.number_input("Minimum ROI (%)",0,200,int(st.session_state.min_roi),1)
    st.session_state.contingency_pct=st.number_input("Prep contingency (%)",0,100,int(st.session_state.contingency_pct),5)
    st.markdown('<div class="card"><div class="meta"><b>Contribution</b> is estimated retail less purchase, prep, selling costs and prep contingency. It is not net profit after fixed overhead, tax or finance.</div></div></div>',unsafe_allow_html=True)
