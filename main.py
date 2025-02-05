#!/usr/bin/env python3
import re
import requests
from flask import Flask, render_template_string, abort

app = Flask(__name__)

# URL, с которого будет скачиваться файл меню iPXE.
REMOTE_MENU_URL = "http://192.168.0.163:5000/menu"  # Замените на нужный URL

# Глобальные переменные для хранения данных меню, меток и переменных
MENU_TITLE = ""
MENU_ITEMS = []   # Список пунктов меню: dict с ключами 'key', 'label' и 'is_gap'
LABELS = {}       # Словарь: имя метки -> список строк (блок команд)
VARS = {}         # Словарь переменных из блока :variables

def fetch_menu_file(url):
    """
    Скачивает содержимое файла меню по указанному URL и возвращает список строк.
    """
    response = requests.get(url)
    response.raise_for_status()
    return response.text.splitlines()

def substitute_variables(text):
    """
    Выполняет подстановку переменных в строке.
    Ищет конструкции вида ${имя[:тип]} и заменяет их на значения из VARS.
    Особое условие: если переменная равна "space", подставляются 4 пробела.
    """
    pattern = re.compile(r'\$\{([^}:]+)(?::[^}]+)?\}')
    def repl(match):
        var_name = match.group(1)
        if var_name == "space":
            return "    "  # 4 пробела
        return VARS.get(var_name, match.group(0))
    return pattern.sub(repl, text)

def parse_labels(lines):
    """
    Разбивает входной список строк на блоки по меткам.
    Каждая метка начинается со строки, начинающейся с ':'.
    Возвращает словарь: label_name -> список строк (блок, включая строку с меткой).
    """
    labels = {}
    current_label = None
    block = []
    for line in lines:
        line = line.rstrip()
        if not line:
            continue

        # Если строка начинается с ":" — это новая метка
        if line.startswith(":"):
            # Сохраняем предыдущий блок, если он есть
            if current_label is not None:
                labels[current_label] = block
            # Получаем имя метки (без двоеточия)
            parts = line.split()
            current_label = parts[0][1:]
            block = [line]
        else:
            block.append(line)
    # Сохраняем последний блок
    if current_label is not None:
        labels[current_label] = block
    return labels

def process_variables():
    """
    Обрабатывает блок переменных (метка :variables) и заполняет словарь VARS.
    Для каждой строки вида:
        set имя[:тип] значение
    выполняется подстановка уже известных переменных в значение.
    """
    if "variables" not in LABELS:
        return
    for line in LABELS["variables"]:
        line = line.strip()
        if line.lower().startswith("set "):
            # Пример: set space:hex 20:20 или set space ${space:string}
            parts = line.split(maxsplit=2)
            if len(parts) < 3:
                continue
            var_full = parts[1]
            var_name = var_full.split(":")[0]
            value = parts[2]
            # Подставляем уже известные переменные (если есть)
            value = substitute_variables(value)
            if value == "20:20":
                value = "    "  # Заменяем 20:20 на 4 пробела
            VARS[var_name] = value

def parse_menu_label(block_lines):
    global MENU_TITLE, MENU_ITEMS
    MENU_TITLE = ""
    MENU_ITEMS = []
    re_menu = re.compile(r'^\s*menu\s+(.*)', re.IGNORECASE)
    re_item = re.compile(r'^\s*item\s+(?:(--gap)\s*(.*)|((\S+)\s+(.*)))', re.IGNORECASE)

    for line in block_lines:
        line = line.rstrip()
        if not line:
            continue
            
        if line.lstrip().lower().startswith("menu "):
            m = re_menu.match(line)
            if m:
                MENU_TITLE = substitute_variables(m.group(1))
        elif line.lstrip().lower().startswith("item"):
            m = re_item.match(line)
            if m:
                is_gap = bool(m.group(1))
                if is_gap:
                    label = m.group(2) if m.group(2) else ""
                    key = ""
                else:
                    key = m.group(4)
                    label = m.group(5)

                label = substitute_variables(label)
                if is_gap and not label.strip():
                    continue

                MENU_ITEMS.append({
                    'key': key,
                    'label': label,
                    'is_gap': is_gap
                })
        elif line.lstrip().lower().startswith("choose"):
            break


def load_menu():
    """
    Загружает меню iPXE с удалённого URL, разбивает его на блоки по меткам,
    обрабатывает переменные и парсит блок с меткой 'menu' для формирования меню.
    """
    global LABELS
    try:
        lines = fetch_menu_file(REMOTE_MENU_URL)
        LABELS = parse_labels(lines)
        # Сначала обработаем переменные, если есть блок :variables
        process_variables()
        # Если есть блок с меткой 'menu', парсим его как основное меню
        if "menu" in LABELS:
            parse_menu_label(LABELS["menu"])
            print("Меню успешно загружено и распарсено.")
        else:
            print("Не найдена метка ':menu' в файле.")
    except Exception as e:
        print(f"Ошибка при загрузке меню: {e}")

# Загружаем меню при старте приложения
load_menu()

# HTML-шаблон главной страницы (меню)
INDEX_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{{ title }}</title>
  <style>
    body { font-family: monospace; background-color: #000; color: #0f0; padding: 20px; }
    h3 { text-align: center; }
    .menu { margin-top: 20px; }
    .item { margin: 5px 0; white-space: pre; }
    a { color: #0f0; text-decoration: none; }
    .item:has(a):hover { background-color: #0f0; color: #fff; }
    .item:has(a):hover a { color: #fff; }
    .gap { color: #888; }
  </style>
</head>
<body>
  <h3>{{ title }}</h3>
  <div class="menu">{% for item in items %}{% if item.is_gap %}<div class="item gap">{{ item.label }}</div>{% elif item.key %}<div class="item"><a href="/select/{{ item.key }}">{{ item.label }}</a></div>{% endif %}{% endfor %}</div>
</body>
</html>"""


# HTML-шаблон для отображения выбранной опции (блок метки)
SELECT_TEMPLATE = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Выбран: {{ key }}</title>
  <style>
    body { font-family: monospace; background-color: #000; color: #0f0; padding: 20px; }
    pre { background-color: #111; padding: 10px; }
    a { color: #0f0; text-decoration: none; }
  </style>
</head>
<body>
  <h1>Опция: {{ key }} - {{ label }}</h1>
  {% if block %}
    <pre>{{ block }}</pre>
  {% else %}
    <p>Нет данных для выбранного пункта.</p>
  {% endif %}
  <p><a href="/">Вернуться в меню</a></p>
</body>
</html>
"""

@app.route("/")
def index():
    load_menu()
    return render_template_string(INDEX_TEMPLATE, title=MENU_TITLE, items=MENU_ITEMS)

@app.route("/select/<key>")
def select(key):
    # Находим пункт меню по ключу (если ключ не пустой)
    item = next((item for item in MENU_ITEMS if item['key'] == key and not item['is_gap']), None)
    if not item:
        abort(404)

    # Если для выбранного ключа есть блок с меткой, получаем его содержимое
    block_lines = LABELS.get(key)
    if block_lines:
        block_text = "\n".join(substitute_variables(line) for line in block_lines)
    else:
        block_text = ""

    return render_template_string(SELECT_TEMPLATE, key=key, label=item['label'], block=block_text)

if __name__ == "__main__":
    # Запускаем Flask-сервер
    app.run(debug=True)
