#!/usr/bin/env python3
import re
import requests
from flask import Flask, render_template_string, abort

app = Flask(__name__)

# URL, с которого будет скачиваться файл меню iPXE.
REMOTE_MENU_URL = "http://192.168.0.163:5000/menu"  # Замените на нужный URL

# Глобальные переменные для хранения данных меню, меток, переменных и цветов
MENU_TITLE = ""
MENU_ITEMS = []   # Список пунктов меню: dict с ключами 'key', 'label' и 'is_gap'
LABELS = {}       # Словарь: имя метки -> список строк (блок команд)

# Глобальный словарь переменных.
# Здесь заданы значения по умолчанию, которые будут подставляться при встрече переменных в меню.
VARS = {
    "version": "1.7.5",
    "boot_mode": "EFI",
    "update": "true",
    "update_version": "2.3.0",
    "net0/mac": "FF:00:FF:00:FF",
    "ip": "192.168.0.101"
}

COLORS = {}       # Словарь: индекс -> значение цвета (например, "6" -> "#ffffff")
COLOR_PAIRS = {}  # Словарь: индекс пары -> словарь с ключами "foreground" и "background"

def fetch_menu_file(url):
    """
    Скачивает содержимое файла меню по указанному URL и возвращает список строк.
    """
    response = requests.get(url)
    response.raise_for_status()
    return response.text.splitlines()

def process_colors(lines):
    """
    Обрабатывает команды задания цветов из строк меню.
    Ищет команды вида:
      - colour --rgb 0xffffff 6
      - cpair --foreground 7 --background 2 2
    Обрабатываются только строки до первой метки (начинающейся с ":").
    """
    global COLORS, COLOR_PAIRS
    COLORS = {}
    COLOR_PAIRS = {}
    for line in lines:
        # Если достигнута первая метка, прекращаем обработку цветов
        if line.lstrip().startswith(":"):
            break
        line = line.strip()
        if line.startswith("colour"):
            # Пример: colour --rgb 0xffffff 6
            m = re.search(r'--rgb\s+([0-9a-fA-F]+)\s+(\d+)', line)
            if m:
                rgb = m.group(1)
                index = m.group(2)
                COLORS[index] = f"#{rgb}"
        elif line.startswith("cpair"):
            # Пример: cpair --foreground 7 --background 2 2
            m = re.search(r'--foreground\s+(\d+)\s+--background\s+(\d+)\s+(\d+)', line)
            if m:
                fg_index = m.group(1)
                bg_index = m.group(2)
                pair_index = m.group(3)
                fg_color = COLORS.get(fg_index, "#ffffff")
                bg_color = COLORS.get(bg_index, "#ff0000")  # по умолчанию красный для фона
                COLOR_PAIRS[pair_index] = {"foreground": fg_color, "background": bg_color}

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
        if line.startswith(":"):
            if current_label is not None:
                labels[current_label] = block
            parts = line.split()
            current_label = parts[0][1:]  # Убираем двоеточие
            block = [line]
        else:
            block.append(line)
    if current_label is not None:
        labels[current_label] = block
    return labels

