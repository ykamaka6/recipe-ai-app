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
if "recipe_answer" not in st.session_state:
    st.session_state.recipe_answer = ""
if "family_profile" not in st.session_state:
    st.session_state.family_profile = ""
if "avoid_foods" not in st.session_state:
    st.session_state.avoid_foods = ""
if "health_goal" not in st.session_state:
    st.session_state.health_goal = ""
if "cooking_time" not in st.session_state:
    st.session_state.cooking_time = ""
if "last_added_items" not in st.session_state:
    st.session_state.last_added_items = []
if "show_consumption_editor" not in st.session_state:
    st.session_state.show_consumption_editor = False

CATEGORY_OPTIONS = [
    "野菜", "肉", "魚", "卵", "乳製品", "大豆製品", "穀物", "主食", "果物",
    "発酵食品", "飲料", "調味料", "その他食品"
]
UNIT_OPTIONS = ["個", "袋", "パック", "本", "玉", "束", "g", "kg", "不明"]


def call_dify(api_key, query, inputs=None):
    url = st.secrets["DIFY_API_URL"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": inputs or {},
        "query": query,
        "response_mode": "blocking",
        "user": "demo-user"
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
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


def strip_html(text):
    text = str(text)
    text = text.replace("<br>", "\n")
    text = text.replace("<br/>", "\n")
    text = text.replace("<br />", "\n")
    text = text.replace("</li>", "\n")
    text = re.sub(r"<li[^>]*>", "・", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


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


def is_suspicious_food_name(food_name):
    text = str(food_name).strip()
    if text == "":
        return True
    suspicious_markers = ["または", "不明", "推測", "候補", "?", "？", "（中）", "(中)", "低確信度"]
    return any(marker in text for marker in suspicious_markers)


def parse_answer(answer):
    cleaned = strip_html(answer)
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

        register_decision = "登録する"
        confirm_status = "登録可能"

        if inventory_target == "対象外" or "食品ではない" in food_name:
            register_decision = "登録しない"
            confirm_status = "要確認"
        if user_check == "必要" or confidence == "低" or is_suspicious_food_name(food_name):
            register_decision = "登録しない"
            confirm_status = "要確認"

        candidates.append({
            "登録判定": register_decision,
            "元の商品名": receipt_name,
            "食材名": food_name,
            "数量": quantity if quantity else "1",
            "単位": unit if unit else "不明",
            "カテゴリ": category if category else "その他食品",
            "確認状態": confirm_status
        })
    return candidates


def inventory_to_text(inventory_list):
    lines = []
    for item in inventory_list:
        lines.append(
            f"{item.get('食材名', '')} {item.get('数量', '')}{item.get('単位', '')} カテゴリ:{item.get('カテゴリ', '')}"
        )
    return "\n".join(lines)


def build_recipe_query(inventory_text, family_profile, avoid_foods, health_goal, cooking_time):
    return f"""
あなたは家庭向けの献立提案AIです。
以下の条件から、今日の夕食を1つだけ提案してください。

在庫一覧：
{inventory_text}

家族条件：
{family_profile}

避ける食材・避ける条件：
{avoid_foods}

健康目標：
{health_goal}

調理時間：
{cooking_time}

最優先ルール：
・家族条件、避ける食材、苦手な味、アレルギー条件を最優先してください。
・在庫食材をすべて使う必要はありません。
・在庫にあっても、家族条件や避ける条件に合わない食材は使わないでください。
・食材ごとに、辛さ、苦味、硬さ、脂っこさ、塩分、食べやすさを判断してください。
・条件に合わない可能性がある食材は、無理に使わず「今回使わない在庫食材」に入れてください。
・食品ロス削減は大事ですが、家族条件や食べやすさより優先しないでください。
・献立として自然で、実際に家庭で食べられるものにしてください。

調味料ルール：
・塩、こしょう、醤油、みそ、砂糖、酢、油、ごま油、みりん、酒、だし、コンソメ、マヨネーズ、ケチャップは基本調味料として扱ってください。
・基本調味料は「買い足す食材」に入れないでください。
・使う基本調味料は「家庭にある前提の調味料」に書いてください。
・特殊な調味料だけ、必要な場合に買い足す食材へ入れてください。

出力ルール：
・HTMLタグを使わないでください。
・説明は短くしてください。
・レシピ以外の説明は各項目1行までにしてください。
・文字数は全体で600字以内にしてください。
・「健康に良いです」を繰り返さないでください。

出力形式：
献立名：

使用する在庫食材：
・

今回使わない在庫食材：
・食材名：理由

買い足す食材：
・なし、または必要な食材だけ

家庭にある前提の調味料：
・

作り方：
1.
2.
3.

提案理由：
・

食品ロス削減：
・

健康補助：
・
"""


receipt_text = st.text_area(
    "レシート内容",
    placeholder="レシートの商品名を1行ずつ入力してください\n例：\n卵\nキャベツ\n鶏むね肉"
)

if st.button("レシートを解析する"):
    if not receipt_text.strip():
        st.warning("レシート内容を入力してください。")
    else:
        try:
            with st.spinner("Difyでレシートを解析しています..."):
                result = call_dify(
                    st.secrets["DIFY_API_KEY"],
                    receipt_text,
                    {"receipt_text": receipt_text, "レシート内容": receipt_text}
                )
            answer = get_answer(result)
            st.session_state.ai_answer = strip_html(answer)
            st.session_state.candidates = parse_answer(answer)
        except Exception as error:
            st.error("レシート解析でエラーが発生しました。")
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
            "登録判定": st.column_config.SelectboxColumn("登録判定", options=["登録する", "登録しない"]),
            "元の商品名": st.column_config.TextColumn("元の商品名"),
            "食材名": st.column_config.TextColumn("食材名"),
            "数量": st.column_config.TextColumn("数量"),
            "単位": st.column_config.SelectboxColumn("単位", options=UNIT_OPTIONS),
            "カテゴリ": st.column_config.SelectboxColumn("カテゴリ", options=CATEGORY_OPTIONS),
            "確認状態": st.column_config.SelectboxColumn("確認状態", options=["登録可能", "要確認"])
        }
    )

    if st.button("登録判定が『登録する』の食材を在庫に登録する"):
        selected_df = edited_df[edited_df["登録判定"] == "登録する"]
        if selected_df.empty:
            st.warning("登録する食材がありません。登録判定を確認してください。")
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
            st.session_state.last_added_items = new_items
            st.success(f"{len(new_items)}件を在庫に登録しました。")
            st.rerun()

