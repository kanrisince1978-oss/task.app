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
SHEET_NAME = "task_db" # スプレッドシートのファイル名

# --- Google Sheets 認証 & 接続設定 ---
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# --- データ操作関数 ---

def load_data():
    """Googleスプレッドシートからデータをロードする"""
    try:
        client = get_gspread_client()
        sheet = client.open(SHEET_NAME).sheet1
        data = sheet.get_all_records()
        
        df = pd.DataFrame(data)
        
        if df.empty:
            df = pd.DataFrame(columns=[
                "削除", "タイトル", "詳細", "依頼者", 
                "担当者1", "担当者2", "担当者3", 
                "優先度", "進捗", "期限", "完了日", "備考"
            ])

        required_cols = [
            "削除", "タイトル", "詳細", "依頼者", 
            "担当者1", "担当者2", "担当者3", 
            "優先度", "進捗", "期限", "完了日", "備考"
        ]
        for col in required_cols:
            if col not in df.columns:
                df[col] = ""

        df['削除'] = df['削除'].apply(lambda x: True if str(x).upper() == 'TRUE' else False)

        def parse_date(x):
            if not x or str(x).strip() == "":
                return None
            try:
                return pd.to_datetime(x).date()
            except:
                return None

        df['期限'] = df['期限'].apply(parse_date)
        df['完了日'] = df['完了日'].apply(parse_date)

        text_cols = ["タイトル", "詳細", "依頼者", "担当者1", "担当者2", "担当者3", "備考"]
        for col in text_cols:
            df[col] = df[col].fillna("").astype(str)

        return df

    except Exception as e:
        st.error(f"スプレッドシート読み込みエラー: {e}")
        return pd.DataFrame(columns=[
            "削除", "タイトル", "詳細", "依頼者", 
            "担当者1", "担当者2", "担当者3", 
            "優先度", "進捗", "期限", "完了日", "備考"
        ])

def set_validation_rules(sheet):
    """プルダウン設定"""
    requests = [
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": 1,
                    "endRowIndex": 1000,
                    "startColumnIndex": 7, # H列
                    "endColumnIndex": 8
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": v} for v in PRIORITY_OPTIONS]
                    },
                    "showCustomUi": True,
                    "strict": True
                }
            }
        },
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": 1,
                    "endRowIndex": 1000,
                    "startColumnIndex": 8, # I列
                    "endColumnIndex": 9
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": v} for v in STATUS_OPTIONS]
                    },
                    "showCustomUi": True,
                    "strict": True
                }
            }
        }
    ]
    sheet.batch_update({"requests": requests})

def save_data(df):
    """保存処理"""
    try:
        client = get_gspread_client()
        sheet = client.open(SHEET_NAME).sheet1
        
        save_df = df.copy()
        
        for col in ['期限', '完了日']:
            save_df[col] = save_df[col].apply(lambda x: x.strftime('%Y-%m-%d') if x is not None and pd.notnull(x) else "")

        save_df['削除'] = save_df['削除'].apply(lambda x: "TRUE" if x else "FALSE")
        
        data_to_write = save_df.values.tolist()
        
        sheet.batch_clear(["A2:L1000"]) 
        if len(data_to_write) > 0:
            sheet.update(range_name=f'A2', values=data_to_write)
        
        try:
            set_validation_rules(sheet)
        except Exception as e:
            print(f"Validation Error: {e}")
            
        return True

    except Exception as e:
        st.error(f"スプレッドシート保存エラー: {e}")
        return False

# --- メール送信関数（名前対応版） ---
def send_gmail(subject, body, to_email, to_name, from_email, from_name, app_password):
    """
    Gmail送信関数 (日本語名対応)
    to_name: 宛名 (例: 鈴木部長)
    from_name: 送信者名 (例: タスク管理Bot)
    """
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        
        # 名前付きのアドレスを作成 ( 例: "タスク管理Bot <sender@gmail.com>" )
        msg['From'] = formataddr((Header(from_name, 'utf-8').encode(), from_email))
        msg['To'] = formataddr((Header(to_name, 'utf-8').encode(), to_email))
        msg['Date'] = formatdate()

        smtpobj = smtplib.SMTP('smtp.gmail.com', 587)
        smtpobj.ehlo()
        smtpobj.starttls()
        smtpobj.ehlo()
        smtpobj.login(from_email, app_password)
        smtpobj.sendmail(from_email, to_email, msg.as_string())
        smtpobj.close()
        return True
    except Exception as e:
        st.error(f"メール送信エラー: {e}")
        return False

# --- 日付型強制変換関数 ---
def ensure_date_columns(df):
    target_cols = ['期限', '完了日']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            df[col] = df[col].apply(lambda x: x.date() if pd.notnull(x) else None)
    return df

# --- UI構築 ---

st.set_page_config(layout="wide", page_title="社内タスク管理システム", page_icon="📝")

# セッション初期化
if 'tasks_df' not in st.session_state:
    loaded_df = load_data()
    st.session_state.tasks_df = ensure_date_columns(loaded_df)

