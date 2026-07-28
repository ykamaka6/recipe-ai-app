import re
import requests
import pandas as pd
import streamlit as st

st.title("AI献立提案アプリ")
st.write("レシート内容を入力し、AIの解析結果を確認・修正して在庫登録します。")

if "candidates" not in st.session_state:
    st.session_state.candidates = []

if "inventory" not in st.session_state:
    st.session_state.inventory = []

if "ai_answer" not in st.session_state:
    st.session_state.ai_answer = ""

receipt_text = st.text_area(
    "レシート内容",
    placeholder="レシートの商品名を1行ずつ入力してください\n例：\nこくうまキムチ\nキャベツ\nあいちっこプレミアム\n洗剤"
)


def run_dify(text):
    url = st.secrets["DIFY_API_URL"]
    api_key = st.secrets["DIFY_API_KEY"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "inputs": {
            "receipt_text": text,
            "レシート内容": text
        },
        "query": text,
        "response_mode": "blocking",
        "user": "demo-user"
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=60
    )

    response.raise_for_status()
    return response.json()


def get_answer(result):
    if "data" in result:
        outputs = result.get("data", {}).get("outputs", {})
        if "answer" in outputs:
            return outputs["answer"]

    if "answer" in result:
        return result["answer"]

    return str(result)


def clean_text(text):
    text = str(text)
    text = text.replace("<br>", "\n")
    text = text.replace("<br/>", "\n")
    text = text.replace("<br />", "\n")
    text = text.replace("</li>", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    return text


def extract_value(block, label):
    labels = [
        "レシート上の商品名",
        "推定される食材名",
        "購入数量",
        "購入単位",
        "内容量推定",
        "カテゴリ",
        "在庫管理対象",
        "確信度",
        "ユーザー確認"
    ]

    other_labels = [item for item in labels if item != label]
    next_label_pattern = "|".join([re.escape(item) for item in other_labels])

    pattern = rf"{re.escape(label)}\s*[:：]\s*(.*?)(?=\s*(?:{next_label_pattern})\s*[:：]|$)"
    match = re.search(pattern, block, flags=re.DOTALL)

    if match:
        return match.group(1).strip()

    return ""


def parse_answer(answer):
    cleaned = clean_text(answer)
    candidates = []

    blocks = re.split(r"\n\s*\d+[\.)]\s*", "\n" + cleaned)

    for block in blocks:
        block = block.strip()

        if not block:
            continue

        if "食材リスト" in block and "推定される食材名" not in block:
            continue

        receipt_name = extract_value(block, "レシート上の商品名")
        food_name = extract_value(block, "推定される食材名")
        quantity = extract_value(block, "購入数量")
        unit = extract_value(block, "購入単位")
        category = extract_value(block, "カテゴリ")
        inventory_target = extract_value(block, "在庫管理対象")
        confidence = extract_value(block, "確信度")
        user_check = extract_value(block, "ユーザー確認")

        if not receipt_name:
            first_line = block.split("\n")[0].strip()
            if "推定される食材名" in first_line:
                first_line = first_line.split("推定される食材名")[0].strip()
            receipt_name = first_line

        if not food_name:
            food_name = receipt_name

        register_flag = True
        non_food_words = [
            
            "洗剤",
            "シャンプー",
            "ラップ",
            "電池",
            "文具",
            "ティッシュ",
            "トイレットペーパー",
            "スポンジ"
        ]

        if inventory_target == "対象外":
            register_flag = False
        if "食品ではない" in food_name:
            register_flag = False
        if receipt_name in non_food_words:
            register_flag = False
        if food_name in non_food_words:
            register_flag = False

        confirm_status = "登録可能"
        if user_check == "必要" or confidence == "低":
            confirm_status = "要確認"

        candidates.append({
            "登録する": register_flag,
            "元の商品名": receipt_name,
            "食材名": food_name,
            "数量": quantity if quantity else "1",
            "単位": unit if unit else "不明",
            "カテゴリ": category if category else "その他食品",
            "確認状態": confirm_status
        })

    return candidates


st.divider()

if st.button("レシートを解析する"):
    if not receipt_text.strip():
        st.warning("レシート内容を入力してください。")
    else:
        try:
            with st.spinner("Difyでレシートを解析しています..."):
                result = run_dify(receipt_text)

            answer = get_answer(result)
            st.session_state.ai_answer = answer
            st.session_state.candidates = parse_answer(answer)

        except requests.exceptions.Timeout:
            st.error("Difyの応答が60秒以内に返ってきませんでした。")

        except Exception as error:
            st.error("エラーが発生しました。")
            st.write(str(error))


if st.session_state.ai_answer:
    st.subheader("AI解析結果")
    st.write(st.session_state.ai_answer)

st.divider()

st.subheader("在庫登録前の確認・修正")

if len(st.session_state.candidates) == 0:
    st.info("まだ在庫登録候補がありません。レシートを解析してください。")
else:
    candidate_df = pd.DataFrame(st.session_state.candidates)

    edited_df = st.data_editor(
        candidate_df,
        key="candidate_editor",
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "登録する": st.column_config.CheckboxColumn("登録する"),
            "元の商品名": st.column_config.TextColumn("元の商品名"),
            "食材名": st.column_config.TextColumn("食材名"),
            "数量": st.column_config.TextColumn("数量"),
            "単位": st.column_config.SelectboxColumn(
                "単位",
                options=["個", "袋", "パック", "本", "玉", "束", "g", "kg", "不明"]
            ),
            "カテゴリ": st.column_config.SelectboxColumn(
                "カテゴリ",
                options=[
                    "野菜",
                    "肉",
                    "魚",
                    "卵",
                    "乳製品",
                    "大豆製品",
                    "穀物",
                    "主食",
                    "果物",
                    "発酵食品",
                    "飲料",
                    "調味料",
                    "その他食品"
                ]
            ),
            "確認状態": st.column_config.SelectboxColumn(
                "確認状態",
                options=["登録可能", "要確認"]
            )
        }
    )

    if st.button("チェックした食材を在庫に登録する"):
        selected_df = edited_df[edited_df["登録する"].astype(bool)]

        if selected_df.empty:
            st.warning("登録する食材にチェックを入れてください。")
        else:
            new_items = []

            for _, row in selected_df.iterrows():
                new_items.append({
                    "食材名": str(row["食材名"]),
                    "数量": str(row["数量"]),
                    "単位": str(row["単位"]),
                    "カテゴリ": str(row["カテゴリ"]),
                    "確認状態": str(row["確認状態"])
                })

            st.session_state.inventory.extend(new_items)
            st.success(f"{len(new_items)}件を在庫に登録しました。")
            st.rerun()

st.divider()

st.subheader("現在の在庫一覧")

if len(st.session_state.inventory) == 0:
    st.info("まだ在庫は登録されていません。")
else:
    inventory_df = pd.DataFrame(st.session_state.inventory)
    st.dataframe(inventory_df, use_container_width=True)
