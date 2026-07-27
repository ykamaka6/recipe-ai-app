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

receipt_text = st.text_area(
    "レシート内容",
    placeholder="レシートの商品名を1行ずつ入力してください\n例：\nこくうまキムチ\nキャベツ\nあいちっこプレミアム\nセンザイ"
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


def extract_value(block, label):
    pattern = rf"{label}\s*[:：]\s*(.*)"
    match = re.search(pattern, block)
    if match:
        return match.group(1).strip()
    return ""


def parse_answer(answer):
    candidates = []

    blocks = re.split(r"\n\s*\d+[\.\)]\s*", "\n" + answer)

    for block i* blocks:
        block = block.str*p()

        if not block:
       *    continue

        receipt_name*= extract_value(block, "レシート上の商品名"*
        food_name = extract_value*block, "推定される食材名")
        quantit* = extract_value(block, "購入数量")
  *     unit = extract_value(block, "*入単位")
        category = extract_v*lue(block, "カテゴリ")
        invento*y_target = extract_value(block, "在*管理対象")
        confidence = extrac*_value(block, "確信度")
        user_*heck = extract_value(block, "ユーザー確*")

        if not receipt_name:
 *          first_line = block.split*"\n")[0].strip()
            recei*t_name = first_line

        if no* food_name:
            food_name * receipt_name

        register_fl*g = True

        if inventory_tar*et == "対象外":
            register_*lag = False

        if "食品ではない" i* food_name:
            register_f*ag = False

        if food_name i* ["センザイ", "洗剤", "シャンプー", "ラップ"]:
 *          register_flag = False

 *      confirm_status = "登録可能"

   *    if user_check == "必要" or confi*ence == "低":
            confirm_s*atus = "要確認"

        candidates.a*pend(
            {
              * "登録する": register_flag,
          *     "元の商品名": receipt_name,
      *         "食材名": food_name,
       *        "数量": quantity if quantity*else "1",
                "単位": un*t if unit else "不明",
             *  "カテゴリ": category if category els* "その他食品",
                "確認状態": *onfirm_status
            }
      * )

    return candidates


st.div*der()

if st.button("レシートを解析する"):
*   if receipt_text.strip() == "":
*       st.warning("レシート内容を入力してください。")
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


if "ai_answer" in st.session_state:
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
        selected_df = edited_df[edited_df["登録する"] == True]

        if selected_df.empty:
            st.warning("登録する食材にチェックを入れてください。")
        else:
            for _, row in selected_df.iterrows():
                st.session_state.inventory.append(
                    {
                        "食材名": row["食材名"],
                        "数量": row["数量"],
                        "単位": row["単位"],
                        "カテゴリ": row["カテゴリ"],
                        "確認状態": row["確認状態"]
                    }
                )

            st.success("在庫に登録しました。")

st.divider()

st.subheader("現在の在庫一覧")

if len(st.session_state.inventory) == 0:
    st.info("まだ在庫は登録されていません。")
else:
    inventory_df = pd.DataFrame(st.session_state.inventory)
    st.table(inventory_df)
