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

#
