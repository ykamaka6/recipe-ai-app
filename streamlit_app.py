import re
import requests
import pandas as pd
import streamlit as st

st.title("AI献立提案アプリ")
st.write("レシート内容を入力し、AIの解析結果を確認・修正して在庫登録します。")

CATEGORY_OPTIONS = [
    "主食・穀物", "肉・魚", "卵", "乳製品", "大豆製品", "調理済み食品",
    "調味料", "加工品・チルド食品", "菓子・スイーツ", "野菜・果物", "飲料", "その他食品"
]
UNIT_OPTIONS = ["個", "袋", "パック", "本", "玉", "束", "g", "kg", "不明"]

SPICY_KEYWORDS = ["キムチ", "唐辛子", "とうがらし", "七味", "一味", "豆板醤", "ラー油", "コチュジャン", "チリ", "タバスコ", "カレー粉", "カレールー", "辛口", "わさび", "からし", "マスタード", "スパイシー"]
BITTER_KEYWORDS = ["ゴーヤ", "春菊", "セロリ", "ピーマン"]
HARD_KEYWORDS = ["するめ", "硬い肉", "牛すじ"]
FATTY_KEYWORDS = ["バラ肉", "豚バラ", "脂身", "揚げ物"]
FRUIT_KEYWORDS = ["ブルーベリー", "いちご", "苺", "バナナ", "りんご", "リンゴ", "林檎", "みかん", "オレンジ", "ぶどう", "葡萄", "キウイ", "桃", "もも", "梨", "パイン", "パイナップル", "マンゴー", "メロン", "すいか", "スイカ", "柿", "レモン", "グレープフルーツ"]
NON_COOKING_CATEGORIES = ["調理済み食品", "菓子・スイーツ", "飲料"]

for key, value in {
    "candidates": [], "inventory": [], "ai_answer": "", "recipe_answer": "",
    "family_profile": "", "avoid_foods": "", "health_goal": "", "cooking_time": "",
    "last_added_items": [], "show_consumption_editor": False, "excluded_inventory": []
}.items():
    if key not in st.session_state:
        st.session_state[key] = value


