"""Build Excel dashboard using artifact_tool. Run after pipeline.py."""
import csv
from pathlib import Path
from artifact_tool import Workbook,SpreadsheetFile
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output';OUT.mkdir(exist_ok=True)
wb=Workbook.create()
navy='#16283F';blue='#EAF2FA';green='#D9F0E4';yellow='#FFF2CD';gray='#F0F3F7'

def read(name,limit=3000):
    f=OUT/name
    if not f.exists():return []
    with f.open(encoding='utf-8-sig',newline='') as h:return list(csv.reader(h))[:limit]

def make(name,description,header,rows,widths=None):
    s=wb.worksheets.add(name)
    n=max(6,len(header))
    s.merge_cells(f'A1:{col(n)}1');s.get_range('A1').values=[[name+'｜TW Swing 2–8W']]
    s.get_range(f'A1:{col(n)}1').format={'fill':navy,'font':{'bold':True,'color':'#FFFFFF','size':16},'row_height':32}
    s.merge_cells(f'A2:{col(n)}2');s.get_range('A2').values=[[description]]
    s.get_range(f'A2:{col(n)}2').format={'fill':blue,'font':{'color':'#35506C','size':10},'row_height':28}
    s.get_range_by_indexes(3,0,1,len(header)).values=[header]
    s.get_range_by_indexes(3,0,1,len(header)).format={'fill':'#2F526F','font':{'color':'#FFFFFF','bold':True},'row_height':26,'wrap_text':True}
    if rows:
        nrows=min(len(rows),2500)
        s.get_range_by_indexes(4,0,nrows,len(header)).values=[list(x)+[None]*(len(header)-len(x)) for x in rows[:nrows]]
    for i in range(len(header)):
        s.get_range_by_indexes(0,i,max(7,len(rows)+5),1).format.column_width=(widths[i] if widths and i<len(widths) else 16)
    s.freeze_panes.freeze_rows(4)
    return s

def col(n):
    z=''
    while n:n,r=divmod(n-1,26);z=chr(65+r)+z
    return z

latest=read('latest_scores.csv');hist=read('score_history.csv',1800);inst=read('institutions_history.csv',1500);tdcc=read('tdcc_history.csv',1000);logs=read('run_log.csv',200)
headers=latest[0] if latest else ['執行時間','代號','名稱','集保資料日','法人資料日','大戶占比%','散戶占比%','法人外資5日股數','投信5日股數','大戶連2週','大戶4週上升','散戶2週下降','法人5日正','法人10日正','籌碼分數','階段','資料完整度','說明']
latestrows=latest[1:] if latest else []
make('籌碼最新','原始最新評分資料；缺少 5 次集保週資料或 10 個法人交易日時不給綜合分數。',headers,latestrows,[18,13,20,16,16,17,17,19,18,14,14,14,14,14,13,16,15,46])
# Data-less template remains explicit: no illustrative securities passed off as live.
dash=wb.worksheets.add('Dashboard')
dash.merge_cells('A1:J1');dash.get_range('A1').values=[['TW SWING 2–8W｜台股三級選股總覽']]
dash.get_range('A1:J1').format={'fill':navy,'font':{'bold':True,'color':'#FFFFFF','size':17},'row_height':38}
dash.merge_cells('A2:J2');dash.get_range('A2').values=[['資料由 pipeline.py 更新｜只以完整籌碼資料評分；營收與技術條件須另行確認']]
dash.get_range('A2:J2').format={'fill':blue,'font':{'color':'#36516F'},'row_height':28}
dash.get_range('A4:E4').values=[['已匯入股票','資料完整','開始關注','仔細分析','準備下手']]
dash.get_range('A4:E4').format={'fill':'#2F526F','font':{'color':'#FFFFFF','bold':True}}
dash.get_range('A5:E5').formulas=[['=COUNTA(籌碼最新!B5:B2504)','=COUNTIF(籌碼最新!Q5:Q2504,"完整")','=COUNTIF(籌碼最新!P5:P2504,"開始關注")','=COUNTIF(籌碼最新!P5:P2504,"仔細分析")','=COUNTIF(籌碼最新!P5:P2504,"準備下手")']]
dash.get_range('A5:E5').format={'fill':gray,'font':{'bold':True,'size':19},'row_height':34}
dash.get_range('A7:J7').values=[['代號','名稱','階段','籌碼分數','大戶持股%','散戶持股%','外資5日(股)','投信5日(股)','資料完整度','追蹤註記']]
dash.get_range('A7:J7').format={'fill':'#2F526F','font':{'bold':True,'color':'#FFFFFF'},'wrap_text':True,'row_height':30}
ranked=sorted(latestrows,key=lambda r:(r[16]!='完整',-float(r[14]) if r[14] else 1e6,r[1]))[:60]
if ranked:
    dash.get_range_by_indexes(7,0,len(ranked),10).values=[[r[1],r[2],r[15],float(r[14]) if r[14] else None,float(r[5]) if r[5] else None,float(r[6]) if r[6] else None,float(r[7]) if r[7] else None,float(r[8]) if r[8] else None,r[16],r[17]] for r in ranked]
