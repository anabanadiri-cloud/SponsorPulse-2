from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title='SponsorPulse 2.0 | PE Intelligence',page_icon='📊',layout='wide')
st.markdown('''<style>
.stApp {background:#071321;color:#eef5ff}
.block-container{padding-top:1.6rem;max-width:1350px}
h1,h2,h3{color:#f3f7ff!important}
[data-testid="stMetric"]{background:#10213a;border:1px solid #203b5b;border-radius:14px;padding:18px}
[data-testid="stMetricLabel"]{color:#b4c4d8}
[data-testid="stMetricValue"]{color:#3ce0b6}
section[data-testid="stSidebar"]{background:#0c1b30}
div[data-testid="stAlert"]{border-radius:10px}
</style>''',unsafe_allow_html=True)

@st.cache_data
def load_data():
    df=pd.read_csv(Path(__file__).parent/'deals.csv',keep_default_na=False)
    df['is_verified_deal']=df['is_verified_deal'].astype(str).str.lower().eq('true')
    df['deal_value_disclosed']=df['deal_value_disclosed'].astype(str).str.lower().eq('true')
    # Recompute classifications from original transaction labels.
    def direction(row):
        if not row['is_verified_deal']:return 'OTHER / NON-DEAL'
        if row['transaction_type'] in ('Platform Investment','Add-On Acquisition'):return 'BUY / INVESTMENT'
        if row['transaction_type']=='Full Exit / Sale':return 'SELL / EXIT'
        return 'REVIEW REQUIRED'
    df['deal_direction']=df.apply(direction,axis=1)
    return df

df=load_data()
# Convert announcement dates into years
df["year"] = pd.to_datetime(
    df["announcement_date"],
    errors="coerce"
).dt.year
st.markdown('### 📈 Sponsor<span style="color:#38bdf8">Pulse</span>  ·  INSTITUTIONAL EDITION',unsafe_allow_html=True)
st.caption('Target Sponsor: Norwest Equity Partners (NEP) · FINC 314 project')
st.title('Private Equity Deal Sourcing & Operational Intelligence')
st.write('Separate investments from exits, filter corporate PR noise, and review the source evidence behind each classification.')
st.warning('**Sample / offline mode:** This dashboard uses the eight fallback announcement records bundled with the Colab notebook. It is **not a live scraper**. Transaction labels and source URLs require independent verification before investment use.',icon='⚠️')

with st.sidebar:
    st.header('Explore announcements')
        # Filter announcements by year
    available_years = sorted(
        df["year"].dropna().astype(int).unique(),
        reverse=True
    )

    selected_years = st.multiselect(
        "Announcement Year",
        available_years,
        default=[2026] if 2026 in available_years else available_years
    )
    direction=st.multiselect('Investment direction',sorted(df['deal_direction'].unique()),default=sorted(df['deal_direction'].unique()))
    types=st.multiselect('Transaction type',sorted(df['transaction_type'].unique()),default=sorted(df['transaction_type'].unique()))
    query=st.text_input('Search company, headline, buyer or industry',placeholder='E-Z UP, Thibaut, Consumer…')
    only_deals=st.checkbox('Verified deals only (model classification)',value=False)

filtered=df[df['deal_direction'].isin(direction)&df['transaction_type'].isin(types)].copy()
filtered = filtered[
    filtered["year"].isin(selected_years)
]
if only_deals: filtered=filtered[filtered['is_verified_deal']]
if query.strip():
    searchable=filtered[['target_company','headline','buyer_entity','target_industry']].astype(str).agg(' '.join,axis=1)
    filtered=filtered[searchable.str.contains(query.strip(),case=False,regex=False)]

c1,c2,c3,c4=st.columns(4)
c1.metric('RAW POSTS',len(filtered))
c2.metric('BUY / INVESTMENT',int((filtered['deal_direction']=='BUY / INVESTMENT').sum()))
c3.metric('SELL / EXIT',int((filtered['deal_direction']=='SELL / EXIT').sum()))
c4.metric('NON-DEAL / PR',int((filtered['deal_direction']=='OTHER / NON-DEAL').sum()))

