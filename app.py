import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import random
import requests
import streamlit as st

# =============================================================================
# НАСТРОЙКИ И КОНФИГУРАЦИЯ
# =============================================================================
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbydDX0UgH_Bx_C7ZEE2fpEa_JM30nVIfl9Mum6rytzEtXFm5VoNfBnQo0RoeZGVucs3jg/exec"

AI_API_KEYS = [
    "AIzaSyDuvBCO2Dklp9zppJsIdmXD8meWxDYO9go",
    "AIzaSyCX9ESLn_jM4gOgSHzfmaYXc6Zz1eXQGbg",
]

AI_SYSTEM_PROMPT = (
    "Ты — ведущий эксперт по истории России, искусствовед и составитель заданий ЕГЭ. "
    "Проанализируй присланное изображение (плакат, монета, марка, картина, скульптура) "
    "и верни ТОЛЬКО его общепринятое точное историческое название "
    "(например: 'Церковь Покрова на Нерли', 'Боярыня Морозова', 'Плакат «Родина-мать зовет!»', 'Медный всадник'). "
    "Отвечай СТРОГО только одним названием без вводных слов, точек на конце и внешних кавычек."
)

st.set_page_config(
    page_title="Массовый Банк Изображений ENL", page_icon="🖼️", layout="wide"
)

st.title("🖼️ Загрузчик и ИИ-Распознаватель изображений | енл")
st.write(
    "Загрузите пачку картинок ➔ Запустите ИИ-распознавание ➔ Проверьте/отредактируйте названия ➔ Сохраните в Google Таблицу!"
)


# =============================================================================
# ФУНКЦИИ ОБРАБОТКИ С ВЫВОДОМ ОШИБОК GOOGLE
# =============================================================================
def get_ai_title(file_bytes: bytes, mime_type: str) -> tuple[str, str]:
    """Обращается к Gemini API и возвращает имя ИЛИ прозрачную ошибку от Google."""
    base64_data = base64.b64encode(file_bytes).decode("utf-8")

    clean_mime = (
        mime_type
        if mime_type in ["image/jpeg", "image/png", "image/webp"]
        else "image/jpeg"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            f"{AI_SYSTEM_PROMPT}\n\nНазови точное историческое название"
                            " этого объекта:"
                        )
                    },
                    {"inlineData": {"mimeType": clean_mime, "data": base64_data}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1},
    }

    models = ["gemini-3.5-flash-lite"]
    shuffled_keys = AI_API_KEYS.copy()
    random.shuffle(shuffled_keys)

    last_error = ""

    for api_key in shuffled_keys:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=25,
                )
                if response.status_code == 200:
                    res_json = response.json()
                    candidates = res_json.get("candidates", [])
                    if candidates:
                        parts = (
                            candidates[0]
                            .get("content", {})
                            .get("parts", [])
                        )
                        if parts:
                            text = parts[0].get("text", "")
                            clean_title = (
                                text.strip()
                                .strip('"')
                                .strip("'")
                                .strip("`")
                            )
                            if clean_title:
                                return clean_title, "✅ Распознано ИИ"
                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:150]}"
            except Exception as e:
                last_error = f"Сетевая ошибка: {str(e)}"
                continue

    return "", f"⚠️ Ошибка Gemini ({last_error if last_error else 'Нет ответа'})"


def upload_single_file(
    file_bytes: bytes, full_filename: str, mime_type: str, replace_flag: bool
):
    """Отправляет готовый файл и название на Google Вебхук."""
    base64_file = base64.b64encode(file_bytes).decode("utf-8")

    payload = {
        "fileName": full_filename,
        "fileBase64": base64_file,
        "mimeType": mime_type,
        "replaceExisting": replace_flag,
    }

    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=60)
        res = response.json()
        if res.get("status") == "success":
            return {
                "Файл / Название": full_filename,
                "Статус": "Успешно",
                "Действие": (
                    "Создан новый"
                    if res.get("action") == "created"
                    else "Обновлен"
                ),
                "ID": res.get("entityId"),
                "Связанные таски": res.get("tasks", ""),
                "Ссылка": res.get("fileUrl"),
            }
        else:
            return {
                "Файл / Название": full_filename,
                "Статус": "Ошибка",
                "Детали": res.get("message"),
            }
    except Exception as e:
        return {
            "Файл / Название": full_filename,
            "Статус": "Ошибка",
            "Детали": str(e),
        }


# =============================================================================
# ИНТЕРФЕЙС И СОСТОЯНИЕ (SESSION STATE)
# =============================================================================
if "items_data" not in st.session_state:
    st.session_state["items_data"] = []