for i,w in enumerate([14,19,16,14,16,16,19,19,16,40]):dash.get_range_by_indexes(0,i,80,1).format.column_width=w
dash.freeze_panes.freeze_rows(7)
for label,target in [('開始關注','開始關注'),('仔細分析','仔細分析'),('準備下手','準備下手')]:
    subset=[r for r in ranked if r[15]==target]
    sh=make(label,'本表是籌碼評分階段；「準備下手」需人工核准營收、技術型態、進出場計畫，不會由籌碼單獨晉級。',['代號','名稱','籌碼分數','大戶占比%','散戶占比%','外資5日股數','投信5日股數','最新集保日','最新法人日','原因'],[[r[1],r[2],float(r[14]) if r[14] else None,r[5],r[6],r[7],r[8],r[3],r[4],r[17]] for r in subset],[13,21,16,17,17,20,20,17,17,45])
    if label=='準備下手':sh.get_range('A5').values=[['目前不自動晉級；需補齊技術／營收／風控確認']]
make('評分歷史','每次執行保留快照，同日重跑仍可保留不同時間資料。',hist[0] if hist else ['執行時間','代號','籌碼分數','階段','資料完整度','大戶占比%','散戶占比%','外資5日','投信5日','說明'],hist[1:] if hist else [],[22,14,14,16,16,17,17,18,18,45])
make('法人歷史','官方上市證交所 TWSE；上櫃需另外手動匯入官方 TPEx 正規化 CSV。',inst[0] if inst else ['日期','代號','市場','名稱','外資淨買股數','投信淨買股數','來源','匯入時間'],inst[1:] if inst else [],[16,13,13,20,22,22,48,22])
make('集保歷史','持股級距：12–15 定義為本系統大戶代理指標；1–5 定義為散戶代理指標。',tdcc[0] if tdcc else ['日期','代號','級距','人數','股數','比例%','來源','匯入時間'],tdcc[1:] if tdcc else [],[16,13,11,15,22,15,49,22])
make('更新紀錄','資料供應商改版或抓取失敗時記錄錯誤，不用空白填成零。',logs[0] if logs else ['執行時間','集保筆數','法人筆數','錯誤或附註'],logs[1:] if logs else [],[24,20,20,100])
config=[['設定','目前值','說明'],['大戶級距','12–15','以持股級距代理，非確定之單一大戶'],['散戶級距','1–5','以集保戶持股級距代理'],['大戶連增','2 週','須有 3 期週資料'],['大戶4週上升','是','須有 5 期週資料'],['法人5日買超','外資+投信>0','買賣超股數，非強度比例'],['法人10日買超','外資+投信>0','須有 10 個交易日'],['籌碼晉級','70 分','僅晉級「仔細分析」'],['準備下手','需技術及營收核准','禁止籌碼資料單獨通過'],['資料來源 TDCC','https://openapi.tdcc.com.tw/v1/opendata/1-5','官方每週快照'],['資料來源 TWSE','https://www.twse.com.tw/rwd/zh/fund/T86','官方上市法人資料'],['上櫃資料','https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/3itrade/day.html','V1 需人工匯出後正規化'],['交易資料','無','尚未接入成交價及量，不能宣稱完整選股'],['營收資料','無','尚未接入 MOPS，Excel 僅是籌碼階段'],['主力分點','無','未取得授權資料，不能計分']]
make('設定與來源','分數由 pipeline.py 計算；修改權重需編輯 SCORE_WEIGHTS 並重新執行。',config[0],config[1:],[26,53,60])
SpreadsheetFile.export_xlsx(wb).save(str(ROOT/'TW_Swing_Dashboard.xlsx'))
print('Exported',ROOT/'TW_Swing_Dashboard.xlsx')
