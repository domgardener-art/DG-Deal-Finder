
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
from PIL import Image
import io

st.set_page_config(page_title="DG Deal Finder Mobile", page_icon="🚗", layout="centered", initial_sidebar_state="collapsed")

DATA = Path(__file__).with_name("deals.csv")

st.markdown("""
<style>
.block-container {max-width: 760px; padding-top: 1rem; padding-bottom: 5rem;}
div[data-testid="stMetric"] {border:1px solid rgba(128,128,128,.25); padding:10px; border-radius:12px;}
.stButton>button, .stFormSubmitButton>button, .stLinkButton>a {min-height:48px; border-radius:12px; font-weight:700;}
h1 {font-size:2rem !important;}
.small {opacity:.72; font-size:.88rem;}
.verdict {padding:14px;border-radius:14px;font-weight:800;text-align:center;font-size:1.25rem;margin:8px 0 14px 0;}
</style>
""", unsafe_allow_html=True)

if "screen" not in st.session_state:
    st.session_state.screen = "analyse"

st.title("DG Deal Finder")
st.caption("Phone-first sourcing app • Marketplace → paste/share details → appraise → save")

# Top navigation
n1,n2,n3 = st.columns(3)
if n1.button("🔎 Analyse", use_container_width=True): st.session_state.screen="analyse"
if n2.button("⭐ Deals", use_container_width=True): st.session_state.screen="deals"
if n3.button("⚙️ Rules", use_container_width=True): st.session_state.screen="rules"

# Defaults kept in session
defaults = {"min_profit":1000, "min_roi":25, "contingency_pct":20}
for k,v in defaults.items():
    if k not in st.session_state: st.session_state[k]=v

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
    st.session_state.min_profit = st.number_input("Minimum target contribution (£)",0,10000,int(st.session_state.min_profit),50)
    st.session_state.min_roi = st.number_input("Minimum ROI on all-in cost (%)",0,200,int(st.session_state.min_roi),1)
    st.session_state.contingency_pct = st.number_input("Contingency on prep (%)",0,100,int(st.session_state.contingency_pct),5)
    st.info("Contribution = estimated retail less purchase, prep, allocated selling costs and prep contingency. It is not profit after rent, wages, tax or other fixed overhead.")

elif st.session_state.screen == "deals":
    st.subheader("Saved deals")
    if DATA.exists():
        df = pd.read_csv(DATA)
        df = df.sort_values(["score","potential_contribution"], ascending=False)
        for _,r in df.iterrows():
            with st.container(border=True):
                st.markdown(f"**{r.get('vehicle','Vehicle')}**  \n{r.get('registration','')} • {int(r.get('mileage',0)):,} miles")
                a,b,c = st.columns(3)
                a.metric("Ask",f"£{r.get('asking',0):,.0f}")
                b.metric("Margin",f"£{r.get('potential_contribution',0):,.0f}")
                c.metric("Score",f"{int(r.get('score',0))}/100")
                st.caption(f"{r.get('verdict','')} • Max buy £{r.get('max_buy',0):,.0f} • Retail est. £{r.get('retail_est',0):,.0f}")
                url = str(r.get("listing",""))
                if url.startswith("http"):
                    st.link_button("Open listing",url,use_container_width=True)
        st.download_button("Export all deals", df.to_csv(index=False).encode(), "dg_deals.csv","text/csv",use_container_width=True)
    else:
        st.info("No saved deals yet.")

else:
    st.subheader("Quick appraisal")
    st.markdown('<div class="small">From Facebook Marketplace: use <b>Share → Copy link</b>, then paste it below. Add a screenshot if you want it stored with the appraisal.</div>', unsafe_allow_html=True)
    listing = st.text_input("Marketplace / advert link", placeholder="Paste listing link")
    shot = st.file_uploader("Listing screenshot (optional)", type=["png","jpg","jpeg","webp"], accept_multiple_files=False)
    if shot:
        img = Image.open(shot)
        st.image(img, caption="Listing screenshot", use_container_width=True)

    with st.form("mobile_deal", clear_on_submit=False):
        reg = st.text_input("Registration", placeholder="CV60 ZLZ").upper().replace(" ","")
        vehicle = st.text_input("Vehicle", placeholder="2014 Ford Fiesta 1.25 Zetec")
        c1,c2 = st.columns(2)
        mileage = c1.number_input("Mileage",0,300000,70000,1000)
        asking = c2.number_input("Asking (£)",0,100000,3000,50)
        c1,c2 = st.columns(2)
        retail = c1.number_input("Realistic retail (£)",0,150000,4500,50)
        prep = c2.number_input("Prep (£)",0,20000,400,50)
        c1,c2 = st.columns(2)
        fees = c1.number_input("Fees / warranty (£)",0,10000,250,25)
        risk = c2.selectbox("Risk",["Low","Medium","High"],index=1)
        notes = st.text_area("Notes", placeholder="Service history, MOT, keys, tyres, damage, warning lights...")
        submit = st.form_submit_button("ANALYSE DEAL", use_container_width=True)

    if submit:
        contingency, all_in, contribution, roi, max_buy, score, verdict = score_deal(asking,retail,prep,fees,risk)
        bg = {"BUY CANDIDATE":"#1f7a4d","INVESTIGATE":"#a36b00","PASS":"#8c3030"}[verdict]
        st.markdown(f'<div class="verdict" style="background:{bg};color:white">{verdict} • DG {score}/100</div>', unsafe_allow_html=True)
        a,b = st.columns(2)
        a.metric("Potential contribution",f"£{contribution:,.0f}")
        b.metric("Maximum buy",f"£{max_buy:,.0f}")
        a,b = st.columns(2)
        a.metric("All-in cost",f"£{all_in:,.0f}")
        b.metric("ROI",f"{roi:.1f}%")
        if asking > max_buy:
            st.warning(f"To retain your £{st.session_state.min_profit:,.0f} target, negotiate about £{asking-max_buy:,.0f} off the asking price.")
        else:
            st.success(f"Asking is £{max_buy-asking:,.0f} inside your target maximum-buy price — subject to inspection and history checks.")

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
        st.success("Saved to DG Deal Finder.")
        if listing.startswith("http"):
            st.link_button("OPEN MARKETPLACE LISTING",listing,use_container_width=True)

        st.markdown("**Before buying**")
        st.write("✓ Verify identity/VIN and seller ownership  \n✓ Check MOT/mileage history  \n✓ Check finance/write-off/theft provenance  \n✓ Inspect cold and road-test  \n✓ Confirm service history, keys, tyres and warning lights  \n✓ Recheck live retail comparables")

st.divider()
st.caption("V2 foundation. This version does not scrape Facebook or automatically value a car. It is designed for fast phone appraisal while you browse Marketplace.")
