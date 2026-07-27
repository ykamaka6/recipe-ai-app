import streamlit as st

st.title("AI献立提案アプリ")

st.write("レシート内容を入力してください。")

receipt_text = st.text_area(
    "レシート内容",
    placeholder="レシートの商品名を1行ずつ入力してください\n例：\nこくうまキムチ\nキャベツ\nあいちっこプレミアム\nセンザイ"
)

if st.button("実行テスト"):
    if receipt_text.strip() == "":
        st.warning("レシート内容を入力してください。")
    else:
        st.write("入力されたレシート内容：")
        st.write(receipt_text)