st.divider()
st.subheader("現在の在庫一覧")

if len(st.session_state.inventory) == 0:
    st.info("まだ在庫は登録されていません。")
else:
    inventory_df = pd.DataFrame(st.session_state.inventory)
    inventory_df.insert(0, "削除", False)

    edited_inventory_df = st.data_editor(
        inventory_df,
        key="inventory_editor",
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "削除": st.column_config.CheckboxColumn("削除"),
            "食材名": st.column_config.TextColumn("食材名"),
            "数量": st.column_config.TextColumn("数量"),
            "単位": st.column_config.SelectboxColumn("単位", options=UNIT_OPTIONS),
            "カテゴリ": st.column_config.SelectboxColumn("カテゴリ", options=CATEGORY_OPTIONS),
            "確認状態": st.column_config.SelectboxColumn("確認状態", options=["登録可能", "要確認"])
        }
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("在庫一覧の編集を保存する"):
            kept_df = edited_inventory_df[edited_inventory_df["削除"] == False].drop(columns=["削除"])
            st.session_state.inventory = kept_df.to_dict("records")
            st.success("在庫一覧を更新しました。")
            st.rerun()

    with col2:
        if st.button("直前の在庫登録を取り消す"):
            if len(st.session_state.last_added_items) == 0:
                st.warning("取り消せる直前登録がありません。")
            else:
                remove_count = len(st.session_state.last_added_items)
                st.session_state.inventory = st.session_state.inventory[:-remove_count]
                st.session_state.last_added_items = []
                st.success("直前の登録を取り消しました。")
                st.rerun()

