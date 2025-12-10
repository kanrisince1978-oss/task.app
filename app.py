import streamlit as st
import pandas as pd
import datetime
import io
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
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

        # 削除フラグの変換
        df['削除'] = df['削除'].apply(lambda x: True if str(x).upper() == 'TRUE' else False)

        # 日付型の変換
        def parse_date(x):
            if not x or str(x).strip() == "":
                return None
            try:
                return pd.to_datetime(x).date()
            except:
                return None

        df['期限'] = df['期限'].apply(parse_date)
        df['完了日'] = df['完了日'].apply(parse_date)

        # テキスト列のNaN処理
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
    """スプレッドシートのH列(優先度)とI列(進捗)にプルダウンを設定する"""
    # H列はインデックス7, I列はインデックス8 (0始まり)
    # 行は2行目(index 1)から1000行目まで
    
    requests = [
        # 1. 優先度 (H列) のプルダウン設定
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
        # 2. 進捗 (I列) のプルダウン設定
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
    # APIリクエスト送信
    sheet.batch_update({"requests": requests})


def save_data(df):
    """Googleスプレッドシートにデータを保存する"""
    try:
        client = get_gspread_client()
        sheet = client.open(SHEET_NAME).sheet1
        
        save_df = df.copy()
        
        for col in ['期限', '完了日']:
            save_df[col] = save_df[col].apply(lambda x: x.strftime('%Y-%m-%d') if x is not None and pd.notnull(x) else "")

        save_df['削除'] = save_df['削除'].apply(lambda x: "TRUE" if x else "FALSE")
        
        data_to_write = save_df.values.tolist()
        
        # 入力規則を守るため、値のみクリアして書き込む
        sheet.batch_clear(["A2:L1000"]) 
        if len(data_to_write) > 0:
            sheet.update(range_name=f'A2', values=data_to_write)
        
        # ★ここでプルダウン設定を適用する
        try:
            set_validation_rules(sheet)
        except Exception as e:
            # 万が一プルダウン設定でコケてもデータ保存は成功させるためpass
            print(f"Validation Error: {e}")
            
        return True

    except Exception as e:
        st.error(f"スプレッドシート保存エラー: {e}")
        return False

def send_gmail(subject, body, to_email, from_email, app_password):
    """Gmail送信関数"""
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
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
    gmail_user = st.text_input("送信元Gmailアドレス", placeholder="your_email@gmail.com")
    gmail_pass = st.text_input("Googleアプリパスワード", type="password")
    target_email = st.text_input("送信先メールアドレス", placeholder="boss@company.com")
    
    if st.button("📩 今すぐ通知を送る"):
        if alert_count > 0:
            if gmail_user and gmail_pass and target_email:
                body = "【タスク管理アプリからの通知】\n\n以下のタスクが未完了、または期限切れです。\n\n"
                for idx, row in alert_rows.iterrows():
                    assignees = f"{row.get('担当者1','') or ''} {row.get('担当者2','') or ''} {row.get('担当者3','') or ''}"
                    body += f"・タイトル: {row['タイトル']}\n"
                    body += f"  期限: {row['期限']} / 担当: {assignees}\n"
                    body += f"  優先度: {row['優先度']} / 進捗: {row['進捗']}\n"
                    body += "-"*20 + "\n"
                
                if send_gmail("【重要】タスク未完了通知", body, target_email, gmail_user, gmail_pass):
                    st.success("メールを送信しました！")
            else:
                st.error("メール設定を全て入力してください。")
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
        
        def get_default_date(key, days_offset=0):
            val = task_to_edit.get(key)
            if isinstance(val, datetime.date): return val
            return datetime.date.today() + datetime.timedelta(days=days_offset)

        due_date = st.date_input("⑦期限", value=get_default_date("期限", 7))
        comp_default = get_default_date("完了日", 0) if status=="完了" else None
        completion_date = st.date_input("⑧完了日", value=comp_default)

    if st.button("タスクを登録・更新", type="primary"):
        if not title:
            st.error("タイトルは必須です。")
        else:
            new_task = {
                "削除": False, "タイトル": title, "詳細": details, "依頼者": requester, 
                "担当者1": assignee1, "担当者2": assignee2, "担当者3": assignee3,
                "優先度": priority, "進捗": status, 
                "期限": due_date, "完了日": completion_date if completion_date and status == "完了" else None,
                "備考": remarks
            }
            
            if st.session_state.edit_index is not None:
                st.session_state.tasks_df.loc[st.session_state.edit_index] = new_task
                st.success(f"更新しました: {title}")
                st.session_state.editing_task = None
                st.session_state.edit_index = None
            else:
                new_task_df = pd.DataFrame([new_task])
                st.session_state.tasks_df = pd.concat([st.session_state.tasks_df, new_task_df], ignore_index=True)
                st.success(f"登録しました: {title}")
            
            st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)
            save_data(st.session_state.tasks_df)
            st.rerun()

    if st.session_state.editing_task and st.button("キャンセル"):
        st.session_state.editing_task = None
        st.session_state.edit_index = None
        st.rerun()

