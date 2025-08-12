## SyncBase — синхронизатор базы проектов с Яндекс.Диском

Инструмент для синхронизации древа файлов и папок проектов между локальной базой (`BASE_PATH`) и облаком (Яндекс.Диск, пространство `app:/`). Точка входа — `sync_base.py`.

### Требования
- Python 3.7+
- Установлен пакет `python-dotenv`
- Файл `.env` в корне репозитория с переменными:

```bash
YANDEX_DISK_TOKEN="ваш_oauth_токен"
BASE_PATH="ваш/путь/до/папки/с/проектами"
```

## Быстрый старт

```bash
# Показать список категорий/проектов (локально и в облаке)
python3 sync_base.py list

# Из папки проекта: показать статус / сохранить / загрузить
python3 sync_base.py status
python3 sync_base.py save
python3 sync_base.py load

# Из папки категории: все проекты или конкретный
python3 sync_base.py status all
python3 sync_base.py save MyProject

# Глобально (из любого места):
python3 sync_base.py status all all
python3 sync_base.py save Docs all
python3 sync_base.py load Docs MyProject
```

## Команды

### list
Показывает все категории и проекты, объединяя локальные и облачные. Проекты помечаются как `[local]`, `[cloud]` или обоими.

```bash
python3 sync_base.py list
```

### status | save | load
Команды поддерживают контекстные и глобальные формы.

- Из-под папки проекта:
  - `python3 sync_base.py status`
  - `python3 sync_base.py save`
  - `python3 sync_base.py load`

- Из-под папки категории:
  - `python3 sync_base.py status all`
  - `python3 sync_base.py status <project_name>`
  - Аналогично для `save` и `load`

- В любом месте (глобально):
  - `python3 sync_base.py status all all`
  - `python3 sync_base.py status <category_name> all`
  - `python3 sync_base.py status <category_name> <project_name>`
  - Аналогично для `save` и `load`

Подсказка по синтаксису выводится автоматически при неверных аргументах.