st.divider()
st.subheader("献立提案")

st.session_state.family_profile = st.text_area(
    "家族条件",
    value=st.session_state.family_profile,
    placeholder="例：大人2人、子ども1人。子どもは辛いものが苦手。"
)
st.session_state.avoid_foods = st.text_input(
    "避ける食材・避ける条件",
    value=st.session_state.avoid_foods,
    placeholder="例：辛いもの、えび、そば"
)
st.session_state.health_goal = st.text_input(
    "健康目標",
    value=st.session_state.health_goal,
    placeholder="例：野菜多め、塩分控えめ"
)
st.session_state.cooking_time = st.text_input(
    "調理時間",
    value=st.session_state.cooking_time,
    placeholder="例：30分以内"
)

if st.button("家族条件を保存する"):
    st.success("家族条件を保存しました。このセッション中は保持されます。")

if st.button("献立を提案する"):
    inventory_text = inventory_to_text(st.session_state.inventory)
    if not inventory_text:
        st.warning("先に在庫を登録してください。")
    else:
        recipe_query = build_recipe_query(
            inventory_text,
            st.session_state.family_profile,
            st.session_state.avoid_foods,
            st.session_state.health_goal,
            st.session_state.cooking_time
        )
        recipe_inputs = {
            "inventory": inventory_text,
            "在庫一覧": inventory_text,
            "family_profile": st.session_state.family_profile,
            "家族条件": st.session_state.family_profile,
            "avoid_foods": st.session_state.avoid_foods,
            "避ける食材": st.session_state.avoid_foods,
            "health_goal": st.session_state.health_goal,
            "健康目標": st.session_state.health_goal,
            "cooking_time": st.session_state.cooking_time,
            "調理時間": st.session_state.cooking_time
        }
        try:
            with st.spinner("Difyで献立を提案しています..."):
                result = call_dify(st.secrets["RECIPE_API_KEY"], recipe_query, recipe_inputs)
            st.session_state.recipe_answer = strip_html(get_answer(result))
            st.session_state.show_consumption_editor = False
        except Exception as error:
            st.error("献立提案でエラーが発生しました。")
            st.write(str(error))

if st.session_state.recipe_answer:
    st.subheader("献立提案結果")
    st.write(st.session_state.recipe_answer)

    if st.button("この献立を作ったので在庫を更新する"):
        st.session_state.show_consumption_editor = True

if st.session_state.show_consumption_editor:
    st.divider()
    st.subheader("作った後の在庫更新")
    st.write("レシピで使った分に合わせて、数量を修正するか、使い切った食材を削除してください。")

    if len(st.session_state.inventory) == 0:
        st.info("在庫がありません。")
    else:
        consumption_df = pd.DataFrame(st.session_state.inventory)
        consumption_df.insert(0, "削除", False)

        edited_consumption_df = st.data_editor(
            consumption_df,
            key="consumption_editor",
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "削除": st.column_config.CheckboxColumn("削除"),
                "食材名": st.column_config.TextColumn("食材名"),
                "数量": st.column_config.TextColumn("数量"),
                "単位": st.column_config.SelectboxColumn("単位", options=UNIT_OPTIONS),
                "カテゴリ": st.column_config.SelectboxColumn("カテゴリ", options=CATEGORY_OPTIONS),
                "確認状態": st.column_config.SelectboxColumn("確認状態", options=["登録可能", "要確認"])
            }
        )

        if st.button("作った後の在庫更新を保存する"):
            updated_df = edited_consumption_df[edited_consumption_df["削除"] == False].drop(columns=["削除"])
            st.session_state.inventory = updated_df.to_dict("records")
            st.session_state.show_consumption_editor = False
            st.success("作った後の在庫を更新しました。")
            st.rerun()
