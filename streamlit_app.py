import streamlit as st
import requests

st.title("AI献立提案アプリ")

st.write("レシート内容を入力すると、Difyのレシート解析ワークフローを呼び出します。")

receipt_text = st.text_area(
    "レシート内容",
    placeholder="レシートの商品名を1行ずつ入力してください\n例：\nこくうまキムチ\nキャベツ\nあいちっこプレミアム\nセンザイ"
)

def run_dify_receipt_workflow(receipt_text):
    url = st.secrets["DIFY_API_URL"]
    api_key = st.secrets["DIFY_API_KEY"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "inputs": {
            "receipt_text": receipt_text
        },
        "response_mode": "blocking",
        "user": "demo-user"
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=120
    )

    return response

if st.button("レシートを解析する"):
    if receipt_text.strip() == "":
        st.warning("レシート内容を入力してください。")
    else:
        with st.spinner("Difyでレシートを解析しています..."):
            response = run_dify_receipt_workflow(receipt_text)

        st.subheader("APIステータス")
        st.write(response.status_code)

        st.subheader("APIレスポンス本文")
        st.write(response.text)

        if response.status_code == 200:
            result = response.json()
            st.subheader("解析結果")

            outputs = result.get("data", {}).get("outputs", {})

            if "answer" in outputs:
                st.write(outputs["answer"])
            else:
                st.write(outputs)
        else:
            st.error("Dify API呼び出しに失敗しています。上のステータスとレスポンス本文を確認してください。")
