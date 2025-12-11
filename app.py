import streamlit as st
import pandas as pd
import datetime
import io
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate, formataddr
from email.header import Header
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 定数設定 ---
PRIORITY_OPTIONS = ["高", "中", "低"]
STATUS_OPTIONS = ["未対応", "進行中", "完了"]
SHEET_NAME = "task_db"

# --- Google Sheets 認証 ---
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# --- データロード・保存 ---
def load_data():
    try:
        client = get_gspread_client()
        sheet = client.open(SHEET_NAME).sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        if df.empty:
            df = pd.DataFrame(columns=["削除", "タイトル", "詳細", "優先度", "依頼者", "担当者1", "担当者2", "担当者3", "進捗", "期限", "完了日", "備考"])

        # 必須カラム確保
        req_cols = ["削除", "タイトル", "詳細", "優先度", "依頼者", "担当者1", "担当者2", "担当者3", "進捗", "期限", "完了日", "備考"]
        for c in req_cols:
            if c not in df.columns: df[c] = ""

        df['削除'] = df['削除'].apply(lambda x: True if str(x).upper() == 'TRUE' else False)

        def parse_date(x):
            if not x or str(x).strip() == "": return None
            try: return pd.to_datetime(x).date()
            except: return None

        df['期限'] = df['期限'].apply(parse_date)
        df['完了日'] = df['完了日'].apply(parse_date)

        text_cols = ["タイトル", "詳細", "依頼者", "担当者1", "担当者2", "担当者3", "備考"]
        for c in text_cols: df[c] = df[c].fillna("").astype(str)

        return df
    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")
        return pd.DataFrame()

def save_data(df):
    try:
        client = get_gspread_client()
        sheet = client.open(SHEET_NAME).sheet1
        save_df = df.copy()
        
        for c in ['期限', '完了日']:
            save_df[c] = save_df[c].apply(lambda x: x.strftime('%Y-%m-%d') if x is not None and pd.notnull(x) else "")
        
        save_df['削除'] = save_df['削除'].apply(lambda x: "TRUE" if x else "FALSE")
        
        # 入力規則用バッチクリア＆更新
        sheet.batch_clear(["A2:L1000"])
        data = save_df.values.tolist()
        if len(data) > 0:
            sheet.update(range_name='A2', values=data)
            
        # プルダウン設定（簡易版）
        set_validation(sheet)
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

def set_validation(sheet):
    # H列(優先度:index7), I列(進捗:index8)
    requests = [
        {
            "setDataValidation": {
                "range": {"sheetId": sheet.id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 7, "endColumnIndex": 8},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in PRIORITY_OPTIONS]}, "showCustomUi": True}
            }
        },
        {
            "setDataValidation": {
                "range": {"sheetId": sheet.id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 8, "endColumnIndex": 9},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in STATUS_OPTIONS]}, "showCustomUi": True}
            }
        }
    ]
    try: sheet.batch_update({"requests": requests})
    except: pass

def send_gmail(subject, body, to_email, to_name, from_email, from_name, app_password):
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = formataddr((Header(from_name, 'utf-8').encode(), from_email))
        msg['To'] = formataddr((Header(to_name, 'utf-8').encode(), to_email))
        msg['Date'] = formatdate()
        
        smtp = smtplib.SMTP('smtp.gmail.com', 587)
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(from_email, app_password)
        smtp.sendmail(from_email, to_email, msg.as_string())
        smtp.close()
        return True
    except Exception as e:
        st.error(f"送信エラー: {e}")
        return False

def ensure_date_columns(df):
    for c in ['期限', '完了日']:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors='coerce').apply(lambda x: x.date() if pd.notnull(x) else None)
    return df

# --- UI構築 ---
st.set_page_config(layout="wide", page_title="社内タスク管理システム", page_icon="📝")

if 'tasks_df' not in st.session_state:
    st.session_state.tasks_df = ensure_date_columns(load_data())
if 'editing_task' not in st.session_state: st.session_state.editing_task = None
if 'edit_index' not in st.session_state: st.session_state.edit_index = None

# リロード時再チェック
st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)