st.markdown("---")

# ------------------------------------------------
## 2. フィルター & 一覧
# ------------------------------------------------
with st.expander("🔎 フィルター", expanded=False):
    f_c1, f_c2, f_c3 = st.columns(3)
    with f_c1: f_pri = st.multiselect("優先度", PRIORITY_OPTIONS)
    with f_c2:
        all_assignees = pd.unique(st.session_state.tasks_df[['担当者1', '担当者2', '担当者3']].astype(str).values.ravel('K'))
        all_assignees = [x for x in all_assignees if x != "" and x != "nan" and x != "None"]
        f_ass = st.multiselect("担当者 (いずれかに該当)", all_assignees)
    with f_c3: f_key = st.text_input("キーワード検索")

# フィルター適用
df_filtered = st.session_state.tasks_df.copy()
if f_pri: df_filtered = df_filtered[df_filtered['優先度'].isin(f_pri)]
if f_ass:
    mask = (df_filtered['担当者1'].isin(f_ass)) | (df_filtered['担当者2'].isin(f_ass)) | (df_filtered['担当者3'].isin(f_ass))
    df_filtered = df_filtered[mask]
if f_key: df_filtered = df_filtered[df_filtered['タイトル'].str.contains(f_key, na=False) | df_filtered['詳細'].str.contains(f_key, na=False)]

# 分割
df_active = df_filtered[df_filtered['進捗'] != '完了'].copy()
df_completed = df_filtered[df_filtered['進捗'] == '完了'].copy()

# === カラム設定 ===
col_cfg = {
    "削除": st.column_config.CheckboxColumn(width="small", label="削除"),
    "タイトル": st.column_config.TextColumn(width="medium"),
    "詳細": st.column_config.TextColumn(width="large"),
    "依頼者": st.column_config.TextColumn(width="small"),
    "担当者1": st.column_config.TextColumn(width="small", label="担当1"),
    "担当者2": st.column_config.TextColumn(width="small", label="担当2"),
    "担当者3": st.column_config.TextColumn(width="small", label="担当3"),
    "優先度": st.column_config.SelectboxColumn(options=PRIORITY_OPTIONS, width="small"),
    "進捗": st.column_config.SelectboxColumn(options=STATUS_OPTIONS, width="small"),
    "期限": st.column_config.DateColumn(format="YYYY-MM-DD", width="medium"),
    "完了日": st.column_config.DateColumn(format="YYYY-MM-DD", width="medium"),
    "備考": st.column_config.TextColumn(width="large"),
}

cols_order = [
    "削除", "タイトル", "詳細", "依頼者", 
    "担当者1", "担当者2", "担当者3", 
    "優先度", "進捗", "期限", "完了日", "備考"
]

# --- A. 未完了 ---
st.subheader("🔥 未完了タスク")
df_active = ensure_date_columns(df_active)
edited_active = st.data_editor(
    df_active, 
    column_config=col_cfg, 
    column_order=cols_order, 
    hide_index=True, 
    key="ed_act", 
    num_rows="dynamic"
)

if st.session_state.ed_act.get("edited_rows"):
    for idx, changes in st.session_state.ed_act["edited_rows"].items():
        real_idx = df_active.index[idx]
        for col, val in changes.items():
            st.session_state.tasks_df.at[real_idx, col] = val
    st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)
    save_data(st.session_state.tasks_df)
    st.rerun()

if st.button("🗑️ チェックした行を削除 (未完了)"):
    del_idx = st.session_state.tasks_df[st.session_state.tasks_df['削除']].index
    if len(del_idx) > 0:
        st.session_state.tasks_df = st.session_state.tasks_df.drop(del_idx).reset_index(drop=True)
        save_data(st.session_state.tasks_df)
        st.rerun()

st.markdown("---")

# --- B. 完了済み ---
st.subheader("✅ 完了済みタスク")
df_completed = ensure_date_columns(df_completed)
edited_completed = st.data_editor(
    df_completed, 
    column_config=col_cfg, 
    column_order=cols_order, 
    hide_index=True, 
    key="ed_comp"
)

if st.session_state.ed_comp.get("edited_rows"):
    for idx, changes in st.session_state.ed_comp["edited_rows"].items():
        real_idx = df_completed.index[idx]
        for col, val in changes.items():
            st.session_state.tasks_df.at[real_idx, col] = val
    st.session_state.tasks_df = ensure_date_columns(st.session_state.tasks_df)
    save_data(st.session_state.tasks_df)
    st.rerun()

st.markdown("---")

# CSV出力
csv_buffer = io.StringIO()
st.session_state.tasks_df.drop(columns=['削除'], errors='ignore').to_csv(csv_buffer, index=False, encoding='utf_8_sig')
st.download_button("📥 CSV出力", csv_buffer.getvalue(), "tasks.csv", "text/csv")
