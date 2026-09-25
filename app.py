
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
from PIL import Image

st.set_page_config(
    page_title="DG Deal Finder",
    page_icon="🚗",
    layout="centered",
    initial_sidebar_state="collapsed"
)

DATA = Path(__file__).with_name("deals.csv")

st.markdown("""
<style>
:root{
  --dg-ink:#171816;
  --dg-muted:#74746e;
  --dg-paper:#f6f3ec;
  --dg-card:#ffffff;
  --dg-line:#e7e1d7;
  --dg-soft:#efebe3;
  --dg-good:#244f3b;
  --dg-warn:#8a641d;
  --dg-bad:#743934;
}
html, body, [class*="css"] {font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;}
.stApp {background:var(--dg-paper);}
.block-container {max-width:760px; padding:1.15rem 1rem 5rem;}
header[data-testid="stHeader"] {background:transparent;}
#MainMenu, footer {visibility:hidden;}

.dg-brand{
  background:var(--dg-ink); color:#fff; border-radius:20px; padding:18px 20px 16px;
  margin:0 0 14px; box-shadow:0 10px 30px rgba(0,0,0,.08);
}
.dg-kicker{font-size:.70rem; letter-spacing:.20em; text-transform:uppercase; opacity:.65; font-weight:800;}
.dg-title{font-size:1.78rem; line-height:1.05; font-weight:900; margin:4px 0 5px; letter-spacing:-.035em;}
.dg-sub{font-size:.88rem; opacity:.74; margin:0;}

h1,h2,h3{color:var(--dg-ink); letter-spacing:-.025em;}
h2{font-size:1.25rem !important; margin-top:.5rem !important;}
label, .stCaption {color:var(--dg-muted) !important;}

div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-baseweb="select"] > div {
  background:#fff !important; border-color:var(--dg-line) !important; border-radius:12px !important;
}
div[data-testid="stMetric"]{
  background:#fff; border:1px solid var(--dg-line); padding:12px 13px;
  border-radius:15px; box-shadow:0 3px 12px rgba(0,0,0,.025);
}
div[data-testid="stMetricLabel"]{font-size:.72rem;}
div[data-testid="stMetricValue"]{font-weight:850; letter-spacing:-.04em;}

.stButton>button, .stFormSubmitButton>button, .stLinkButton>a, .stDownloadButton>button{
  min-height:48px; border-radius:13px; font-weight:800; border:1px solid var(--dg-line);
}
.stFormSubmitButton>button{
  background:var(--dg-ink) !important; color:white !important; border-color:var(--dg-ink) !important;
}
.stButton>button:hover, .stFormSubmitButton>button:hover{transform:translateY(-1px);}

.dg-help{
  background:var(--dg-soft); border:1px solid var(--dg-line); border-radius:14px;
  padding:12px 14px; color:#55554f; font-size:.87rem; margin-bottom:14px;
}
.verdict{
  padding:18px 16px; border-radius:18px; color:white; margin:10px 0 15px;
  box-shadow:0 8px 24px rgba(0,0,0,.08);
}
.verdict-small{font-size:.70rem; letter-spacing:.16em; text-transform:uppercase; opacity:.72; font-weight:800;}
.verdict-main{font-size:1.42rem; font-weight:900; letter-spacing:-.03em; margin-top:2px;}
.verdict-score{font-size:.85rem; opacity:.84; margin-top:3px;}

.deal-card{
  background:#fff; border:1px solid var(--dg-line); border-radius:17px; padding:15px;
  margin:0 0 12px; box-shadow:0 3px 12px rgba(0,0,0,.025);
}
.deal-name{font-weight:900; font-size:1rem; color:var(--dg-ink);}
.deal-meta{font-size:.80rem; color:var(--dg-muted); margin-top:2px;}
.small{font-size:.82rem; color:var(--dg-muted);}
hr{border-color:var(--dg-line) !important;}
</style>
""", unsafe_allow_html=True)

if "screen" not in st.session_state:
    st.session_state.screen = "analyse"

defaults = {"min_profit":1000, "min_roi":25, "contingency_pct":20}
for k,v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

