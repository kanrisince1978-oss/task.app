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

# ★ここにあなたのアプリのURLを貼り付けてください（メールの末尾に記載されます）
APP_URL = "https://taskapp-vjdepqj8lk3fmd5sy9amsx.streamlit.app/" 

# スプレッドシートの列順序定義
SPREADSHEET_ORDER = [
    "タイトル", "詳細", "依頼者", 
    "担当者1", "担当者2", "担当者3", 
    "優先度", "進捗", "期限", "完了日", "備考"
]

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
            df = pd.DataFrame(columns=SPREADSHEET_ORDER)

        for c in SPREADSHEET_ORDER:
            if c not in df.columns: df[c] = ""

        if "削除" in df.columns: df = df.drop(columns=["削除"])
        if "通知" in df.columns: df = df.drop(columns=["通知"])
            
        # アプリ操作用列の追加
        df.insert(0, "通知", False)
        df.insert(1, "削除", False)

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
        cols_with_app = ["通知", "削除"] + SPREADSHEET_ORDER
        return pd.DataFrame(columns=cols_with_app)

def save_data(df):
    try:
        client = get_gspread_client()
        sheet = client.open(SHEET_NAME).sheet1
        
        save_df = df.copy()
        
        if "通知" in save_df.columns: save_df = save_df.drop(columns=["通知"])
        if "削除" in save_df.columns: save_df = save_df.drop(columns=["削除"])

        for c in ['期限', '完了日']:
            save_df[c] = save_df[c].apply(lambda x: x.strftime('%Y-%m-%d') if x is not None and pd.notnull(x) else "")
        
        save_df = save_df.reindex(columns=SPREADSHEET_ORDER)
        
        sheet.batch_clear(["A2:K1000"])
        data = save_df.values.tolist()
        if len(data) > 0:
            sheet.update(range_name='A2', values=data)
            
        set_validation(sheet)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