# 1. Загрузка файлов
uploaded_files = st.file_uploader(
    "Выберите или перетащите картинки (до 50-100 штук)",
    type=["webp", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

replace_existing = st.checkbox(
    "Заменять картинку и обновлять ссылку, если такое Название уже есть в таблице (ID сохранится)",
    value=True,
)

# Запись новых файлов в состояние
if uploaded_files:
    current_filenames = [
        item["original_name"] for item in st.session_state["items_data"]
    ]
    for file in uploaded_files:
        if file.name not in current_filenames:
            base_name, ext = os.path.splitext(file.name)
            item_id = len(st.session_state["items_data"])
            st.session_state["items_data"].append(
                {
                    "id": item_id,
                    "original_name": file.name,
                    "base_name": base_name,
                    "ext": ext,
                    "bytes": file.read(),
                    "mime_type": file.type or "image/jpeg",
                    "ai_title": "",
                    "status": "⏳ Ожидает распознавания",
                }
            )

st.divider()

# =============================================================================
# СЧЕТЧИКИ И ПРОГРЕСС-БАР ИИ
# =============================================================================
if st.session_state["items_data"]:
    total_count = len(st.session_state["items_data"])
    ai_done_count = sum(
        1 for item in st.session_state["items_data"] if item["ai_title"]
    )
    pending_count = total_count - ai_done_count

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("📊 Всего картинок", total_count)
    col_m2.metric("✅ Распознано ИИ", f"{ai_done_count} из {total_count}")
    col_m3.metric("⏳ Ожидает распознавания", pending_count)

    ai_status_box = st.empty()
    ai_progress_box = st.empty()

    if pending_count > 0:
        if st.button("🤖 1. Распознать названия с помощью ИИ", type="secondary"):
            progress_bar = ai_progress_box.progress(0)

            def process_ai(item):
                if not item["ai_title"]:
                    title, status_str = get_ai_title(
                        item["bytes"], item["mime_type"]
                    )
                    if title:
                        item["ai_title"] = title
                        item["status"] = status_str
                    else:
                        item["ai_title"] = item["base_name"]
                        item["status"] = status_str

                    widget_key = f"input_{item['id']}_{item['original_name']}"
                    st.session_state[widget_key] = item["ai_title"]
                return item

            completed = 0
            # 1 поток для поштучной отладки
            with ThreadPoolExecutor(max_workers=1) as executor:
                futures = [
                    executor.submit(process_ai, item)
                    for item in st.session_state["items_data"]
                ]
                for future in as_completed(futures):
                    future.result()
                    completed += 1
                    percent = int((completed / total_count) * 100)
                    ai_status_box.info(
                        f"🧠 ИИ обработал: **{completed} из {total_count}**"
                        f" картинок ({percent}%)"
                    )
                    progress_bar.progress(completed / total_count)

            # Автоматическая уникализация
            title_counts = {}
            for item in st.session_state["items_data"]:
                t = item["ai_title"]
                if t in title_counts:
                    title_counts[t] += 1
                    item["ai_title"] = f"{t}_{title_counts[t]}"
                else:
                    title_counts[t] = 1

                widget_key = f"input_{item['id']}_{item['original_name']}"
                st.session_state[widget_key] = item["ai_title"]

            ai_status_box.success("🎉 Обработка завершена!")
            st.rerun()

    # =========================================================================
    # ПРЕДПРОСМОТР, ПРОВЕРКА И РЕДАКТИРОВАНИЕ
    # =========================================================================
    st.subheader("👁️ Проверка и редактирование названий")
    st.info(
        "Вы можете изменить любое название. "
        "Чтобы привязать задания к картинке, добавьте их в скобках: `Аленушка [101, 102]`"
    )

    final_upload_list = []
    entered_titles = []

    cols = st.columns(3)
    for idx, item in enumerate(st.session_state["items_data"]):
        col = cols[idx % 3]
        widget_key = f"input_{item['id']}_{item['original_name']}"

        if widget_key not in st.session_state:
            st.session_state[widget_key] = (
                item["ai_title"] if item["ai_title"] else item["base_name"]
            )

        with col:
            with st.container(border=True):
                st.caption(
                    f"Файл: `{item['original_name']}` | Статус: **{item['status']}**"
                )
                st.image(item["bytes"], use_column_width=True)

                edited_title = st.text_input(
                    f"Название #{idx+1}:",
                    key=widget_key,
                )

                if edited_title.strip() in entered_titles:
                    st.warning("⚠️ Такое название уже есть выше!")
                else:
                    entered_titles.append(edited_title.strip())

                selected = st.checkbox(
                    "Загрузить файл",
                    value=True,
                    key=f"check_{item['id']}_{item['original_name']}",
                )

                if selected and edited_title.strip():
                    full_filename = f"{edited_title.strip()}{item['ext']}"
                    final_upload_list.append(
                        {
                            "bytes": item["bytes"],
                            "full_filename": full_filename,
                            "mime_type": item["mime_type"],
                        }
                    )

    st.divider()

    # =========================================================================
    # КНОПКА 2: МАССОВАЯ ЗАГРУЗКА НА ВЕБХУК В GOOGLE
    # =========================================================================
    if final_upload_list:
        if st.button(
            f"🚀 2. Загрузить выбранные ({len(final_upload_list)} шт.) в Google Диск и Таблицу",
            type="primary",
        ):
            drive_status_box = st.empty()
            drive_progress_box = st.empty()
            progress_bar_drive = drive_progress_box.progress(0)

            results = []
            completed = 0
            total = len(final_upload_list)

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(
                        upload_single_file,
                        file_item["bytes"],
                        file_item["full_filename"],
                        file_item["mime_type"],
                        replace_existing,
                    )
                    for file_item in final_upload_list
                ]

                for future in as_completed(futures):
                    res = future.result()
                    results.append(res)
                    completed += 1
                    percent = int((completed / total) * 100)
                    drive_status_box.info(
                        f"📤 Отправка в Google: **{completed} из {total}**"
                        f" файлов ({percent}%)"
                    )
                    progress_bar_drive.progress(completed / total)

            drive_status_box.success(
                "🎉 Все выбранные файлы успешно отправлены и сохранены на Google"
                " Диск!"
            )
            st.dataframe(results, use_container_width=True)
else:
    st.info("👆 Загрузите файлы в блоке выше, чтобы начать работу.")