def call_dify(api_key, query, inputs=None):
    response = requests.post(
        st.secrets["DIFY_API_URL"],
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"inputs": inputs or {}, "query": query, "response_mode": "blocking", "user": "demo-user"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def get_answer(result):
    if "data" in result:
        answer = result.get("data", {}).get("outputs", {}).get("answer")
        if answer:
            return answer
    return result.get("answer", str(result)) if isinstance(result, dict) else str(result)


def strip_html(text):
    text = str(text)
    for tag in ["&lt;br&gt;", "&lt;br/&gt;", "&lt;br /&gt;", "<br>", "<br/>", "<br />"]:
        text = text.replace(tag, "\n")
    text = text.replace("&lt;/li&gt;", "\n")
    text = re.sub(r"&lt;li[^&gt;]*&gt;", "・", text)
    text = re.sub(r"&lt;[^&gt;]+&gt;", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def text_contains_any(text, keywords):
    target = str(text).lower()
    return any(str(word).lower() in target for word in keywords)


def normalize_category(category):
    value = str(category).strip()
    mapping = {
        "主食": "主食・穀物", "穀物": "主食・穀物", "肉": "肉・魚", "魚": "肉・魚",
        "野菜": "野菜・果物", "果物": "野菜・果物", "菓子": "菓子・スイーツ",
        "発酵食品": "加工品・チルド食品", "加工食品": "加工品・チルド食品", "チルド食品": "加工品・チルド食品",
    }
    if value in CATEGORY_OPTIONS:
        return value
    return mapping.get(value, "その他食品")


def extract_value(block, label):
    labels = ["レシート上の商品名", "推定される食材名", "購入数量", "購入単位", "内容量推定", "カテゴリ", "在庫管理対象", "確信度", "ユーザー確認"]
    others = "|".join(re.escape(x) for x in labels if x != label)
    match = re.search(rf"{re.escape(label)}\s*[:：]\s*(.*?)(?=\s*(?:{others})\s*[:：]|$)", block, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def is_suspicious_food_name(food_name):
    text = str(food_name).strip()
    if not text:
        return True
    return any(x in text for x in ["または", "不明", "推測", "候補", "?", "？", "（中）", "(中)", "低確信度"])


def parse_answer(answer):
    cleaned = strip_html(answer)
    blocks = re.split(r"\n\s*\d+[\.)]\s*", "\n" + cleaned)
    candidates = []

    for block in blocks:
        block = block.strip()
        if not block or ("食材リスト" in block and "推定される食材名" not in block):
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
            receipt_name = block.split("\n")[0].replace("推定される食材名", "").strip()
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
            "カテゴリ": normalize_category(category),
            "確認状態": confirm_status,
        })
    return candidates


def get_avoid_flags(family_profile, avoid_foods, health_goal):
    text = f"{family_profile}\n{avoid_foods}\n{health_goal}"
    return {
        "spicy": text_contains_any(text, ["辛い", "辛味", "からい", "スパイシー", "刺激物"]),
        "bitter": text_contains_any(text, ["苦い", "苦味"]),
        "hard": text_contains_any(text, ["硬い", "かたい", "噛みにくい"]),
        "fatty": text_contains_any(text, ["脂っこい", "油っこい", "脂質控えめ"]),
        "salt": text_contains_any(text, ["塩分控えめ", "減塩", "低塩"]),
    }


def should_exclude_item(item, flags, avoid_foods):
    food_name = str(item.get("食材名", ""))
    category = str(item.get("カテゴリ", ""))
    reasons = []

    for term in [x.strip() for x in re.split(r"[,、\n]", str(avoid_foods)) if x.strip()]:
        if term in food_name:
            reasons.append(f"避ける食材に該当するため（{term}）")
    if category in NON_COOKING_CATEGORIES:
        reasons.append("料理に混ぜる食材ではなく、そのまま食べる・飲むものとして扱うため")
    if text_contains_any(food_name, FRUIT_KEYWORDS):
        reasons.append("甘い果物は夕食の主菜に混ぜず、デザートや別添えにするため")
    if flags["spicy"] and text_contains_any(food_name, SPICY_KEYWORDS):
        reasons.append("辛いものを避ける条件に合わない可能性があるため")
    if flags["bitter"] and text_contains_any(food_name, BITTER_KEYWORDS):
        reasons.append("苦味を避ける条件に合わない可能性があるため")
    if flags["hard"] and text_contains_any(food_name, HARD_KEYWORDS):
        reasons.append("硬い食材を避ける条件に合わない可能性があるため")
    if flags["fatty"] and text_contains_any(food_name, FATTY_KEYWORDS):
        reasons.append("脂っこさを避ける条件に合わない可能性があるため")
    if flags["salt"] and category == "調味料":
        reasons.append("塩分控えめの条件では注意が必要なため")
    return reasons


def split_inventory_for_recipe(inventory_list, family_profile, avoid_foods, health_goal):
    flags = get_avoid_flags(family_profile, avoid_foods, health_goal)
    usable, excluded = [], []
    for item in inventory_list:
        reasons = should_exclude_item(item, flags, avoid_foods)
        if reasons:
            excluded.append({**item, "除外理由": " / ".join(reasons)})
        else:
            usable.append(item)
    return usable, excluded


def inventory_to_text(inventory_list):
    return "\n".join(f"{x.get('食材名', '')} {x.get('数量', '')}{x.get('単位', '')} カテゴリ:{x.get('カテゴリ', '')}" for x in inventory_list)


def excluded_to_text(excluded_list):
    return "\n".join(f"{x.get('食材名', '')}：{x.get('除外理由', '')}" for x in excluded_list)


def answer_uses_excluded_item(answer, excluded_list):
    answer_text = strip_html(answer)
    answer_text = re.sub(
        r"今回使わない在庫食材：.*?(?=買い足す食材：|家庭にある前提の調味料：|作り方：|提案理由：|食品ロス削減：|健康補助：|$)",
        "",
        answer_text,
        flags=re.DOTALL,
    )
    used = []
    for item in excluded_list:
        food_name = str(item.get("食材名", "")).strip()
        if food_name and food_name in answer_text:
            used.append(food_name)
    return used


def build_recipe_query(usable_inventory_text, excluded_inventory_text, family_profile, avoid_foods, health_goal, cooking_time, retry_note=""):
    return f"""
あなたは家庭料理に詳しい献立提案AIです。
以下の条件から、今日の夕食を1つだけ提案してください。

使用してよい在庫食材：
{usable_inventory_text}

献立に使わない在庫食材：
{excluded_inventory_text if excluded_inventory_text else "なし"}

家族条件：
{family_profile}

避ける食材・避ける条件：
{avoid_foods}

健康目標：
{health_goal}

調理時間：
{cooking_time}

{retry_note}

最重要ルール：
・料理として自然でおいしいことを最優先してください。
・食品ロス削減よりも、おいしさ、食べやすさ、家族条件を優先してください。
・在庫食材をすべて使う必要はありません。
・相性が悪い食材は無理に使わないでください。
・使わない方がおいしくなる食材は「今回使わない在庫食材」に入れてください。
・奇抜な創作料理や実験的な料理は提案しないでください。
・家庭で普通に食べられる献立にしてください。

食材の相性ルール：
・甘い果物は夕食の主菜、炒め物、サンドイッチ、スープ、煮物、茶碗蒸しに絶対に混ぜないでください。
・果物は献立の使用食材にせず、必要なら「今回使わない在庫食材」でデザート向きと説明してください。
・ブルーベリー、いちご、バナナ、りんご、みかんなどの果物を、肉、魚、きのこ、チーズ、トマト、卵と無理に組み合わせないでください。
・菓子、飲料、茶碗蒸しなどの調理済み食品は、料理の材料として混ぜないでください。
・料理名を見た時点でおいしそうと思えるものだけを提案してください。

禁止ルール：
・「献立に使わない在庫食材」は、料理名、使用する在庫食材、作り方、提案理由には使わないでください。
・ただし「今回使わない在庫食材」欄には、使わない理由として記載してください。
・使わない在庫食材を無理に使うくらいなら、買い足す食材を提案してください。
・料理として成立しない組み合わせを出さないでください。

調味料ルール：
・塩、こしょう、醤油、みそ、砂糖、酢、油、ごま油、みりん、酒、だし、コンソメ、マヨネーズ、ケチャップ、めんつゆは基本調味料として扱ってください。
・基本調味料は「買い足す食材」に入れないでください。
・使う基本調味料は「家庭にある前提の調味料」に書いてください。

出力ルール：
・HTMLタグを使わないでください。
・全体で600字以内にしてください。
・説明は各項目1行までにしてください。
・長い健康説明は不要です。
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


def show_item_editor(df, key):
    return st.data_editor(
        df,
        key=key,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "削除": st.column_config.CheckboxColumn("削除"),
            "登録判定": st.column_config.SelectboxColumn("登録判定", options=["登録する", "登録しない"]),
            "元の商品名": st.column_config.TextColumn("元の商品名"),
            "食材名": st.column_config.TextColumn("食材名"),
            "数量": st.column_config.TextColumn("数量"),
            "単位": st.column_config.SelectboxColumn("単位", options=UNIT_OPTIONS),
            "カテゴリ": st.column_config.SelectboxColumn("カテゴリ", options=CATEGORY_OPTIONS),
            "確認状態": st.column_config.SelectboxColumn("確認状態", options=["登録可能", "要確認"]),
        },
    )


receipt_text = st.text_area(
    "レシート内容",
    placeholder="レシートの商品名を1行ずつ入力してください\n例：\n卵\nキャベツ\n鶏むね肉",
)

if st.button("レシートを解析する"):
    if not receipt_text.strip():
        st.warning("レシート内容を入力してください。")
    else:
        try:
            with st.spinner("Difyでレシートを解析しています..."):
                result = call_dify(st.secrets["DIFY_API_KEY"], receipt_text, {"receipt_text": receipt_text, "レシート内容": receipt_text})
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

if not st.session_state.candidates:
    st.info("まだ在庫登録候補がありません。レシートを解析してください。")
else:
    edited_df = show_item_editor(pd.DataFrame(st.session_state.candidates), "candidate_editor")
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
                    "確認状態": str(row["確認状態"]),
                })
            st.session_state.inventory.extend(new_items)
            st.session_state.last_added_items = new_items
            st.success(f"{len(new_items)}件を在庫に登録しました。")
            st.rerun()

st.divider()
st.subheader("現在の在庫一覧")

if not st.session_state.inventory:
    st.info("まだ在庫は登録されていません。")
else:
    inventory_df = pd.DataFrame(st.session_state.inventory)
    inventory_df.insert(0, "削除", False)
    edited_inventory_df = show_item_editor(inventory_df, "inventory_editor")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("在庫一覧の編集を保存する"):
            kept_df = edited_inventory_df[edited_inventory_df["削除"] == False].drop(columns=["削除"])
            st.session_state.inventory = kept_df.to_dict("records")
            st.success("在庫一覧を更新しました。")
            st.rerun()

    with col2:
        if st.button("直前の在庫登録を取り消す"):
            if not st.session_state.last_added_items:
                st.warning("取り消せる直前登録がありません。")
            else:
                remove_count = len(st.session_state.last_added_items)
                st.session_state.inventory = st.session_state.inventory[:-remove_count]
                st.session_state.last_added_items = []
                st.success("直前の登録を取り消しました。")
                st.rerun()

st.divider()
st.subheader("献立提案")

st.session_state.family_profile = st.text_area("家族条件", value=st.session_state.family_profile, placeholder="例：大人2人、子ども1人。子どもは辛いものが苦手。")
st.session_state.avoid_foods = st.text_input("避ける食材・避ける条件", value=st.session_state.avoid_foods, placeholder="例：辛いもの、えび、そば")
st.session_state.health_goal = st.text_input("健康目標", value=st.session_state.health_goal, placeholder="例：野菜多め、塩分控えめ")
st.session_state.cooking_time = st.text_input("調理時間", value=st.session_state.cooking_time, placeholder="例：30分以内")

if st.button("家族条件を保存する"):
    st.success("家族条件を保存しました。このセッション中は保持されます。")

if st.button("献立を提案する"):
    usable_inventory, excluded_inventory = split_inventory_for_recipe(
        st.session_state.inventory,
        st.session_state.family_profile,
        st.session_state.avoid_foods,
        st.session_state.health_goal,
    )
    st.session_state.excluded_inventory = excluded_inventory
    usable_inventory_text = inventory_to_text(usable_inventory)
    excluded_inventory_text = excluded_to_text(excluded_inventory)

    if not usable_inventory_text:
        st.warning("条件に合う在庫食材がありません。避ける条件を確認するか、買い足す食材を中心に提案してください。")
    else:
        if excluded_inventory_text:
            st.info("条件に合わない、または料理に混ぜない方がよいため、献立AIに使わせない在庫食材：\n" + excluded_inventory_text)

        recipe_query = build_recipe_query(
            usable_inventory_text,
            excluded_inventory_text,
            st.session_state.family_profile,
            st.session_state.avoid_foods,
            st.session_state.health_goal,
            st.session_state.cooking_time,
        )
        recipe_inputs = {
            "inventory": usable_inventory_text,
            "在庫一覧": usable_inventory_text,
            "excluded_inventory": excluded_inventory_text,
            "使用禁止の在庫食材": excluded_inventory_text,
            "family_profile": st.session_state.family_profile,
            "家族条件": st.session_state.family_profile,
            "avoid_foods": st.session_state.avoid_foods,
            "避ける食材": st.session_state.avoid_foods,
            "health_goal": st.session_state.health_goal,
            "健康目標": st.session_state.health_goal,
            "cooking_time": st.session_state.cooking_time,
            "調理時間": st.session_state.cooking_time,
        }

        try:
            with st.spinner("Difyで献立を提案しています..."):
                result = call_dify(st.secrets["RECIPE_API_KEY"], recipe_query, recipe_inputs)
            answer = strip_html(get_answer(result))
            used_forbidden = answer_uses_excluded_item(answer, excluded_inventory)

            if used_forbidden:
                retry_note = "重要：前回の提案では献立に使わない食材を料理に入れました。今回は次の食材を料理名、使用食材、作り方、提案理由に絶対に使わないでください：" + "、".join(used_forbidden)
                retry_query = build_recipe_query(
                    usable_inventory_text,
                    excluded_inventory_text,
                    st.session_state.family_profile,
                    st.session_state.avoid_foods,
                    st.session_state.health_goal,
                    st.session_state.cooking_time,
                    retry_note,
                )
                with st.spinner("条件違反があったため、再提案しています..."):
                    retry_result = call_dify(st.secrets["RECIPE_API_KEY"], retry_query, recipe_inputs)
                answer = strip_html(get_answer(retry_result))
                used_forbidden = answer_uses_excluded_item(answer, excluded_inventory)

            if used_forbidden:
                st.error("提案結果が避ける条件に反しています。使用禁止食材が含まれています：" + "、".join(used_forbidden))
                st.session_state.recipe_answer = ""
            else:
                st.session_state.recipe_answer = answer
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
    if not st.session_state.inventory:
        st.info("在庫がありません。")
    else:
        consumption_df = pd.DataFrame(st.session_state.inventory)
        consumption_df.insert(0, "削除", False)
        edited_consumption_df = show_item_editor(consumption_df, "consumption_editor")
        if st.button("作った後の在庫更新を保存する"):
            updated_df = edited_consumption_df[edited_consumption_df["削除"] == False].drop(columns=["削除"])
            st.session_state.inventory = updated_df.to_dict("records")
            st.session_state.show_consumption_editor = False
            st.success("作った後の在庫を更新しました。")
            st.rerun()
