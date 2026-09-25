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
    listing=st.text_input("Facebook Marketplace link",placeholder="Paste the advert/share link",key="listing_url")
    if st.button("IMPORT ADVERT",use_container_width=True):
        try:
            with st.spinner("Reading public advert details…"):
                imp=import_public_listing(listing)
            st.session_state["imp_vehicle"]=imp.get("vehicle") or ""
            st.session_state["imp_reg"]=imp.get("registration") or ""
            st.session_state["imp_mileage"]=int(imp.get("mileage") or 0)
            st.session_state["imp_asking"]=int(imp.get("price") or 0)
            st.session_state["imp_desc"]=imp.get("description") or ""
            if imp.get("blocked") or not any([imp.get("vehicle"),imp.get("price"),imp.get("mileage"),imp.get("registration")]):
                st.warning("Facebook did not expose enough public advert data from this link. Use the advert screenshot/text fallback below.")
            else:
                st.success("Advert details imported. Check them before analysing.")
        except Exception as e:
            st.warning("Facebook did not expose this advert to the importer. Use the screenshot/text fallback below.")
            st.session_state["import_error"]=str(e)

    with st.expander("Advert screenshot / text fallback"):
        st.file_uploader("Screenshot",type=["png","jpg","jpeg","webp"],help="Keeps the advert with the appraisal. Automatic screenshot reading is a later integration.")
        pasted=st.text_area("Paste advert text",placeholder="Paste the listing title, price, mileage and description")
        if st.button("EXTRACT PASTED TEXT",use_container_width=True) and pasted:
            blob=pasted
            pm=re.search(r'£\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,6})',blob)
            mm=re.search(r'([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,6})\s*(?:miles|mi)\b',blob,re.I)
            rm=re.search(r'\b([A-Z]{2}[0-9]{2}\s?[A-Z]{3})\b',blob.upper())
            if pm: st.session_state["imp_asking"]=int(pm.group(1).replace(",",""))
            if mm: st.session_state["imp_mileage"]=int(mm.group(1).replace(",",""))
            if rm: st.session_state["imp_reg"]=rm.group(1).replace(" ","")
            lines=[x.strip() for x in pasted.splitlines() if x.strip()]
            if lines: st.session_state["imp_vehicle"]=lines[0][:100]
            st.success("Text extracted. Check the fields below.")

    with st.form("appraise"):
        reg=st.text_input("Registration",value=st.session_state.get("imp_reg",""),placeholder="e.g. CV60 ZLZ").upper().replace(" ","")
        vehicle=st.text_input("Vehicle",value=st.session_state.get("imp_vehicle",""),placeholder="Make, model and derivative")
        a,b=st.columns(2); mileage=a.number_input("Mileage",0,300000,int(st.session_state.get("imp_mileage",0)),1000); asking=b.number_input("Seller asking (£)",0,100000,int(st.session_state.get("imp_asking",0)),50)
        a,b=st.columns(2); retail=a.number_input("Retail estimate (£)",0,150000,0,50); prep=b.number_input("Prep budget (£)",0,20000,400,50)
        a,b=st.columns(2); fees=a.number_input("Fees / warranty (£)",0,10000,250,25); risk=b.selectbox("Risk",["Low","Medium","High"],1)
        notes=st.text_area("Notes",placeholder="History, MOT, tyres, damage, keys…")
        go=st.form_submit_button("ANALYSE DEAL",use_container_width=True)
    if go:
        contingency,all_in,margin,roi,max_buy,score,verdict=calc(asking,retail,prep,fees,risk)
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
