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
    "Проанализируй присланное изображение и верни ТОЛЬКО его общепринятое точное историческое название "
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
# ФУНКЦИИ ОБРАБОТКИ
# =============================================================================
def get_ai_title(file_bytes: bytes, mime_type: str) -> str:
    """Обращается к Gemini API с ротацией ключей и фоллбэком."""
    base64_data = base64.b64encode(file_bytes).decode("utf-8")

    payload = {
        "system_instruction": {"parts": [{"text": AI_SYSTEM_PROMPT}]},
        "contents": [
            {
                "parts": [
                    {"text": "Назови исторический объект на изображении:"},
                    {"inlineData": {"mimeType": mime_type, "data": base64_data}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1},
    }

    models = ["gemini-3.5-flash-lite"]
    shuffled_keys = AI_API_KEYS.copy()
    random.shuffle(shuffled_keys)

    for api_key in shuffled_keys:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                response = requests.post(url, json=payload, timeout=20)
                if response.status_code == 200:
                    res_json = response.json()
                    candidates = res_json.get("candidates", [])
                    if candidates:
                        text = candidates[0]["content"]["parts"][0]["text"]
                        clean_title = text.strip().strip('"').strip("'")
                        if clean_title:
                            return clean_title
            except Exception:
                continue

    return ""


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

# Запись загруженных файлов в состояние
if uploaded_files:
    current_filenames = [
        item["original_name"] for item in st.session_state["items_data"]
    ]
    for file in uploaded_files:
        if file.name not in current_filenames:
            base_name, ext = os.path.splitext(file.name)
            st.session_state["items_data"].append(
                {
                    "id": len(st.session_state["items_data"]),
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
# КНОПКА 1: ИИ-РАСПОЗНАВАНИЕ
# =============================================================================
if st.session_state["items_data"]:
    st.subheader(f"📋 Файлов к обработке: {len(st.session_state['items_data'])}")

    if st.button("🤖 1. Распознать названия с помощью ИИ", type="secondary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        total = len(st.session_state["items_data"])

        def process_ai(item):
            if not item["ai_title"]:
                item["status"] = "🔄 ИИ обрабатывает..."
                title = get_ai_title(item["bytes"], item["mime_type"])
                if title:
                    item["ai_title"] = title
                    item["status"] = "✅ Распознано ИИ"
                else:
                    item["ai_title"] = item["base_name"]
                    item["status"] = "⚠️ Имя по умолчанию"
            return item

        completed = 0
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(process_ai, item)
                for item in st.session_state["items_data"]
            ]
            for future in as_completed(futures):
                future.result()
                completed += 1
                status_text.text(
                    f"ИИ распознает: {completed} из {total} картинок..."
                )
                progress_bar.progress(completed / total)

        # Автоматическая уникализация совпадающих названий (например: Аленушка_2)
        title_counts = {}
        for item in st.session_state["items_data"]:
            t = item["ai_title"]
            if t in title_counts:
                title_counts[t] += 1
                item["ai_title"] = f"{t}_{title_counts[t]}"
                item["status"] = "⚠️ Дубликат (переименовано)"
            else:
                title_counts[t] = 1

        status_text.empty()
        progress_bar.empty()
        st.success("🎉 ИИ завершил обработку! Все дубликаты пронумерованы.")
        st.rerun()

    # =========================================================================
    # 2. ПРЕДПРОСМОТР, ПРОВЕРКА И РЕДАКТИРОВАНИЕ
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
        with col:
            with st.container(border=True):
                # Статус-бейдж
                st.caption(f"Файл: `{item['original_name']}` | Статус: **{item['status']}**")
                st.image(
                    item["bytes"], use_column_width=True
                )

                default_title = (
                    item["ai_title"] if item["ai_title"] else item["base_name"]
                )
                
                edited_title = st.text_input(
                    f"Название #{idx+1}:",
                    value=default_title,
                    key=f"input_{item['id']}_{item['original_name']}",
                )

                # Проверка на совпадение в реальном времени
                if edited_title.strip() in entered_titles:
                    st.warning("⚠️ Такое название уже есть выше! Уточните его, чтобы не перезаписать файл.")
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
    # КНОПКА 2: МАССОВАЯ ЗАГРУЗКА НА ВЕБХУК
    # =========================================================================
    if final_upload_list:
        if st.button(
            f"🚀 2. Загрузить выбранные ({len(final_upload_list)} шт.) в Google Диск и Таблицу",
            type="primary",
        ):
            progress_bar = st.progress(0)
            status_text = st.empty()

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
                    status_text.text(
                        f"Отправка в Google: {completed} из {total}..."
                    )
                    progress_bar.progress(completed / total)

            status_text.empty()
            progress_bar.empty()
            st.success("🎉 Все файлы успешно отправлены и сохранены!")
            st.dataframe(results, use_container_width=True)
else:
    st.info("👆 Загрузите файлы в блоке выше, чтобы начать работу.")