def process_variables():
    """
    Обрабатывает блок переменных (метка :variables) и обновляет словарь VARS.
    Для каждой строки вида:
        set имя[:тип] значение
    выполняется подстановка уже известных переменных в значение.
    Если переменная уже задана в VARS (значение по умолчанию), то она будет перезаписана.
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
            value = substitute_variables(value)
            if value == "20:20":
                value = "    "  # Заменяем 20:20 на 4 пробела
            VARS[var_name] = value

def parse_menu_label(block_lines):
    """
    Парсит блок с меткой 'menu' для формирования заголовка меню и пунктов.
    """
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

def get_text_color():
    """
    Возвращает цвет, заданный командой `colour --rgb ...` с индексом 6,
    который используется как основной цвет всего текста.
    """
    return COLORS.get("6", "#ffffff")

def get_item_highlight_colors():
    """
    Возвращает цветовую пару для выделения пунктов меню, заданную командой
    'cpair --foreground 7 --background 2 2'.
    Если такой пары нет, используются цвета по умолчанию.
    """
    pair = COLOR_PAIRS.get("2", {"foreground": "#ffffff", "background": "#ff0000"})
    return pair["foreground"], pair["background"]

def load_menu():
    """
    Загружает меню iPXE с удалённого URL, обрабатывает цвета, разбивает его на блоки по меткам,
    обрабатывает переменные и парсит блок с меткой 'menu' для формирования меню.
    """
    global LABELS
    try:
        lines = fetch_menu_file(REMOTE_MENU_URL)
        # Обработка цветовых команд до первой метки
        process_colors(lines)
        # Разбиваем на блоки по меткам
        LABELS = parse_labels(lines)
        # Обрабатываем переменные (файл может задавать свои переменные, перезаписывая значения по умолчанию)
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

# Получаем основной цвет текста
TEXT_COLOR = get_text_color()
# Получаем цвета для выделения пунктов меню (например, при наведении)
ITEM_FG, ITEM_BG = get_item_highlight_colors()

# HTML-шаблон главной страницы (меню).
# При наведении на пункт меню используется цветовая пара с индексом 2.
INDEX_TEMPLATE = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{{{{ title }}}}</title>
  <style>
    body {{
      font-family: monospace;
      background-color: #000;
      color: {TEXT_COLOR};
      padding: 20px;
    }}
    h3 {{
      text-align: center;
    }}
    .menu {{
      margin-top: 20px;
    }}
    .item {{
      margin: 5px 0;
      white-space: pre;
    }}
    a {{
      color: {TEXT_COLOR};
      text-decoration: none;
    }}
    /* При наведении на пункт меню используем выделение по цветовой паре "2" */
    .item:has(a):hover {{
      background-color: {ITEM_BG};
      color: {ITEM_FG};
    }}
    .item:has(a):hover a {{
      color: {ITEM_FG};
    }}
    .gap {{
      color: #888;
    }}
  </style>
</head>
<body>
  <h3>{{{{ title }}}}</h3>
  <div class="menu">
    {{% for item in items %}}
      {{% if item.is_gap %}}
        <div class="item gap">{{{{ item.label }}}}</div>
      {{% elif item.key %}}
        <div class="item"><a href="/select/{{{{ item.key }}}}">{{{{ item.label }}}}</a></div>
      {{% endif %}}
    {{% endfor %}}
  </div>
</body>
</html>
"""

# HTML-шаблон для отображения выбранной опции (блок метки).
SELECT_TEMPLATE = f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Выбран: {{{{ key }}}}</title>
  <style>
    body {{
      font-family: monospace;
      background-color: #000;
      color: {TEXT_COLOR};
      padding: 20px;
    }}
    pre {{
      background-color: #111;
      padding: 10px;
    }}
    a {{
      color: {TEXT_COLOR};
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <h1>Опция: {{{{ key }}}} - {{{{ label }}}}</h1>
  {{% if block %}}
    <pre>{{{{ block }}}}</pre>
  {{% else %}}
    <p>Нет данных для выбранного пункта.</p>
  {{% endif %}}
  <p><a href="/">Вернуться в меню</a></p>
</body>
</html>
"""

@app.route("/")
def index():
    # Перезагружаем меню
    load_menu()
    text_color = get_text_color()
    item_fg, item_bg = get_item_highlight_colors()
    template = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{{{{ title }}}}</title>
  <style>
    body {{
      font-family: monospace;
      background-color: #000;
      color: {text_color};
      padding: 20px;
    }}
    h3 {{
      text-align: center;
    }}
    .menu {{
      margin-top: 20px;
    }}
    .item {{
      margin: 5px 0;
      white-space: pre;
    }}
    a {{
      color: {text_color};
      text-decoration: none;
    }}
    .item:has(a):hover {{
      background-color: {item_bg};
      color: {item_fg};
    }}
    .item:has(a):hover a {{
      color: {item_fg};
    }}
    .gap {{
      color: #888;
    }}
  </style>
</head>
<body>
  <h3>{{{{ title }}}}</h3>
  <div class="menu">
    {{% for item in items %}}
      {{% if item.is_gap %}}
        <div class="item gap">{{{{ item.label }}}}</div>
      {{% elif item.key %}}
        <div class="item"><a href="/select/{{{{ item.key }}}}">{{{{ item.label }}}}</a></div>
      {{% endif %}}
    {{% endfor %}}
  </div>
</body>
</html>
"""
    return render_template_string(template, title=MENU_TITLE, items=MENU_ITEMS)

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
    text_color = get_text_color()
    template = f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Выбран: {{{{ key }}}}</title>
  <style>
    body {{
      font-family: monospace;
      background-color: #000;
      color: {text_color};
      padding: 20px;
    }}
    pre {{
      background-color: #111;
      padding: 10px;
    }}
    a {{
      color: {text_color};
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <h1>Опция: {{{{ key }}}} - {{{{ label }}}}</h1>
  {{% if block %}}
    <pre>{{{{ block }}}}</pre>
  {{% else %}}
    <p>Нет данных для выбранного пункта.</p>
  {{% endif %}}
  <p><a href="/">Вернуться в меню</a></p>
</body>
</html>
"""
    return render_template_string(template, key=key, label=item['label'], block=block_text)

if __name__ == "__main__":
    # Запускаем Flask-сервер
    app.run(debug=True)
