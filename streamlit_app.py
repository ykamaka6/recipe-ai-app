import re
import requests
import pandas as pd
import streamlit as st

st.title("AI献立提案アプリ")
st.write("レシート内容を入力し、AIの解析結果を確認・修正して在庫登録します。")

CATEGORY_OPTIONS = [
    "主食・穀物",
    "肉・魚",
    "卵",
    "乳製品",
    "大豆製品",
    "調理済み食品",
    "調味料",
    "加工品・チルド食品",
    "菓子・スイーツ",
    "野菜・果物",
    "飲料",
    "その他食品",
]

UNIT_OPTIONS = ["個", "袋", "パック", "本", "玉", "束", "g", "kg", "不明"]

SPICY_KEYWORDS = [
    "キムチ", "唐辛子", "とうがらし", "七味", "一味", "豆板醤", "ラー油",
    "コチュジャン", "チリ", "タバスコ", "カレー粉", "カレールー", "辛口",
    "わさび", "からし", "マスタード", "スパイシー"
]

BITTER_KEYWORDS = ["ゴーヤ", "春菊", "セロリ", "ピーマン"]
HARD_KEYWORDS = ["するめ", "硬い肉", "牛すじ"]
FATTY_KEYWORDS = ["バラ肉", "豚バラ", "脂身", "揚げ物"]

FRUIT_KEYWORDS = [
    "ブルーベリー", "いちご", "苺", "バナナ", "りんご", "リンゴ", "林檎",
    "みかん", "オレンジ", "ぶどう", "葡萄", "キウイ", "桃", "もも",
    "梨", "パイン", "パイナップル", "マンゴー", "メロン",
    "すいか", "スイカ", "柿", "レモン", "グレープフルーツ"
]

NON_COOKING_CATEGORIES = ["調理済み食品", "菓子・スイーツ", "飲料"]

for key, default_value in {
    "candidates": [],
    "inventory": [],
    "ai_answer": "",
    "recipe_answer": "",
    "family_profile": "",
    "avoid_foods": "",
    "health_goal": "",
    "cooking_time": "",
    "last_added_items": [],
    "show_consumption_editor": False,
    "excluded_inventory": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default_value


def call_dify(api_key, query, inputs=None):
    url = st.secrets["DIFY_API_URL"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "inputs": inputs or {},
        "query": query,
        "response_mode": "blocking",
        "user": "demo-user",
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

    html_breaks = [
        "&lt;br&gt;",
        "&lt;br/&gt;",
        "&lt;br /&gt;",
        "<br>",
        "<br/>",
        "<br />",
    ]

    for tag in html_breaks:
        text = text.replace(tag, "\n")

    text = text.replace("&lt;/li&gt;", "\n")
    text = re.sub(r"&lt;li[^&gt;]*&gt;", "・", text)
    text = re.sub(r"&lt;[^&gt;]+&gt;", "", text)
    text = re.sub(r"<[^>]+>", "", text)

    return text.strip()


def text_contains_any(text, keywords):
    target = str(text).lower()
    return any(str(keyword).lower() in target for keyword in keywords)


def normalize_category(category):
    value = str(category).strip()

    category_map = {
        "主食": "主食・穀物",
        "穀物": "主食・穀物",
        "肉": "肉・魚",
        "魚": "肉・魚",
        "野菜": "野菜・果物",
        "果物": "野菜・果物",
        "菓子": "菓子・スイーツ",
        "発酵食品": "加工品・チルド食品",
        "加工食品": "加工品・チルド食品",
        "チルド食品": "加工品・チルド食品",
    }

    if value in CATEGORY_OPTIONS:
        return value

    return category_map.get(value, "その他食品")


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
        "ユーザー確認",
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

    suspicious_markers = [
        "または",
        "不明",
        "推測",
        "候補",
        "?",
        "？",
        "（中）",
        "(中)",
        "低確信度",
    ]

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
            "カテゴリ": normalize_category(category),
            "確認状態": confirm_status,
        })

    return candidates


