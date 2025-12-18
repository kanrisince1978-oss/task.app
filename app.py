# --- 接続テスト用ボタン（サイドバーに追加されます） ---
with st.sidebar:
    st.markdown("---")
    if st.button("🔧 接続テスト"):
        try:
            client = get_gspread_client()
            sheet = client.open(SHEET_NAME).sheet1
            val = sheet.acell('A1').value
            st.success(f"✅ 接続成功！\nスプレッドシートが見つかりました。\nA1セルの値: {val}")
        except Exception as e:
            st.error(f"❌ 接続失敗\n原因: {e}")
