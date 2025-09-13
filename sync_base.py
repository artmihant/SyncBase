#!/usr/bin/env python3

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dotenv import load_dotenv

# Добавляем текущую директорию в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sync_project import SyncProject, SyncIgnore
from yandex_disk_client import YandexDiskClient


class SyncBase:
    """Класс для управления всей базой знаний и точка входа CLI."""

    def __init__(self, base_path: str, token: str):
        self.base_path: Path = Path(base_path)
        self.token: str = token
        self.cloud_client = YandexDiskClient(token)

    # ---------- Вспомогательные методы обнаружения структуры ----------
    def _get_local_categories(self) -> List[str]:
        if not self.base_path.exists():
            return []
        categories: List[str] = []
        base_syncignore = self._read_base_syncignore()

        for entry in sorted(self.base_path.iterdir()):
            if entry.is_dir():
                category_name = entry.name
                # Проверяем, нужно ли игнорировать эту категорию
                if not base_syncignore.should_ignore(category_name, is_directory=True):
                    categories.append(category_name)
        return categories

    def _get_local_projects(self, category: str) -> List[str]:
        category_path = self.base_path / category
        if not category_path.exists() or not category_path.is_dir():
            return []
        projects: List[str] = []
        category_syncignore = self._read_category_syncignore(category)

        for entry in sorted(category_path.iterdir()):
            if entry.is_dir():
                project_name = entry.name
                # Проверяем, нужно ли игнорировать этот проект
                if not category_syncignore.should_ignore(project_name, is_directory=True):
                    projects.append(project_name)
        return projects

    def _get_cloud_categories(self) -> List[str]:
        items = self.cloud_client.list('app:/') or []
        base_syncignore = self._read_base_syncignore()

        categories = []
        for item in items:
            if item.get('type') == 'dir':
                category_name = item.get('name')
                # Проверяем, нужно ли игнорировать эту категорию
                if not base_syncignore.should_ignore(category_name, is_directory=True):
                    categories.append(category_name)

        return sorted(categories)

    def _get_cloud_projects(self, category: str) -> List[str]:
        cloud_path = f"app:/{category}"
        items = self.cloud_client.list(cloud_path) or []
        category_syncignore = self._read_category_syncignore(category)

        projects = []
        for item in items:
            if item.get('type') == 'dir':
                project_name = item.get('name')
                # Проверяем, нужно ли игнорировать этот проект
                if not category_syncignore.should_ignore(project_name, is_directory=True):
                    projects.append(project_name)

        return sorted(projects)

    # ---------- Методы для работы с .syncignore ----------
    def _read_base_syncignore(self) -> SyncIgnore:
        """Читает .syncignore из корня базы для игнорирования категорий"""
        syncignore_path = self.base_path / '.syncignore'
        syncignore = SyncIgnore()

        if syncignore_path.exists() and syncignore_path.is_file():
            try:
                content = syncignore_path.read_text(encoding='utf-8')
                syncignore.parse_rules(content)
            except Exception as e:
                print(f"⚠️ Не удалось прочитать базовый .syncignore: {e}")

        return syncignore

    def _read_category_syncignore(self, category: str) -> SyncIgnore:
        """Читает .syncignore из папки категории для игнорирования проектов"""
        category_path = self.base_path / category
        syncignore_path = category_path / '.syncignore'
        syncignore = SyncIgnore()

        if syncignore_path.exists() and syncignore_path.is_file():
            try:
                content = syncignore_path.read_text(encoding='utf-8')
                syncignore.parse_rules(content)
            except Exception as e:
                print(f"⚠️ Не удалось прочитать .syncignore для категории '{category}': {e}")

        return syncignore

    def _resolve_context(self, cwd_path: str) -> Dict[str, Optional[str]]:
        """Определяет контекст запуска: проект/категория/вне базы.

        Returns:
            dict(level='project'|'category'|'outside'|'base', category, project)
        """
        current_path = os.path.abspath(cwd_path)
        base_path_abs = os.path.abspath(str(self.base_path))

        if not current_path.startswith(base_path_abs.rstrip(os.sep) + os.sep):
            # Не внутри базы
            return {"level": "outside", "category": None, "project": None}

        rel_to_base = os.path.relpath(current_path, base_path_abs)
        parts = rel_to_base.split(os.sep)
        if len(parts) == 1 and parts[0] == '.':
            return {"level": "base", "category": None, "project": None}

        if len(parts) >= 2:
            category_name = parts[0]
            project_name = parts[1]
            return {"level": "project", "category": category_name, "project": project_name}
        elif len(parts) == 1:
            category_name = parts[0]
            return {"level": "category", "category": category_name, "project": None}

        return {"level": "outside", "category": None, "project": None}

    # ---------- Печать списков ----------
    def cmd_list(self):
        """Список всех проектов во всех категориях, включая облачные."""
        print("📋 Список проектов (локально/облако):")
        local_categories = set(self._get_local_categories())
        cloud_categories = set(self._get_cloud_categories())
        all_categories = sorted(local_categories | cloud_categories)

        print(f"🔍 Найдено категорий: {len(all_categories)} (локальных: {len(local_categories)}, облачных: {len(cloud_categories)})")

        for category in all_categories:
            # Определяем статус категории
            category_marks: List[str] = []
            if category in local_categories:
                category_marks.append("local")
            if category in cloud_categories:
                category_marks.append("cloud")
            category_mark_str = "/".join(category_marks) if category_marks else "—"

            local_projects = set(self._get_local_projects(category))
            cloud_projects = set(self._get_cloud_projects(category))
            all_projects = sorted(local_projects | cloud_projects)
            print(f"\n📂 Категория: {category} [{category_mark_str}]")
            if not all_projects:
                print("  (пусто)")
                continue
            for project in all_projects:
                marks: List[str] = []
                if project in local_projects:
                    marks.append("local")
                if project in cloud_projects:
                    marks.append("cloud")
                mark_str = "/".join(marks) if marks else "—"
                print(f"  - {project} [{mark_str}]")

    # ---------- Массовые операции ----------
    def _iter_selected_projects(
        self,
        selector: Tuple[str, Optional[str], Optional[str]]
    ) -> List[Tuple[str, str]]:
        """Возвращает список пар (category, project) согласно селектору.

        selector: (scope, category, project)
        scope ∈ { 'single', 'category_all', 'category_one', 'all_all' }
        """
        scope, category, project = selector
        selected: List[Tuple[str, str]] = []

        if scope == 'single' and category and project:
            selected.append((category, project))
            return selected

        if scope == 'category_one' and category and project:
            selected.append((category, project))
            return selected

        if scope == 'category_all' and category:
            local = set(self._get_local_projects(category))
            cloud = set(self._get_cloud_projects(category))
            for proj in sorted(local | cloud):
                selected.append((category, proj))
            return selected

        if scope == 'all_all':
            local_c = set(self._get_local_categories())
            cloud_c = set(self._get_cloud_categories())
            for cat in sorted(local_c | cloud_c):
                local = set(self._get_local_projects(cat))
                cloud = set(self._get_cloud_projects(cat))
                for proj in sorted(local | cloud):
                    selected.append((cat, proj))
            return selected

        return selected

    def _run_for_project(self, command: str, category: str, project: str):
        sp = SyncProject(self.base_path, category, project, self.token)
        if command == 'status':
            sp.show_status()
        elif command == 'save':
            sp.sync_save()
        elif command == 'load':
            sp.sync_load()
        else:
            print(f"❌ Неизвестная операция для проекта: {command}")

    # ---------- Разбор аргументов: выбор проекта(ов) ----------
    def _select_targets(self, command: str, ctx: Dict[str, Optional[str]], args: List[str]) -> List[Tuple[str, str]]:
        """Преобразует контекст + аргументы команды в список целей (category, project)."""
        level = ctx.get('level')
        category = ctx.get('category')
        project = ctx.get('project')

        # Вариант 1: запуск из-под проекта, без доп. аргументов
        if level == 'project' and not args:
            return self._iter_selected_projects(('single', category, project))

        # Вариант 2: запуск из-под категории с 1 аргументом: all | <project>
        if level == 'category' and len(args) == 1:
            if args[0] == 'all':
                return self._iter_selected_projects(('category_all', category, None))
            return self._iter_selected_projects(('category_one', category, args[0]))

        # Вариант 3: глобальная форма (работает одинаково из любой папки)
        #   - <category> <project>
        #   - <category> all
        #   - all all
        if len(args) == 2:
            a1, a2 = args[0], args[1]
            if a1 == 'all' and a2 == 'all':
                return self._iter_selected_projects(('all_all', None, None))
            if a1 != 'all' and a2 == 'all':
                return self._iter_selected_projects(('category_all', a1, None))
            if a1 != 'all' and a2 != 'all':
                return self._iter_selected_projects(('single', a1, a2))

        # Недостаточно/некорректно аргументов
        self._print_usage(command)
        sys.exit(1)

    def _print_usage(self, cmd: Optional[str] = None):
        base = "Использование:\n" \
               "  sync_base.py list\n" \
               "  sync_base.py status [all all | <category> all | <category> <project>]\n" \
               "  sync_base.py save   [all all | <category> all | <category> <project>]\n" \
               "  sync_base.py load   [all all | <category> all | <category> <project>]\n\n" \
               "При вызове из-под папки проекта: 'status' | 'save' | 'load' без аргументов.\n" \
               "При вызове из-под папки категории: 'status|save|load all' или 'status|save|load <project>'."
        if cmd:
            print(f"❗ Уточните аргументы для команды '{cmd}'.")
        print(base)