def get_avoid_flags(family_profile, avoid_foods, health_goal):
    condition_text = f"{family_profile}\n{avoid_foods}\n{health_goal}"

    return {
        "spicy": text_contains_any(condition_text, ["辛い", "辛味", "からい", "スパイシー", "刺激物"]),
        "bitter": text_contains_any(condition_text, ["苦い", "苦味"]),
        "hard": text_contains_any(condition_text, ["硬い", "かたい", "噛みにくい"]),
        "fatty": text_contains_any(condition_text, ["脂っこい", "油っこい", "脂質控えめ"]),
        "salt": text_contains_any(condition_text, ["塩分控えめ", "減塩", "低塩"]),
    }


def should_exclude_item(item, flags, avoid_foods):
    food_name = str(item.get("食材名", ""))
    category = str(item.get("カテゴリ", ""))
    reasons = []

    avoid_terms = [
        term.strip()
        for term in re.split(r"[,、\n]", str(avoid_foods))
        if term.strip()
    ]

    for term in avoid_terms:
        if term and term in food_name:
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

    usable = []
    excluded = []

    for item in inventory_list:
        reasons = should_exclude_item(item, flags, avoid_foods)

        if reasons:
            excluded.append({
                **item,
                "除外理由": " / ".join(reasons),
            })
        else:
            usable.append(item)

    return usable, excluded


def inventory_to_text(inventory_list):
    lines = []

    for item in inventory_list:
        lines.append(
            f"{item.get('食材名', '')} {item.get('数量', '')}{item.get('単位', '')} カテゴリ:{item.get('カテゴリ', '')}"
        )

    return "\n".join(lines)


def excluded_to_text(excluded_list):
    lines = []

    for item in excluded_list:
        lines.append(
            f"{item.get('食材名', '')}：{item.get('除外理由', '')}"
        )

    return "\n".join(lines)


def get_answer_section(answer, start_label, next_labels):
    text = strip_html(answer)

    pattern = rf"{re.escape(start_label)}\s*(.*?)(?=" + "|".join(
        [re.escape(label) for label in next_labels]
    ) + r"|$)"

    match = re.search(pattern, text, flags=re.DOTALL)

    if match:
        return match.group(1).strip()

    return ""


def count_used_inventory_items(answer):
    section = get_answer_section(
        answer,
        "使用する在庫食材：",
        [
            "今回使わない在庫食材：",
            "買い足す食材：",
            "家庭にある前提の調味料：",
            "作り方：",
            "提案理由：",
            "食品ロス削減：",
            "健康補助：",
        ],
    )

    lines = [
        line.strip()
        for line in section.splitlines()
        if line.strip().startswith("・")
    ]

    return len(lines)


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


def answer_has_bad_recipe(answer):
    text = strip_html(answer)
    reasons = []

    used_count = count_used_inventory_items(text)

    if used_count > 4:
        reasons.append("使用する在庫食材が多すぎます。食材を無理に使いすぎています。")

    if "こんにゃく" in text and ("揚げ" in text or "天ぷら" in text or "てんぷら" in text):
        reasons.append("こんにゃくを揚げ物や天ぷらにする提案は不自然です。")

    if "大根" in text and ("大根を揚げ" in text or ("大根" in text and "揚げ" in text)):
        reasons.append("大根を揚げ物の中心にする提案は避けてください。")

    if "チーズ" in text and text_contains_any(text, ["わかめ", "こんにゃく", "タコ", "たこ"]):
        reasons.append("チーズと、わかめ・こんにゃく・タコを同じ料理に混ぜる提案は不自然です。")

    if "トマト" in text and text_contains_any(text, ["わかめ", "こんにゃく", "天ぷら", "てんぷら", "茶碗蒸し"]):
        reasons.append("トマトと、わかめ・こんにゃく・天ぷら・茶碗蒸し系を混ぜる提案は不自然です。")

    if "丼" in text and used_count > 4:
        reasons.append("丼に在庫食材を大量にのせる提案は不自然です。")

    if "トッピング" in text and used_count > 4:
        reasons.append("トッピングとして食材を大量に組み合わせる提案は不自然です。")

    if text_contains_any(text, FRUIT_KEYWORDS) and text_contains_any(text, ["肉", "魚", "きのこ", "しいたけ", "シイタケ", "チーズ", "卵", "丼", "茶碗蒸し"]):
        reasons.append("甘い果物を主菜や丼、卵料理に混ぜる提案は不自然です。")

    if "茶碗蒸し" in text and text_contains_any(text, ["ブルーベリー", "チーズ", "トマト"]):
        reasons.append("茶碗蒸しにブルーベリー・チーズ・トマトを入れる提案は不自然です。")

    if "丼" in text and text_contains_any(text, ["チーズ", "わかめ", "こんにゃく", "トマト", "タコ", "たこ"]) and used_count >= 4:
        reasons.append("丼にチーズ・わかめ・こんにゃく・トマト・タコなどを雑に組み合わせる提案は不自然です。")

    return reasons


