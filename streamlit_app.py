import streamlit as st
import requests

st.title("AI献立提案アプリ")

st.write("レシート内容を入力し、AIの解析結果を人間が確認・修正して在庫登録します。")

if "inventory" not in st.session_state:
    st.session_state.inventory = []

receipt_text = st.text_area(
    "レシート内容",
    placeholder="レシートの商品名を1行ずつ入力してください\n例：\nこくうまキムチ\nキャベツ\nあいちっこプレミアム\nセンザイ"
)

def run_dify(receipt_text):
    url = st.secrets["DIFY_API_URL"]
    api_key = st.secrets["DIFY_API_KEY"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "inputs": {
            "receipt_text": receipt_text,
            "レシート内容": receipt_text
        },
        "query": receipt_text,
        "response_mode": "blocking",
        "user": "demo-user"
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=60
    )

    return response

st.divider()

if st.button("レシートを解析する"):
    if receipt_text.strip() == "":
        st.warning("レシート内容を入力してください。")
    else:
        with st.spinner("Difyでレシートを解析しています..."):
            response = run_dify(receipt_text)

        if response.status_code == 200:
            result = response.json()

            answer = None

            if "data" in result:
                outputs = result.get("data", {}).get("outputs", {})
                answer = outputs.get("answer")

            if answer is None:
                answer = result.get("answer")

            st.session_state.ai_result = answer

        else:
            st.error(f"APIエラー：{response.status_code}")
            st.write(response.text)

if "ai_result" in st.session_state:
    st.subheader("AI解析結果")
    st.write(st.session_state.ai_result)

st.divider()

st.subheader("在庫登録内容を人間が確認・修正")

food_name = st.text_input("登録する食材名", placeholder="例：卵")
quantity = st.text_input("数量", placeholder="例：1")
unit = st.selectbox(
    "単位",
    ["個", "袋", "パック", "本", "玉", "束", "g", "kg", "不明"]
)
category = st.selectbox(
    "カテゴリ",
    ["野菜", "肉", "魚", "卵", "乳製品", "大豆製品", "穀物", "主食", "果物", "発酵食品", "飲料", "調味料", "その他食品"]
)

if st.button("在庫に追加する"):
    if food_name.strip() == "":
        st.warning("食材名を入力してください。")
    else:
        st.session_state.inventory.append(
            {
                "食材名": food_name,
                "数量": quantity,
                "単位": unit,
                "カテゴリ": category
            }
        )
        st.success(f"{food_name} を在庫に追加しました。")

st.divider()

st.subheader("現在の在庫一覧")

if len(st.session_state.inventory) == 0:
    st.info("まだ在庫が登録されていません。")
else:
    st.table(st.session_state.inventory)