if 'editing_task' not in st.session_state:
    st.session_state.editing_task = None
if 'edit_index' not in st.session_state:
    st.session_state.edit_index = None

# リロード時の型安全対策
st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)

# --- 通知判定ロジック ---
today = datetime.date.today()
df_alert = st.session_state.tasks_df.copy()
incomplete_mask = df_alert['進捗'] != '完了'

temp_due_dates = pd.to_datetime(df_alert['期限'], errors='coerce')
today_timestamp = pd.Timestamp(today)
is_expired = temp_due_dates < today_timestamp

alert_rows = df_alert[
    incomplete_mask & (
        is_expired | 
        ((df_alert['優先度'] == '高'))
    )
]
alert_count = len(alert_rows)

# --- ヘッダー & メール設定 ---
col_title, col_alert = st.columns([1, 2])
with col_title:
    st.title("📝 社内タスク管理")
with col_alert:
    if alert_count > 0:
        st.markdown(f"<h3 style='color: red;'>⚠️ 未完了・期限切れタスク: {alert_count}件</h3>", unsafe_allow_html=True)

with st.sidebar:
    st.header("📧 通知設定 (Gmail)")
    
    st.markdown("#### 送信元設定")
    gmail_user = st.text_input("送信元Gmailアドレス", placeholder="your_email@gmail.com")
    gmail_name = st.text_input("送信元名 (表示名)", placeholder="タスク管理システム", help="メールの差出人名として表示されます")
    gmail_pass = st.text_input("Googleアプリパスワード", type="password", help="Googleアカウント設定で生成した16桁のパスワード")
    
    st.markdown("#### 送信先設定")
    target_email = st.text_input("送信先メールアドレス", placeholder="boss@company.com")
    target_name = st.text_input("送信先名 (宛名)", placeholder="〇〇部長", help="メールの宛名として使用されます")
    
    if st.button("📩 今すぐ通知を送る"):
        if alert_count > 0:
            if gmail_user and gmail_pass and target_email:
                # 名前が空欄の場合はデフォルト値を設定
                final_from_name = gmail_name if gmail_name else "タスク管理通知"
                final_to_name = target_name if target_name else "担当者様"
                
                body = f"{final_to_name}\n\n【タスク管理アプリからの通知】\n以下のタスクが未完了、または期限切れです。\n\n"
                for idx, row in alert_rows.iterrows():
                    assignees = f"{row.get('担当者1','') or ''} {row.get('担当者2','') or ''} {row.get('担当者3','') or ''}"
                    body += f"・タイトル: {row['タイトル']}\n"
                    body += f"  期限: {row['期限']} / 担当: {assignees}\n"
                    body += f"  優先度: {row['優先度']} / 進捗: {row['進捗']}\n"
                    body += "-"*20 + "\n"
                
                if send_gmail("【重要】タスク未完了通知", body, target_email, final_to_name, gmail_user, final_from_name, gmail_pass):
                    st.success(f"{final_to_name} 宛にメールを送信しました！")
            else:
                st.error("必須項目（アドレス・パスワード）を入力してください。")
        else:
            st.info("通知対象のタスクはありません。")

# ------------------------------------------------
## 1. 登録・編集フォーム
# ------------------------------------------------

with st.expander(f"**タスク新規登録 / {'編集' if st.session_state.editing_task is not None else '作成'}**", expanded=True):
    task_to_edit = st.session_state.editing_task if st.session_state.editing_task else {}
    col1, col2 = st.columns(2)

    with col1:
        title = st.text_input("①タイトル", value=task_to_edit.get("タイトル", ""))
        priority = st.selectbox("③優先度", options=PRIORITY_OPTIONS, index=PRIORITY_OPTIONS.index(task_to_edit.get("優先度", PRIORITY_OPTIONS[0])))
        last_req = st.session_state.tasks_df["依頼者"].iloc[-1] if not st.session_state.tasks_df.empty and pd.notna(st.session_state.tasks_df["依頼者"].iloc[-1]) else ""
        requester = st.text_input("④依頼者", value=task_to_edit.get("依頼者", last_req))
        
        st.write("⑤担当者 (最大3名)")
        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            assignee1 = st.text_input("担当1", value=task_to_edit.get("担当者1", ""), label_visibility="collapsed", placeholder="担当者1")
        with ac2:
            assignee2 = st.text_input("担当2", value=task_to_edit.get("担当者2", ""), label_visibility="collapsed", placeholder="担当者2")
        with ac3:
            assignee3 = st.text_input("担当3", value=task_to_edit.get("担当者3", ""), label_visibility="collapsed", placeholder="担当者3")
        
    with col2:
        details = st.text_area("②詳細", value=task_to_edit.get("詳細", ""))
        remarks = st.text_area("⑨備考 (遅延理由など)", value=task_to_edit.get("備考", ""))
        status = st.selectbox("⑥進捗", options=STATUS_OPTIONS, index=STATUS_OPTIONS.index(task_to_edit.get("進捗", STATUS_OPTIONS[0])))
