#!/usr/bin/env python3
"""
Тестовый скрипт для проверки структуры путей интеграционного теста
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def test_path_structure():
    """Тестирует создание структуры путей для интеграционного теста"""
    print("🧪 Тестирование структуры путей для интеграционного теста...")
    
    # Загружаем переменные окружения
    load_dotenv()
    
    base_path = os.getenv("BASE_PATH")
    if not base_path:
        print("❌ BASE_PATH не найден в .env файле")
        return False
    
    print(f"✅ BASE_PATH: {base_path}")
    
    # Создаем временную папку внутри BASE_PATH
    base_path_obj = Path(base_path)
    temp_dir_name = f"tmp_test_{int(time.time())}"
    temp_path = base_path_obj / temp_dir_name
    
    print(f"📁 Создаем временную папку: {temp_path}")
    temp_path.mkdir(exist_ok=True)
    
    # Создаем структуру папок
    category_path = temp_path / "TestCategory"
    category_path.mkdir(exist_ok=True)
    
    project_path = category_path / "test_project"
    project_path.mkdir(exist_ok=True)
    
    print(f"📂 Структура создана:")
    print(f"   {temp_path}")
    print(f"   └── TestCategory")
    print(f"       └── test_project")
    
    # Проверяем, что мы находимся внутри BASE_PATH
    current_path = str(project_path.absolute())
    if not current_path.startswith(base_path):
        print(f"❌ Ошибка: {current_path} не находится внутри {base_path}")
        return False
    
    print(f"✅ Путь {current_path} находится внутри {base_path}")
    
    # Получаем относительный путь от BASE_PATH
    rel_to_base = os.path.relpath(current_path, base_path)
    parts = rel_to_base.split(os.sep)
    
    print(f"📊 Относительный путь: {rel_to_base}")
    print(f"📊 Части пути: {parts}")
    
    # Проверяем, что путь достаточно длинный (минимум Категория/Проект)
    if len(parts) < 2:
        print(f"❌ Путь слишком короткий: {len(parts)} частей, нужно минимум 2")
        return False
    
    print(f"✅ Путь имеет достаточную длину: {len(parts)} частей")
    
    # Определяем папку проекта (две директории выше)
    project_local_path = os.path.join(base_path, parts[0], parts[1])
    print(f"📁 Путь к проекту: {project_local_path}")
    
    # Проверяем, что папка проекта существует
    if not os.path.isdir(project_local_path):
        print(f"❌ Папка проекта не найдена: {project_local_path}")
        return False
    
    print(f"✅ Папка проекта найдена: {project_local_path}")
    
    # Получаем относительный путь к проекту относительно base_path
    relative_path = os.path.relpath(project_local_path, base_path)
    print(f"📊 Относительный путь к проекту: {relative_path}")
    
    # Очистка
    import shutil
    shutil.rmtree(temp_path)
    print(f"🧹 Временная папка удалена: {temp_path}")
    
    print("\n🎉 Тест структуры путей прошел успешно!")
    return True


if __name__ == "__main__":
    try:
        import time
        success = test_path_structure()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1) 