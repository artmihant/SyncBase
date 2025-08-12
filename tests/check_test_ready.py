#!/usr/bin/env python3
"""
Скрипт для проверки готовности к запуску интеграционного теста
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def check_requirements():
    """Проверяет наличие всех необходимых компонентов для тестирования"""
    print("🔍 Проверка готовности к интеграционному тестированию...")
    print("=" * 60)
    
    all_ok = True
    
    # Проверка Python версии
    print(f"🐍 Python версия: {sys.version}")
    if sys.version_info < (3, 7):
        print("❌ Требуется Python 3.7+")
        all_ok = False
    else:
        print("✅ Python версия подходит")
    
    # Проверка .env файла
    print(f"\n📄 Проверка .env файла...")
    if not os.path.exists(".env"):
        print("❌ Файл .env не найден")
        all_ok = False
    else:
        print("✅ Файл .env найден")
        
        # Загружаем переменные окружения
        load_dotenv()
        
        # Проверка YANDEX_DISK_TOKEN
        yandex_token = os.getenv("YANDEX_DISK_TOKEN")
        if not yandex_token:
            print("❌ YANDEX_DISK_TOKEN не найден в .env")
            all_ok = False
        else:
            print(f"✅ YANDEX_DISK_TOKEN найден: {yandex_token[:10]}...")
        
        # Проверка BASE_PATH
        base_path = os.getenv("BASE_PATH")
        if not base_path:
            print("❌ BASE_PATH не найден в .env")
            all_ok = False
        else:
            print(f"✅ BASE_PATH найден: {base_path}")
            
            # Проверка существования базовой папки
            if not os.path.exists(base_path):
                print(f"❌ Базовая папка {base_path} не существует")
                all_ok = False
            else:
                print(f"✅ Базовая папка {base_path} существует")
    
    # Проверка test_project папки
    print(f"\n📁 Проверка test_project папки...")
    if not os.path.exists("test_project"):
        print("❌ Папка test_project не найдена")
        all_ok = False
    else:
        print("✅ Папка test_project найдена")
        
        # Проверка содержимого
        test_project_path = Path("test_project")
        required_files = [".syncignore", "README.md", "package.json"]
        
        for file_name in required_files:
            file_path = test_project_path / file_name
            if file_path.exists():
                print(f"  ✅ {file_name} найден")
            else:
                print(f"  ⚠️ {file_name} не найден")
    
    # Проверка sync_project.py
    print(f"\n📜 Проверка sync_project.py...")
    if not os.path.exists("sync_project.py"):
        print("❌ Файл sync_project.py не найден")
        all_ok = False
    else:
        print("✅ Файл sync_project.py найден")
    
    # Проверка sync_item.py
    print(f"\n📜 Проверка sync_item.py...")
    if not os.path.exists("sync_item.py"):
        print("❌ Файл sync_item.py не найден")
        all_ok = False
    else:
        print("✅ Файл sync_item.py найден")
    
    # Проверка yandex_disk_client.py
    print(f"\n📜 Проверка yandex_disk_client.py...")
    if not os.path.exists("yandex_disk_client.py"):
        print("❌ Файл yandex_disk_client.py не найден")
        all_ok = False
    else:
        print("✅ Файл yandex_disk_client.py найден")
    
    # Проверка зависимостей Python
    print(f"\n📦 Проверка Python зависимостей...")
    try:
        import dotenv
        print("✅ python-dotenv установлен")
    except ImportError:
        print("❌ python-dotenv не установлен")
        print("💡 Установите: pip install python-dotenv")
        all_ok = False
    
    # Итоговая оценка
    print("\n" + "=" * 60)
    if all_ok:
        print("🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ! Можно запускать интеграционный тест.")
        print("\n🚀 Запуск теста:")
        print("   python3 test_sync_project_integration.py")
        print("   или")
        print("   python3 run_integration_test.py")
    else:
        print("⚠️ НЕКОТОРЫЕ ПРОВЕРКИ НЕ ПРОЙДЕНЫ!")
        print("💡 Исправьте ошибки перед запуском теста.")
    
    return all_ok


if __name__ == "__main__":
    try:
        success = check_requirements()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1) 