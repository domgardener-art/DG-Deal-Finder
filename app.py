import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

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

for k,v in {"min_profit":1000,"min_roi":25,"contingency_pct":20}.items():
    if k not in st.session_state: st.session_state[k]=v

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
    listing=st.text_input("Advert link",placeholder="Paste Marketplace or advert link")
    with st.form("appraise"):
        reg=st.text_input("Registration",placeholder="CV60 ZLZ").upper().replace(" ","")
        vehicle=st.text_input("Vehicle",placeholder="2014 Ford Fiesta 1.25 Zetec")
        a,b=st.columns(2); mileage=a.number_input("Mileage",0,300000,70000,1000); asking=b.number_input("Seller asking (£)",0,100000,3000,50)
        a,b=st.columns(2); retail=a.number_input("Retail estimate (£)",0,150000,4500,50); prep=b.number_input("Prep budget (£)",0,20000,400,50)
        a,b=st.columns(2); fees=a.number_input("Fees / warranty (£)",0,10000,250,25); risk=b.selectbox("Risk",["Low","Medium","High"],1)
        notes=st.text_area("Notes",placeholder="History, MOT, tyres, damage, keys…")
        go=st.form_submit_button("ANALYSE DEAL",use_container_width=True)
    if go:
        contingency,all_in,margin,roi,max_buy,score,verdict=calc(asking,retail,prep,fees,risk)
        klass={"BUY":"good","RESEARCH":"warn","PASS":"bad"}[verdict]
        st.markdown(f'<div class="card"><div class="label">DG appraisal</div><div class="car">{vehicle or "Vehicle appraisal"}</div><div class="meta">{reg or "No registration"} · {mileage:,} miles</div><span class="chip {klass}">{verdict} · DG SCORE {score}/100</span></div>',unsafe_allow_html=True)
        a,b=st.columns(2); a.metric("Estimated retail",f"£{retail:,.0f}"); b.metric("Potential margin",f"£{margin:,.0f}")
        a,b=st.columns(2); a.metric("Maximum buy",f"£{max_buy:,.0f}"); b.metric("ROI",f"{roi:.1f}%")
        st.markdown('<div class="section">Market trend</div>',unsafe_allow_html=True)
        st.markdown(f'<div class="card"><div class="label">6 month retail value</div><div class="car">£{retail:,.0f} estimated retail</div>{trend_svg()}<div class="meta">Preview only — connect live valuation/comparable data before using this trend for buying decisions.</div></div>',unsafe_allow_html=True)
        row=pd.DataFrame([{"date":datetime.now().strftime("%Y-%m-%d %H:%M"),"registration":reg,"vehicle":vehicle,"mileage":mileage,"asking":asking,"retail_est":retail,"prep":prep,"fees":fees,"potential_contribution":round(margin,2),"roi_pct":round(roi,1),"max_buy":round(max_buy,2),"risk":risk,"score":score,"verdict":verdict,"notes":notes,"listing":listing}])
        if DATA.exists(): row=pd.concat([pd.read_csv(DATA),row],ignore_index=True)
        row.to_csv(DATA,index=False)
    st.markdown('</div>',unsafe_allow_html=True)

with tabs[1]:
    st.markdown('<div class="dg-wrap"><div class="dg-hero"><div class="eyebrow">Market intelligence</div><div class="hero">What is moving?</div><div class="sub">Pricing, demand and days-to-sell signals will live here.</div></div>',unsafe_allow_html=True)
    st.markdown(f'<div class="card"><div class="label">Retail price movement</div><div class="car">Target market trend</div>{trend_svg()}<div class="meta">No fake data: this becomes live once a valuation/comparables source is connected.</div></div>',unsafe_allow_html=True)
    a,b=st.columns(2); a.metric("Price trend","—"); b.metric("Days to sell","—")
    a,b=st.columns(2); a.metric("Comparable cars","—"); b.metric("Demand","—")
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