left,right=st.columns(2)
with left:
    st.subheader('Investment Direction Tracker')
    order=['BUY / INVESTMENT','SELL / EXIT','OTHER / NON-DEAL','REVIEW REQUIRED']
    counts=filtered['deal_direction'].value_counts().reindex(order,fill_value=0).reset_index()
    counts.columns=['Direction','Announcements']
    counts=counts[counts['Announcements']>0]
    if len(counts):
        fig=px.bar(counts,x='Direction',y='Announcements',color='Direction',text='Announcements',color_discrete_map={'BUY / INVESTMENT':'#10b981','SELL / EXIT':'#fb7185','OTHER / NON-DEAL':'#64748b','REVIEW REQUIRED':'#f59e0b'})
        fig.update_layout(showlegend=False,plot_bgcolor='#10213a',paper_bgcolor='#10213a',font_color='#e2e8f0',margin=dict(l=10,r=10,t=20,b=20),height=340)
        fig.update_yaxes(dtick=1,gridcolor='#28405c')
        st.plotly_chart(fig,use_container_width=True)
    else: st.info('No announcements match your filters.')
with right:
    st.subheader('Transaction Type Breakdown')
    type_counts=filtered['transaction_type'].value_counts().reset_index()
    type_counts.columns=['Type','Count']
    if len(type_counts):
        fig=px.pie(type_counts,names='Type',values='Count',hole=.65,color_discrete_sequence=['#38bdf8','#818cf8','#10b981','#c084fc','#64748b'])
        fig.update_layout(paper_bgcolor='#10213a',font_color='#e2e8f0',margin=dict(l=10,r=10,t=20,b=20),height=340)
        st.plotly_chart(fig,use_container_width=True)
    else: st.info('No announcements match your filters.')

st.subheader('Deal Activity Report')
buys=filtered[filtered['deal_direction']=='BUY / INVESTMENT']
sells=filtered[filtered['deal_direction']=='SELL / EXIT']
buy_tab,sell_tab=st.tabs([f'🟢 Investments ({len(buys)})',f'🔴 Exits ({len(sells)})'])
cols=['target_company','buyer_entity','transaction_type','target_industry','announcement_date','url']
with buy_tab: st.dataframe(buys[cols],hide_index=True,use_container_width=True)
with sell_tab: st.dataframe(sells[cols],hide_index=True,use_container_width=True)

st.subheader('Announcement Evidence Explorer')
st.caption('Click source URLs to review announcements. “Verified deal” reflects the notebook’s rule-based classification, not external fact-checking.')
view_cols=['announcement_date','headline','deal_direction','transaction_type','target_company','buyer_entity','target_industry','strategic_rationale','evidence_snippet','url']
st.dataframe(filtered[view_cols],hide_index=True,use_container_width=True,column_config={'url':st.column_config.LinkColumn('Original announcement')})
st.download_button('⬇ Export filtered master CSV',filtered.to_csv(index=False).encode('utf-8'),file_name='sponsorpulse_filtered.csv',mime='text/csv')
with st.expander('Methodology & limitations'):
    st.markdown('''- **BUY / INVESTMENT:** Platform Investment or Add-On Acquisition. An add-on can be acquired by a portfolio company rather than directly by NEP.\n- **SELL / EXIT:** Full Exit / Sale.\n- **OTHER / NON-DEAL:** Personnel updates and fund closings, excluded from transaction counts.\n- **REVIEW REQUIRED:** Any other classified transaction, which should not be automatically called a buy or sell.\n- **Evidence:** The notebook uses rule-based parsing and a bundled fallback sample. A headline or cached body is not proof of closing or terms.\n- **No live data claim:** To refresh, run and verify the notebook pipeline, then replace `deals.csv` and redeploy.''')