st.markdown("""
<div class="dg-brand">
  <div class="dg-kicker">DG MOTORWORKS</div>
  <div class="dg-title">Deal Finder</div>
  <p class="dg-sub">Buy smarter. Protect the margin.</p>
</div>
""", unsafe_allow_html=True)

n1,n2,n3 = st.columns(3)
if n1.button("Analyse", use_container_width=True): st.session_state.screen="analyse"
if n2.button("Saved", use_container_width=True): st.session_state.screen="deals"
if n3.button("Rules", use_container_width=True): st.session_state.screen="rules"

def score_deal(asking, retail, prep, fees, risk):
    contingency = prep * st.session_state.contingency_pct/100
    all_in = asking + prep + fees + contingency
    contribution = retail - all_in
    roi = contribution/all_in*100 if all_in else 0
    max_buy = max(0, retail - prep - fees - contingency - st.session_state.min_profit)
    score = 50
    score += min(25, max(-25, (contribution-st.session_state.min_profit)/40))
    score += min(15, max(-15, (roi-st.session_state.min_roi)/2))
    score += {"Low":10,"Medium":0,"High":-20}[risk]
    score = max(0,min(100,round(score)))
    if contribution >= st.session_state.min_profit and roi >= st.session_state.min_roi and risk != "High":
        verdict="BUY CANDIDATE"
    elif contribution >= st.session_state.min_profit*0.6 and risk != "High":
        verdict="INVESTIGATE"
    else:
        verdict="PASS"
    return contingency, all_in, contribution, roi, max_buy, score, verdict

if st.session_state.screen == "rules":
    st.subheader("Buying rules")
    st.caption("Set the minimum economics a car needs to meet before DG considers it.")
    st.session_state.min_profit = st.number_input("Minimum target contribution (£)",0,10000,int(st.session_state.min_profit),50)
    st.session_state.min_roi = st.number_input("Minimum ROI on all-in cost (%)",0,200,int(st.session_state.min_roi),1)
    st.session_state.contingency_pct = st.number_input("Prep contingency (%)",0,100,int(st.session_state.contingency_pct),5)
    st.markdown(
        '<div class="dg-help"><b>Contribution</b> is estimated retail less purchase, prep, allocated selling costs and prep contingency. '
        'It is not profit after rent, wages, tax or other fixed overhead.</div>',
        unsafe_allow_html=True
    )

elif st.session_state.screen == "deals":
    st.subheader("Saved opportunities")
    if DATA.exists():
        df = pd.read_csv(DATA).sort_values(["score","potential_contribution"], ascending=False)
        for _,r in df.iterrows():
            vehicle = r.get("vehicle","Vehicle")
            reg = r.get("registration","")
            miles = int(r.get("mileage",0))
            st.markdown(
                f'<div class="deal-card"><div class="deal-name">{vehicle}</div>'
                f'<div class="deal-meta">{reg} · {miles:,} miles · {r.get("verdict","")}</div></div>',
                unsafe_allow_html=True
            )
            a,b,c = st.columns(3)
            a.metric("ASK",f"£{r.get('asking',0):,.0f}")
            b.metric("MARGIN",f"£{r.get('potential_contribution',0):,.0f}")
            c.metric("DG SCORE",f"{int(r.get('score',0))}")
            st.caption(f"Max buy £{r.get('max_buy',0):,.0f} · Retail £{r.get('retail_est',0):,.0f}")
            url = str(r.get("listing",""))
            if url.startswith("http"):
                st.link_button("Open advert",url,use_container_width=True)
            st.write("")
        st.download_button("Export deal list", df.to_csv(index=False).encode(), "dg_deals.csv","text/csv",use_container_width=True)
    else:
        st.info("No saved opportunities yet. Appraise your first car in Analyse.")

