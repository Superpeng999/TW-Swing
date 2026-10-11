"""Public read-only TW Swing dashboard; password protected admin action dispatch."""
import csv
import hmac
import io
import os
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title='TW Swing｜台股波段選股', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {max-width:1100px;padding-top:1.5rem;padding-left:1rem;padding-right:1rem}
[data-testid="stMetricValue"] {font-size:1.7rem}
@media(max-width:600px){.block-container{padding-top:1rem}.stButton button{width:100%}}
</style>''',unsafe_allow_html=True)
BASE=Path(__file__).resolve().parent
HEADERS=['執行時間','代號','名稱','集保資料日','法人資料日','大戶占比%','散戶占比%','法人外資5日股數','投信5日股數','大戶連2週','大戶4週上升','散戶2週下降','法人5日正','法人10日正','籌碼分數','階段','資料完整度','說明']

def secret(name):
    try:return str(st.secrets.get(name,'') or '')
    except Exception:return os.environ.get(name,'')

@st.cache_data(ttl=300,show_spinner=False)
def load_csv(name,owner,repo,branch):
    # Remote raw file preferred so periodic GitHub workflow updates appear without app redeployment.
    if owner and repo:
        url=f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/output/{name}'
        try:
            res=requests.get(url,timeout=12,headers={'Cache-Control':'no-cache'})
            if res.status_code==200:
                return pd.read_csv(io.BytesIO(res.content),dtype={'代號':'string','日期':'string','集保資料日':'string','法人資料日':'string'},encoding='utf-8-sig').fillna('')
        except (requests.RequestException,ValueError):pass
    local=BASE/'output'/name
    if local.exists():
        try:return pd.read_csv(local,dtype={'代號':'string'},encoding='utf-8-sig').fillna('')
        except (OSError,ValueError):pass
    return pd.DataFrame()

owner=secret('GITHUB_OWNER');repo=secret('GITHUB_REPO');branch=secret('GITHUB_BRANCH') or 'main'
st.title('📈 TW Swing')
st.caption('台股 2–8 週波段選股｜公開唯讀看板・資料非即時報價・非投資建議')
latest=load_csv('latest_scores.csv',owner,repo,branch)
logs=load_csv('run_log.csv',owner,repo,branch)
history=load_csv('score_history.csv',owner,repo,branch)

pub, hist, about, admin=st.tabs(['📋 選股總覽','📊 歷史評分','ℹ️ 來源與限制','🔐 管理者'])
with pub:
    if latest.empty:
        st.warning('尚無正式資料。管理者完成首次更新後會顯示資料；此頁不使用假股票與假分數。')
    else:
        latest['代號']=latest['代號'].astype(str).str.replace(r'\.0$','',regex=True).str.zfill(4)
        known=latest[latest['資料完整度'].eq('完整')]
        a,b,c,d=st.columns(4)
        a.metric('股票總數',len(latest));b.metric('籌碼資料完整',len(known))
        c.metric('仔細分析',int((latest['階段']=='仔細分析').sum()))
        d.metric('準備下手',int((latest['階段']=='準備下手').sum()))
        run_time=str(latest['執行時間'].max()) if '執行時間' in latest else '未知'
        st.caption(f'最新評分執行時間：{run_time}（執行環境時間；不同資料來源日期請見表格）')
        st.info('目前是「籌碼候選名單」：缺少完整營收與技術資料時，不會自動將股票列為「準備下手」。')
        stage=st.selectbox('檢視階段',['全部','開始關注','仔細分析','準備下手','資料不足'])
        keyword=st.text_input('搜尋股票代號／名稱',placeholder='例如 2330')
        view=latest.copy()
        if stage!='全部':view=view[view['階段'].eq(stage)]
        if keyword.strip():view=view[view['代號'].str.contains(keyword.strip(),regex=False,na=False)|view['名稱'].astype(str).str.contains(keyword.strip(),regex=False,na=False)]
        view['籌碼分數數值']=pd.to_numeric(view['籌碼分數'],errors='coerce')
        view=view.sort_values('籌碼分數數值',ascending=False,na_position='last')
        cols=['代號','名稱','階段','籌碼分數','大戶占比%','散戶占比%','法人外資5日股數','投信5日股數','集保資料日','法人資料日','資料完整度','說明']
        st.dataframe(view[[x for x in cols if x in view]],hide_index=True,use_container_width=True)
        st.download_button('下載目前篩選 CSV',view[[x for x in cols if x in view]].to_csv(index=False).encode('utf-8-sig'),file_name='tw_swing_selection.csv',mime='text/csv')
        st.caption('註：法人買賣超欄位單位為「股」，非「張」；大戶級距是集保級距代理，非實際受益人識別。')
    if not logs.empty:
        st.subheader('最近更新紀錄')
        st.dataframe(logs.head(5),hide_index=True,use_container_width=True)
with hist:
    if history.empty:
        st.info('尚無歷史紀錄。系統完成更新後會保留每次評分快照。')
    else:
        code=st.text_input('查詢個股歷史代號',placeholder='例如 2330',key='hist_code')
        hh=history.copy()
        if code.strip():hh=hh[hh['代號'].astype(str).str.replace(r'\.0$','',regex=True).str.zfill(4).eq(code.strip())]
        hh=hh.sort_values('執行時間',ascending=False)
        st.dataframe(hh.head(300),hide_index=True,use_container_width=True)
        if code.strip() and not hh.empty:
            chart=hh.copy();chart['籌碼分數']=pd.to_numeric(chart['籌碼分數'],errors='coerce')
            chart=chart.dropna(subset=['籌碼分數']).sort_values('執行時間')
            if not chart.empty:st.line_chart(chart.set_index('執行時間')['籌碼分數'])
with about:
    st.markdown('''**資料來源**：臺灣集保結算所（TDCC）持股級距、臺灣證券交易所（TWSE）上市三大法人日報。上櫃 TPEX 全自動接入、月營收、技術條件及主力分點尚未完成。\n\n**資料限制**：官方公開日期與本系統擷取日期可能不同；資料不足則不評分。大戶持股以級距推估，並非「單一大戶」身分。籌碼評分不等於買進建議。\n\n**資料使用與風險**：公開分享前，管理者應依官方資料之重製、再利用及散布條款確認授權；不可揭露個人登入資訊、GitHub 金鑰或資料庫憑證。''')
    st.markdown('- [TDCC OpenAPI](https://openapi.tdcc.com.tw/)\n- [TWSE 法人日報](https://www.twse.com.tw/zh/trading/foreign/t86.html)')
with admin:
    st.write('只有管理者驗證成功後才能觸發更新。公眾頁面沒有寫入權限。')
    pw=secret('ADMIN_PASSWORD');token=secret('GITHUB_PAT')
    if not pw or not token or not owner or not repo:
        st.warning('尚未在 Streamlit Secrets 完成管理者設定。公開資料仍可瀏覽，但更新功能停用。')
    else:
        password=st.text_input('管理者密碼',type='password')
        authenticated=bool(password) and hmac.compare_digest(password.encode(),pw.encode())
        if authenticated:
            st.success('已驗證。以下更新將由 GitHub Actions 在雲端執行。')
            if st.button('執行官方資料更新',type='primary'):
                endpoint=f'https://api.github.com/repos/{owner}/{repo}/actions/workflows/update.yml/dispatches'
                try:
                    res=requests.post(endpoint,headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},json={'ref':branch},timeout=15)
                    if res.status_code==204:st.success('更新工作已送出。等待 GitHub Actions 完成後，約數分鐘即可刷新報表。')
                    else:st.error(f'更新要求失敗，GitHub 狀態碼 {res.status_code}。請確認 token 的 Actions 寫入權限。')
                except requests.RequestException:st.error('GitHub API 連線失敗，稍後再試。')
            st.link_button('查看更新工作進度',f'https://github.com/{owner}/{repo}/actions/workflows/update.yml')
            if st.button('重新讀取資料'):load_csv.clear();st.rerun()
        elif password:st.error('密碼不正確')
        else:st.caption('管理者登入後可送出工作；不會在網頁端執行長時間資料抓取。')