# 通知ロジック
today = datetime.date.today()
df_alert = st.session_state.tasks_df.copy()
try:
    # 日付比較エラー対策
    due_ts = pd.to_datetime(df_alert['期限'], errors='coerce')
    is_expired = due_ts < pd.Timestamp(today)
    alert_rows = df_alert[(df_alert['進捗'] != '完了') & (is_expired | (df_alert['優先度'] == '高'))]
    alert_count = len(alert_rows)
except:
    alert_count = 0

col_t, col_a = st.columns([1, 2])
with col_t: st.title("📝 社内タスク管理")
with col_a:
    if alert_count > 0:
        st.markdown(f"<h3 style='color:red'>⚠️ 未完了・期限切れ: {alert_count}件</h3>", unsafe_allow_html=True)

# サイドバー（Secretsから自動入力）
with st.sidebar:
    st.header("📧 通知設定")
    # Secretsから初期値を取得
    def_user = st.secrets["gmail"]["user_email"] if "gmail" in st.secrets else ""
    def_pass = st.secrets["gmail"]["app_password"] if "gmail" in st.secrets else ""
    def_name = st.secrets["gmail"]["user_name"] if "gmail" in st.secrets else "タスク管理Bot"
    
    gmail_user = st.text_input("送信元Gmail", value=def_user)
    gmail_name = st.text_input("送信元名", value=def_name)
    gmail_pass = st.text_input("アプリパスワード", value=def_pass, type="password")
    
    st.markdown("---")
    target_email = st.text_input("送信先メール")
    target_name = st.text_input("宛名 (〇〇様)")
    
    if st.button("📩 通知送信"):
        if alert_count > 0 and gmail_user and gmail_pass and target_email:
            body = f"{target_name}\n\n未完了タスクのお知らせです。\n\n"
            for _, r in alert_rows.iterrows():
                assignees = f"{r.get('担当者1','')} {r.get('担当者2','')} {r.get('担当者3','')}"
                body += f"・{r['タイトル']}\n  期限:{r['期限']} / 担当:{assignees}\n  優先度:{r['優先度']} / 進捗:{r['進捗']}\n\n"
            if send_gmail("【タスク通知】未完了案件", body, target_email, target_name, gmail_user, gmail_name, gmail_pass):
                st.success("送信しました")
        else:
            st.error("設定不足または対象タスクがありません")

# --- タスク登録フォーム (順番整理済み) ---
with st.expander(f"**タスク登録 / 編集**", expanded=True):
    task = st.session_state.editing_task if st.session_state.editing_task else {}
    c1, c2 = st.columns(2)
    
    with c1:
        # 1. タイトル
        title = st.text_input("①タイトル", value=task.get("タイトル", ""))
        # 3. 詳細
        details = st.text_area("②詳細", value=task.get("詳細", ""), height=100)
        # 4. 優先度
        priority = st.selectbox("③優先度", PRIORITY_OPTIONS, index=PRIORITY_OPTIONS.index(task.get("優先度", "高")))
        # 5. 依頼者
        last_req = st.session_state.tasks_df["依頼者"].iloc[-1] if not st.session_state.tasks_df.empty else ""
        requester = st.text_input("④依頼者", value=task.get("依頼者", last_req))

    with c2:
        # 5. 担当者
        st.write("⑤担当者")
        ac1, ac2, ac3 = st.columns(3)
        as1 = ac1.text_input("担当1", task.get("担当者1",""), label_visibility="collapsed", placeholder="担当1")
        as2 = ac2.text_input("担当2", task.get("担当者2",""), label_visibility="collapsed", placeholder="担当2")
        as3 = ac3.text_input("担当3", task.get("担当者3",""), label_visibility="collapsed", placeholder="担当3")
        
        # 6. 進捗
        status = st.selectbox("⑥進捗", STATUS_OPTIONS, index=STATUS_OPTIONS.index(task.get("進捗", "未対応")))
        
        # 7. 期限 & 8. 完了日 (復活)
        dc1, dc2 = st.columns(2)
        def_due = task.get("期限") if isinstance(task.get("期限"), datetime.date) else datetime.date.today() + datetime.timedelta(days=7)
        due_date = dc1.date_input("⑦期限", value=def_due)
        
        def_comp = task.get("完了日") if isinstance(task.get("完了日"), datetime.date) else (datetime.date.today() if status=="完了" else None)
        completion_date = dc2.date_input("⑧完了日", value=def_comp)

        # 9. 備考
        remarks = st.text_area("⑨備考", value=task.get("備考", ""))

    if st.button("登録・更新", type="primary"):
        if not title:
            st.error("タイトルは必須です")
        else:
            new_data = {
                "削除": False, "タイトル": title, "詳細": details, "優先度": priority, "依頼者": requester,
                "担当者1": as1, "担当者2": as2, "担当者3": as3, "進捗": status,
                "期限": due_date, "完了日": completion_date if completion_date and status=="完了" else None, "備考": remarks
            }
            if st.session_state.edit_index is not None:
                st.session_state.tasks_df.loc[st.session_state.edit_index] = new_data
                st.session_state.editing_task = None
                st.session_state.edit_index = None
                st.success("更新しました")
            else:
                st.session_state.tasks_df = pd.concat([st.session_state.tasks_df, pd.DataFrame([new_data])], ignore_index=True)
                st.success("登録しました")
            
            st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)
            save_data(st.session_state.tasks_df)
            st.rerun()
            
    if st.session_state.editing_task and st.button("キャンセル"):
        st.session_state.editing_task = None
        st.session_state.edit_index = None
        st.rerun()