def main():
    """Главная функция"""
    # Загружаем переменные окружения
    load_dotenv()
    
    YANDEX_DISK_TOKEN = os.getenv("YANDEX_DISK_TOKEN")
    BASE_PATH = os.getenv("BASE_PATH")
    
    if not YANDEX_DISK_TOKEN or not BASE_PATH:
        print("❌ Не найдены необходимые переменные окружения YANDEX_DISK_TOKEN и/или BASE_PATH в .env файле.")
        sys.exit(1)
    
    # Создаем экземпляр менеджера базы знаний
    sync_base = SyncBase(BASE_PATH, YANDEX_DISK_TOKEN)

    # Извлекаем путь директории, из-под которой был вызван этот скрипт
    cwd_path = os.getcwd()

    # Обработка команд
    if len(sys.argv) < 2:
        sync_base._print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    if command == 'list':
        sync_base.cmd_list()
        sys.exit(0)

    if command not in {'status', 'save', 'load'}:
        print(f"❌ Неизвестная команда: {command}")
        sync_base._print_usage()
        sys.exit(1)

    ctx = sync_base._resolve_context(cwd_path)
    targets = sync_base._select_targets(command, ctx, args)

    if not targets:
        print("⚠️ Не найдено ни одного проекта для обработки.")
        sys.exit(0)

    # Выполнение выбранной операции для всех целей
    for category, project in targets:
        # Для 'save' имеет смысл работать только с локальными проектами
        if command == 'save':
            local_exists = (sync_base.base_path / category / project).is_dir()
            if not local_exists:
                print(f"⚠️ Пропуск save для {category}/{project}: локального проекта нет. Используйте 'load'.")
                continue
        # Для 'status' если локального проекта нет — сообщим и продолжим
        if command == 'status':
            local_exists = (sync_base.base_path / category / project).is_dir()
            if not local_exists:
                print(f"📊 {category}/{project}: локального проекта нет. 💡 Выполните 'load' для восстановления.")
                continue
        sync_base._run_for_project(command, category, project)


if __name__ == "__main__":
    main() 