else:
    st.subheader("Appraise a car")
    st.markdown(
        '<div class="dg-help">Found something on Marketplace? Paste the advert link, enter the key numbers and DG will calculate '
        'your margin, ROI and maximum sensible buy price.</div>',
        unsafe_allow_html=True
    )

    listing = st.text_input("Advert link", placeholder="Paste Facebook Marketplace or advert link")
    shot = st.file_uploader("Listing screenshot · optional", type=["png","jpg","jpeg","webp"], accept_multiple_files=False)
    if shot:
        img = Image.open(shot)
        st.image(img, caption="Advert screenshot", use_container_width=True)

    with st.form("mobile_deal", clear_on_submit=False):
        reg = st.text_input("Registration", placeholder="CV60 ZLZ").upper().replace(" ","")
        vehicle = st.text_input("Vehicle", placeholder="2014 Ford Fiesta 1.25 Zetec")

        c1,c2 = st.columns(2)
        mileage = c1.number_input("Mileage",0,300000,70000,1000)
        asking = c2.number_input("Asking price (£)",0,100000,3000,50)

        c1,c2 = st.columns(2)
        retail = c1.number_input("Retail estimate (£)",0,150000,4500,50)
        prep = c2.number_input("Prep budget (£)",0,20000,400,50)

        c1,c2 = st.columns(2)
        fees = c1.number_input("Fees / warranty (£)",0,10000,250,25)
        risk = c2.selectbox("Risk level",["Low","Medium","High"],index=1)

        notes = st.text_area("Appraisal notes", placeholder="History, MOT, keys, tyres, damage, warning lights...")
        submit = st.form_submit_button("RUN DG APPRAISAL", use_container_width=True)

    if submit:
        contingency, all_in, contribution, roi, max_buy, score, verdict = score_deal(asking,retail,prep,fees,risk)
        bg = {"BUY CANDIDATE":"#244f3b","INVESTIGATE":"#8a641d","PASS":"#743934"}[verdict]
        st.markdown(
            f'<div class="verdict" style="background:{bg}">'
            f'<div class="verdict-small">DG DECISION</div>'
            f'<div class="verdict-main">{verdict}</div>'
            f'<div class="verdict-score">Deal score {score}/100</div></div>',
            unsafe_allow_html=True
        )

        a,b = st.columns(2)
        a.metric("POTENTIAL MARGIN",f"£{contribution:,.0f}")
        b.metric("MAXIMUM BUY",f"£{max_buy:,.0f}")
        a,b = st.columns(2)
        a.metric("ALL-IN COST",f"£{all_in:,.0f}")
        b.metric("ROI",f"{roi:.1f}%")

        if asking > max_buy:
            st.warning(f"Target negotiation: about £{asking-max_buy:,.0f} below asking to preserve your £{st.session_state.min_profit:,.0f} contribution target.")
        else:
            st.success(f"Asking price is £{max_buy-asking:,.0f} inside your target maximum buy — subject to inspection and history.")

        row = pd.DataFrame([{
            "date":datetime.now().strftime("%Y-%m-%d %H:%M"),"registration":reg,"vehicle":vehicle,
            "mileage":mileage,"asking":asking,"retail_est":retail,"prep":prep,"fees":fees,
            "contingency":round(contingency,2),"all_in":round(all_in,2),
            "potential_contribution":round(contribution,2),"roi_pct":round(roi,1),
            "max_buy":round(max_buy,2),"risk":risk,"score":score,"verdict":verdict,
            "notes":notes,"listing":listing
        }])
        if DATA.exists():
            row = pd.concat([pd.read_csv(DATA),row],ignore_index=True)
        row.to_csv(DATA,index=False)

        if listing.startswith("http"):
            st.link_button("RETURN TO ADVERT",listing,use_container_width=True)

        with st.expander("Pre-purchase checklist"):
            st.write(
                "✓ Verify VIN, identity and seller ownership\n\n"
                "✓ Check MOT and mileage history\n\n"
                "✓ Check finance, write-off and theft provenance\n\n"
                "✓ Inspect from cold and road-test\n\n"
                "✓ Confirm history, keys, tyres and warning lights\n\n"
                "✓ Recheck live retail comparables"
            )

st.divider()
st.caption("DG Motorworks · Deal Finder V3 · Appraisal support, not a substitute for physical inspection or provenance checks.")
