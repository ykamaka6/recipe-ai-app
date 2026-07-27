import streamlit as st
import requests

st.title("AI献立提案アプリ")

st.write("レシート内容を入力すると、Difyのレシート解析AIを呼び出します。")

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
        "receipt_text": receipt_text
    },
    "query": "レシート内容を解析してください。",
    "response_mode": "blocking",
    "user": "demo-user"
}
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    return response

if st.button("レシートを解析する"):
    if receipt_text.strip() == "":
        st.warning("レシート内容を入力してください。")
    else:
        try:
            with st.spinner("Difyでレシートを解析しています..."):
                response = run_dify(receipt_text)

            if response.status_code == 200:
                result = response.json()
                st.subheader("解析結果")

                if "answer" in result:
                    st.write(result["answer"])
                else:
                    st.write(result)
            else:
                st.error(f"APIエラー：{response.status_code}")
                st.write(response.text)

        except requests.exceptions.Timeout:
            st.error("Difyの応答が30秒以内に返ってきませんでした。Dify側の処理が重い可能性があります。")

        except Exception as e:
            st.error("エラーが発生しました。")
            st.write(str(e))