st.markdown("---")

# --- フィルター & 一覧 (復活) ---
with st.expander("🔎 フィルター"):
    fc1, fc2, fc3 = st.columns(3)
    f_pri = fc1.multiselect("優先度", PRIORITY_OPTIONS)
    all_ass = pd.unique(st.session_state.tasks_df[['担当者1','担当者2','担当者3']].astype(str).values.ravel('K'))
    f_ass = fc2.multiselect("担当者", [x for x in all_ass if x and x!="nan"])
    f_key = fc3.text_input("検索")

df_view = st.session_state.tasks_df.copy()
if f_pri: df_view = df_view[df_view['優先度'].isin(f_pri)]
if f_ass: df_view = df_view[df_view['担当者1'].isin(f_ass) | df_view['担当者2'].isin(f_ass) | df_view['担当者3'].isin(f_ass)]
if f_key: df_view = df_view[df_view['タイトル'].str.contains(f_key, na=False)]

# 分割
df_active = df_view[df_view['進捗'] != '完了'].copy()
df_completed = df_view[df_view['進捗'] == '完了'].copy()

# カラム設定
col_cfg = {
    "削除": st.column_config.CheckboxColumn(width="small"),
    "期限": st.column_config.DateColumn(format="YYYY-MM-DD"),
    "完了日": st.column_config.DateColumn(format="YYYY-MM-DD"),
    "優先度": st.column_config.SelectboxColumn(options=PRIORITY_OPTIONS),
    "進捗": st.column_config.SelectboxColumn(options=STATUS_OPTIONS)
}
col_ord = ["削除","タイトル","詳細","依頼者","担当者1","担当者2","担当者3","優先度","進捗","期限","完了日","備考"]

st.subheader("🔥 未完了タスク")
df_active = ensure_date_columns(df_active)
ed_act = st.data_editor(df_active, column_config=col_cfg, column_order=col_ord, hide_index=True, key="act", num_rows="dynamic")

if st.session_state.act.get("edited_rows"):
    for idx, chg in st.session_state.act["edited_rows"].items():
        real_idx = df_active.index[idx]
        for c, v in chg.items(): st.session_state.tasks_df.at[real_idx, c] = v
    st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)
    save_data(st.session_state.tasks_df)
    st.rerun()

if st.button("🗑️ 削除 (未完了)"):
    idx = st.session_state.tasks_df[st.session_state.tasks_df['削除']].index
    if len(idx)>0:
        st.session_state.tasks_df.drop(idx, inplace=True)
        st.session_state.tasks_df.reset_index(drop=True, inplace=True)
        save_data(st.session_state.tasks_df)
        st.rerun()

st.markdown("---")

st.subheader("✅ 完了済みタスク")
df_completed = ensure_date_columns(df_completed)
ed_comp = st.data_editor(df_completed, column_config=col_cfg, column_order=col_ord, hide_index=True, key="comp")

if st.session_state.comp.get("edited_rows"):
    for idx, chg in st.session_state.comp["edited_rows"].items():
        real_idx = df_completed.index[idx]
        for c, v in chg.items(): st.session_state.tasks_df.at[real_idx, c] = v
    st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)
    save_data(st.session_state.tasks_df)
    st.rerun()