def build_recipe_query(
    usable_inventory_text,
    excluded_inventory_text,
    family_profile,
    avoid_foods,
    health_goal,
    cooking_time,
    retry_note="",
):
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
・使用する在庫食材は最大4つまでにしてください。
・在庫食材をすべて使う必要はありません。
・相性が悪い食材は絶対に使わないでください。
・使わない方がおいしくなる食材は「今回使わない在庫食材」に入れてください。
・奇抜な創作料理や実験的な料理は提案しないでください。
・家庭で普通に食べられる献立にしてください。
・丼、炒め物、スープ、茶碗蒸し、サンドイッチに、在庫食材を何でも入れる提案は禁止です。

食材の相性ルール：
・甘い果物は夕食の主菜、炒め物、サンドイッチ、スープ、煮物、丼、茶碗蒸しに絶対に混ぜないでください。
・果物は献立の使用食材にせず、必要なら「今回使わない在庫食材」でデザート向きと説明してください。
・こんにゃくは揚げ物、天ぷら、丼のメイン具材にしないでください。
・わかめは味噌汁、酢の物、スープ以外では無理に使わないでください。
・チーズは、わかめ、こんにゃく、タコ、大根、小松菜と無理に組み合わせないでください。
・トマトは、天ぷら、茶碗蒸し、こんにゃく、わかめと組み合わせないでください。
・ベーコン、チーズ、トマトを使うなら洋風にまとめてください。
・しいたけ、小松菜、ねぎ、大根、こんにゃくを使うなら和風にまとめてください。
・和風食材と洋風食材を無理に混ぜないでください。
・料理名を見た時点でおいしそうと思えるものだけを提案してください。

禁止ルール：
・「献立に使わない在庫食材」は、料理名、使用する在庫食材、作り方、提案理由には使わないでください。
・ただし「今回使わない在庫食材」欄には、使わない理由として記載してください。
・使わない在庫食材を無理に使うくらいなら、買い足す食材を提案してください。
・料理として成立しない組み合わせを出さないでください。
・トッピングとして余った食材を大量にのせる提案はしないでください。
・丼に何でものせる提案はしないでください。
・こんにゃく、大根、わかめ、チーズ、トマト、タコを無理に同じ献立へ入れないでください。

調味料ルール：
・塩、こしょう、醤油、みそ、砂糖、酢、油、ごま油、みりん、酒、だし、コンソメ、マヨネーズ、ケチャップ、めんつゆは基本調味料として扱ってください。
・基本調味料は「買い足す食材」に入れないでください。
・使う基本調味料は「家庭にある前提の調味料」に書いてください。

出力前チェック：
以下を満たす献立だけを出力してください。
・使用する在庫食材は最大4つである
・家庭料理として自然である
・食材の味の相性がよい
・甘い果物を不自然に主菜へ混ぜていない
・こんにゃくを揚げていない
・丼やトッピングに食材を大量にのせていない
・和風と洋風を無理に混ぜていない
・実際に食べたいと思える料理である

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
            "登録判定": st.column_config.SelectboxColumn(
                "登録判定",
                options=["登録する", "登録しない"],
            ),
            "元の商品名": st.column_config.TextColumn("元の商品名"),
            "食材名": st.column_config.TextColumn("食材名"),
            "数量": st.column_config.TextColumn("数量"),
            "単位": st.column_config.SelectboxColumn("単位", options=UNIT_OPTIONS),
            "カテゴリ": st.column_config.SelectboxColumn("カテゴリ", options=CATEGORY_OPTIONS),
            "確認状態": st.column_config.SelectboxColumn(
                "確認状態",
                options=["登録可能", "要確認"],
            ),
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
                result = call_dify(
                    st.secrets["DIFY_API_KEY"],
                    receipt_text,
                    {
                        "receipt_text": receipt_text,
                        "レシート内容": receipt_text,
                    },
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

    edited_df = show_item_editor(candidate_df, "candidate_editor")

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

if len(st.session_state.inventory) == 0:
    st.info("まだ在庫は登録されていません。")
else:
    inventory_df = pd.DataFrame(st.session_state.inventory)
    inventory_df.insert(0, "削除", False)

    edited_inventory_df = show_item_editor(inventory_df, "inventory_editor")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("在庫一覧の編集を保存する"):
            kept_df = edited_inventory_df[
                edited_inventory_df["削除"] == False
            ].drop(columns=["削除"])

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
    placeholder="例：大人2人、子ども1人。子どもは辛いものが苦手。",
)