def set_validation(sheet):
    requests = [
        {
            "setDataValidation": {
                "range": {"sheetId": sheet.id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 6, "endColumnIndex": 7},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in PRIORITY_OPTIONS]}, "showCustomUi": True}
            }
        },
        {
            "setDataValidation": {
                "range": {"sheetId": sheet.id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 7, "endColumnIndex": 8},
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

cols_check = set(["通知", "削除"] + SPREADSHEET_ORDER)
if set(st.session_state.tasks_df.columns) != cols_check:
    st.cache_data.clear()
    st.session_state.tasks_df = ensure_date_columns(load_data())

if 'editing_task' not in st.session_state: st.session_state.editing_task = None
if 'edit_index' not in st.session_state: st.session_state.edit_index = None

st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)

today = datetime.date.today()
df_base = st.session_state.tasks_df.copy()

try:
    if '進捗' in df_base.columns and '期限' in df_base.columns:
        due_ts = pd.to_datetime(df_base['期限'], errors='coerce')
        is_expired = due_ts < pd.Timestamp(today)
        alert_rows = df_base[(df_base['進捗'] != '完了') & (is_expired | (df_base['優先度'] == '高'))]
        alert_count = len(alert_rows)
    else:
        alert_count = 0
except:
    alert_count = 0

col_t, col_a = st.columns([1, 2])
with col_t: st.title("📝 社内タスク管理")
with col_a:
    if alert_count > 0:
        st.markdown(f"<h3 style='color:red'>⚠️ 未完了・期限切れ: {alert_count}件</h3>", unsafe_allow_html=True)

# --- サイドバー (通知設定) ---
with st.sidebar:
    st.header("📧 通知設定")
    
    def_user = st.secrets["gmail"]["user_email"] if "gmail" in st.secrets else ""
    gmail_user = st.text_input("送信元Gmail", value=def_user, placeholder="your_email@gmail.com")
    gmail_name = st.text_input("送信元名", value="", placeholder="タスク管理Bot")
    gmail_pass = st.text_input("アプリパスワード", value="", type="password")
    
    st.markdown("---")
    target_email = st.text_input("送信先メール", placeholder="boss@company.com")
    
    all_assignees = []
    if not st.session_state.tasks_df.empty:
        ass_cols = [c for c in ['担当者1','担当者2','担当者3'] if c in st.session_state.tasks_df.columns]
        if ass_cols:
            raw_ass = st.session_state.tasks_df[ass_cols].astype(str).values.ravel('K')
            unique_ass = pd.unique(raw_ass)
            all_assignees = [x for x in unique_ass if x and x.lower() != "nan" and x.lower() != "none"]
    
    target_name = st.selectbox("宛名 (担当者を選択)", options=[""] + sorted(all_assignees))
    
    if st.button("📩 通知送信"):
        if gmail_user and gmail_pass and target_email and target_name:
            checked_rows = df_base[df_base['通知'] == True]
            incomplete_rows = checked_rows[checked_rows['進捗'] != '完了']
            
            target_rows = incomplete_rows[
                (incomplete_rows['担当者1'] == target_name) |
                (incomplete_rows['担当者2'] == target_name) |
                (incomplete_rows['担当者3'] == target_name)
            ]
            
            email_count = len(target_rows)
            
            if email_count > 0:
                body = f"{target_name} 様\n\nお疲れ様です。\n現在残っているタスクのお知らせです。\n\n"
                for _, r in target_rows.iterrows():
                    assignees = f"{r.get('担当者1','')} {r.get('担当者2','')} {r.get('担当者3','')}"
                    body += f"・{r['タイトル']}\n  期限:{r['期限']} / 担当:{assignees}\n  優先度:{r['優先度']} / 進捗:{r['進捗']}\n\n"
                
                # ★URLの追記
                body += "-"*30 + "\n"
                body += f"▼ アプリを開いて確認する\n{APP_URL}\n"

                if send_gmail("【タスク通知】未完了案件一覧", body, target_email, target_name, gmail_user, gmail_name, gmail_pass):
                    st.success(f"{target_name}様のタスク {email_count}件を送信しました")
            else:
                st.warning(f"「{target_name}」様のタスクで、通知チェック(✉️)が入った未完了タスクがありません。")
        else:
            st.error("設定不足です。アドレス、パスワード、宛先（担当者）を選択してください")

# --- タスク登録フォーム ---
with st.expander(f"**タスク登録 / 編集**", expanded=True):
    task = st.session_state.editing_task if st.session_state.editing_task else {}
    c1, c2 = st.columns(2)
    
    with c1:
        title = st.text_input("①タイトル", value=task.get("タイトル", ""))
        details = st.text_area("②詳細", value=task.get("詳細", ""), height=100)
        last_req = st.session_state.tasks_df["依頼者"].iloc[-1] if not st.session_state.tasks_df.empty else ""
        requester = st.text_input("③依頼者", value=task.get("依頼者", last_req))
        
        st.write("④担当者")
        ac1, ac2, ac3 = st.columns(3)
        as1 = ac1.text_input("担当1", task.get("担当者1",""), label_visibility="collapsed", placeholder="担当1")
        as2 = ac2.text_input("担当2", task.get("担当者2",""), label_visibility="collapsed", placeholder="担当2")
        as3 = ac3.text_input("担当3", task.get("担当者3",""), label_visibility="collapsed", placeholder="担当3")

    with c2:
        priority = st.selectbox("⑤優先度", PRIORITY_OPTIONS, index=PRIORITY_OPTIONS.index(task.get("優先度", "高")))
        status = st.selectbox("⑥進捗", STATUS_OPTIONS, index=STATUS_OPTIONS.index(task.get("進捗", "未対応")))
        
        dc1, dc2 = st.columns(2)
        def_due = task.get("期限") if isinstance(task.get("期限"), datetime.date) else datetime.date.today() + datetime.timedelta(days=7)
        due_date = dc1.date_input("⑦期限", value=def_due)
        
        def_comp = task.get("完了日") if isinstance(task.get("完了日"), datetime.date) else (datetime.date.today() if status=="完了" else None)
        completion_date = dc2.date_input("⑧完了日", value=def_comp)

        remarks = st.text_area("⑨備考", value=task.get("備考", ""))

    if st.button("登録・更新", type="primary"):
        if not title:
            st.error("タイトルは必須です")
        else:
            new_data = {
                "削除": False, "通知": False, "タイトル": title, "詳細": details, "依頼者": requester,
                "担当者1": as1, "担当者2": as2, "担当者3": as3, 
                "優先度": priority, "進捗": status,
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

# --- フィルター & 一覧 ---
with st.expander("🔎 フィルター"):
    fc1, fc2, fc3 = st.columns(3)
    f_pri = fc1.multiselect("優先度", PRIORITY_OPTIONS)
    f_ass = fc2.multiselect("担当者", all_assignees)
    f_key = fc3.text_input("検索")

df_view = st.session_state.tasks_df.copy()
if f_pri: df_view = df_view[df_view['優先度'].isin(f_pri)]
if f_ass: df_view = df_view[df_view['担当者1'].isin(f_ass) | df_view['担当者2'].isin(f_ass) | df_view['担当者3'].isin(f_ass)]
if f_key: df_view = df_view[df_view['タイトル'].str.contains(f_key, na=False)]

df_active = df_view[df_view['進捗'] != '完了'].copy()
df_completed = df_view[df_view['進捗'] == '完了'].copy()

col_cfg = {
    "通知": st.column_config.CheckboxColumn(width="small", label="✉️", help="チェックしたタスクをメール通知します"),
    "削除": st.column_config.CheckboxColumn(width="small", label="🗑️"),
    "期限": st.column_config.DateColumn(format="YYYY-MM-DD"),
    "完了日": st.column_config.DateColumn(format="YYYY-MM-DD"),
    "優先度": st.column_config.SelectboxColumn(options=PRIORITY_OPTIONS),
    "進捗": st.column_config.SelectboxColumn(options=STATUS_OPTIONS)
}

# A. 未完了タスク
st.subheader("🔥 未完了タスク")
df_active = ensure_date_columns(df_active)
active_cols = ["通知", "削除", "タイトル", "詳細", "依頼者", "担当者1", "担当者2", "担当者3", "優先度", "進捗", "期限", "完了日", "備考"]

ed_act = st.data_editor(
    df_active, 
    column_config=col_cfg, 
    column_order=active_cols, 
    hide_index=True, 
    key="act", 
    num_rows="dynamic"
)

if st.session_state.act.get("edited_rows"):
    for idx, chg in st.session_state.act["edited_rows"].items():
        real_idx = df_active.index[idx]
        for c, v in chg.items(): st.session_state.tasks_df.at[real_idx, c] = v
    st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)
    save_data(st.session_state.tasks_df)
    st.rerun()

if st.button("🗑️ チェックした行を削除 (未完了)"):
    idx = st.session_state.tasks_df[st.session_state.tasks_df['削除']].index
    if len(idx)>0:
        st.session_state.tasks_df.drop(idx, inplace=True)
        st.session_state.tasks_df.reset_index(drop=True, inplace=True)
        
        if "削除" not in st.session_state.tasks_df.columns:
            st.session_state.tasks_df.insert(1, "削除", False)
        else:
            st.session_state.tasks_df["削除"] = False
            
        if "通知" not in st.session_state.tasks_df.columns:
            st.session_state.tasks_df.insert(0, "通知", False)
        else:
            st.session_state.tasks_df["通知"] = False

        save_data(st.session_state.tasks_df)
        st.rerun()

st.markdown("---")

# B. 完了済みタスク
st.subheader("✅ 完了済みタスク")
df_completed = ensure_date_columns(df_completed)
completed_cols = ["タイトル", "詳細", "依頼者", "担当者1", "担当者2", "担当者3", "優先度", "進捗", "期限", "完了日", "備考"]

ed_comp = st.data_editor(
    df_completed, 
    column_config=col_cfg, 
    column_order=completed_cols, 
    hide_index=True, 
    key="comp"
)

if st.session_state.comp.get("edited_rows"):
    for idx, chg in st.session_state.comp["edited_rows"].items():
        real_idx = df_completed.index[idx]
        for c, v in chg.items(): st.session_state.tasks_df.at[real_idx, c] = v
    st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)
    save_data(st.session_state.tasks_df)
    st.rerun()
