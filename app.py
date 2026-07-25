import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import streamlit as st

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbydDX0UgH_Bx_C7ZEE2fpEa_JM30nVIfl9Mum6rytzEtXFm5VoNfBnQo0RoeZGVucs3jg/exec"

st.set_page_config(
    page_title="Массовый Банк Изображений ENL", page_icon="🖼️", layout="wide"
)

st.title("📦 Массовый Загрузчик Изображений | ENL")
st.write(
    "Загрузите сразу пачку файлов. Картинки сохранятся на Google Диск, а в таблицу запишутся 6-значные ID."
)

# 1. Выбор файлов
uploaded_files = st.file_uploader(
    "Выберите или перетащите картинки (до 50-100 штук)",
    type=["webp", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

# 2. Настройка замен
replace_existing = st.checkbox(
    "Заменять картинку и обновлять ссылку, если имя файла уже есть (ID сохранится)",
    value=True,
)


def upload_single_file(file, replace_flag):
    file_bytes = file.read()
    base64_file = base64.b64encode(file_bytes).decode("utf-8")

    payload = {
        "fileName": file.name,
        "fileBase64": base64_file,
        "mimeType": file.type,
        "replaceExisting": replace_flag,
    }

    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=60)
        res = response.json()
        if res.get("status") == "success":
            return {
                "Файл": file.name,
                "Статус": "Успешно",
                "Действие": (
                    "Создан новый"
                    if res.get("action") == "created"
                    else "Обновлен"
                ),
                "ID": res.get("entityId"),
                "Ссылка": res.get("fileUrl"),
            }
        else:
            return {
                "Файл": file.name,
                "Статус": "Ошибка",
                "Детали": res.get("message"),
            }
    except Exception as e:
        return {"Файл": file.name, "Статус": "Ошибка", "Детали": str(e)}


if uploaded_files:
    st.info(f"Выбрано файлов: **{len(uploaded_files)}**")

    if st.button(
        f"🚀 Загрузить все ({len(uploaded_files)} шт.) в 10 потоков",
        type="primary",
    ):
        progress_bar = st.progress(0)
        status_text = st.empty()

        results = []
        completed = 0
        total = len(uploaded_files)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(upload_single_file, file, replace_existing)
                for file in uploaded_files
            ]

            for future in as_completed(futures):
                res = future.result()
                results.append(res)
                completed += 1

                status_text.text(
                    f"Загрузка: {completed} из {total} файлов..."
                )
                progress_bar.progress(completed / total)

        status_text.empty()
        st.success("🎉 Все файлы успешно обработаны!")
        st.dataframe(results, use_container_width=True)