st.session_state.avoid_foods = st.text_input(
    "避ける食材・避ける条件",
    value=st.session_state.avoid_foods,
    placeholder="例：辛いもの、えび、そば",
)

st.session_state.health_goal = st.text_input(
    "健康目標",
    value=st.session_state.health_goal,
    placeholder="例：野菜多め、塩分控えめ",
)

st.session_state.cooking_time = st.text_input(
    "調理時間",
    value=st.session_state.cooking_time,
    placeholder="例：30分以内",
)

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
                result = call_dify(
                    st.secrets["RECIPE_API_KEY"],
                    recipe_query,
                    recipe_inputs,
                )

            answer = strip_html(get_answer(result))
            used_forbidden = answer_uses_excluded_item(answer, excluded_inventory)
            bad_reasons = answer_has_bad_recipe(answer)

            if used_forbidden or bad_reasons:
                retry_note = "重要：前回の提案は不自然でした。"

                if used_forbidden:
                    retry_note += " 次の食材は料理名、使用食材、作り方、提案理由に絶対に使わないでください：" + "、".join(used_forbidden)

                if bad_reasons:
                    retry_note += " 前回の問題点：" + " / ".join(bad_reasons)

                retry_note += """
今回は以下を必ず守ってください。
・使用する在庫食材は最大4つまで。
・丼やトッピングに食材を大量にのせない。
・こんにゃくを揚げない。
・わかめ、こんにゃく、チーズ、トマト、タコを無理に同じ料理へ入れない。
・和風なら和風、洋風なら洋風で味をまとめる。
・食べておいしい家庭料理だけを提案する。
"""

                retry_query = build_recipe_query(
                    usable_inventory_text,
                    excluded_inventory_text,
                    st.session_state.family_profile,
                    st.session_state.avoid_foods,
                    st.session_state.health_goal,
                    st.session_state.cooking_time,
                    retry_note,
                )

                with st.spinner("不自然な献立だったため、再提案しています..."):
                    retry_result = call_dify(
                        st.secrets["RECIPE_API_KEY"],
                        retry_query,
                        recipe_inputs,
                    )

                answer = strip_html(get_answer(retry_result))
                used_forbidden = answer_uses_excluded_item(answer, excluded_inventory)
                bad_reasons = answer_has_bad_recipe(answer)

            if used_forbidden or bad_reasons:
                error_message = "提案結果が不自然、または避ける条件に反しています。"

                if used_forbidden:
                    error_message += "\n使用禁止食材：" + "、".join(used_forbidden)

                if bad_reasons:
                    error_message += "\n不自然な理由：" + " / ".join(bad_reasons)

                st.error(error_message)
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

    if len(st.session_state.inventory) == 0:
        st.info("在庫がありません。")
    else:
        consumption_df = pd.DataFrame(st.session_state.inventory)
        consumption_df.insert(0, "削除", False)

        edited_consumption_df = show_item_editor(consumption_df, "consumption_editor")

        if st.button("作った後の在庫更新を保存する"):
            updated_df = edited_consumption_df[
                edited_consumption_df["削除"] == False
            ].drop(columns=["削除"])

            st.session_state.inventory = updated_df.to_dict("records")
            st.session_state.show_consumption_editor = False
            st.success("作った後の在庫を更新しました。")
            st.rerun()
